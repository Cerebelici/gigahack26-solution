import logging
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, BeforeValidator, Field, StringConstraints, ValidationError, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import DataError, InternalError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db import get_db
from app.models import Annotation, Project, Raster, User
from app.routers.process_tif import ProcessTifResponse, tile_url
from app.security import current_user
from app.services.annotations import (
    UnplaceableRasterError,
    box_ring,
    create_annotation,
    feature_by_id,
    insert_annotations,
)
from app.services.cvat_annotations import items_on_raster
from app.services.mosaic import store_project_imagery
from app.services.project_features import features_json, forget as forget_features
from app.services.route import StartInsideObstacle, plan_route as plan_walking_route
from app.services.tif import RasterError, StoredRaster, remove_raster

router = APIRouter(prefix="/projects", tags=["projects"])
logger = logging.getLogger(__name__)
ANNOTATION_BATCH = 2000

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Coordinate = Annotated[float, Field(allow_inf_nan=False)]
Point = tuple[Coordinate, Coordinate]
Ident = Annotated[str | None, BeforeValidator(lambda v: str(v) if isinstance(v, int) else v)]
Measure = Annotated[float | None, Field(ge=0, allow_inf_nan=False)]


class ProjectWrite(BaseModel):
    name: Name


RasterOut = ProcessTifResponse


class ProjectSummary(BaseModel):
    id: int
    name: str
    raster: RasterOut | None
    createdAt: datetime
    updatedAt: datetime


class ProjectOut(ProjectSummary):
    features: dict[str, Any]


class PixelBox(BaseModel):
    xtl: Coordinate
    ytl: Coordinate
    xbr: Coordinate
    ybr: Coordinate

    @model_validator(mode="after")
    def _ordered(self) -> "PixelBox":
        if self.xbr <= self.xtl or self.ybr <= self.ytl:
            raise ValueError("box needs xbr > xtl and ybr > ytl.")
        return self


class AnnotationCreate(BaseModel):
    """Pixel coordinates on the project's current raster: origin top-left, x right, y down.

    `rings` is one ring `[[x, y], ...]`, or a list of rings for a polygon with holes.
    """

    label: Literal["vineyard", "waste", "row", "interrow_area"]
    rings: list[Point] | list[list[Point]] | None = None
    box: PixelBox | None = None
    vineyard_id: Ident = None
    row_id: Ident = None
    row_structure: Literal["regular", "disrupted", "unassessable"] | None = None
    interrow_cover: Literal["bare_soil", "vegetation", "mixed", "unassessable"] | None = None
    length_m: Measure = None
    grapevine_count: Annotated[int | None, Field(ge=0)] = None
    area_m2: Measure = None
    area_ha: Measure = None

    @model_validator(mode="after")
    def _shape_matches_label(self) -> "AnnotationCreate":
        if (self.rings is None) == (self.box is None):
            raise ValueError("Send exactly one of 'rings' or 'box'.")
        if self.box is not None and self.label != "waste":
            raise ValueError("Only 'waste' may be sent as a box; use 'rings'.")
        rings = self.pixel_rings()
        if self.label == "row":
            if len(rings) != 1 or len(rings[0]) < 2 or len(set(map(tuple, rings[0]))) < 2:
                raise ValueError("A 'row' polyline needs one ring of at least two distinct points.")
        elif rings and not all(len(set(map(tuple, ring))) >= 3 for ring in rings):
            raise ValueError("Each polygon ring needs at least three distinct points.")
        if self.rings is not None and not rings:
            raise ValueError("'rings' is empty.")
        return self

    @property
    def shape(self) -> str:
        if self.box is not None:
            return "box"
        return "polyline" if self.label == "row" else "polygon"

    def pixel_rings(self) -> list[list[list[float]]]:
        if self.box is not None:
            return [box_ring(self.box.model_dump())]
        rings = self.rings or []
        if rings and isinstance(rings[0], tuple):
            rings = [rings]
        return [[[x, y] for x, y in ring] for ring in rings]


class RouteRequest(BaseModel):
    """Obstacle rings, canopy rings, the start, and the targets, in EPSG:32635 metres.

    Each obstacle ring is a solid polygon. A two-point row is not a polygon.
    Canopy rings are vine footprints the walk must not cross.
    """

    routeType: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    obstacles: list[list[Point]]
    start: Point
    targets: list[Point]
    canopies: list[list[Point]] = Field(default_factory=list)


class RouteLine(BaseModel):
    type: Literal["LineString"] = "LineString"
    coordinates: list[Point]


class RouteResponse(BaseModel):
    route: RouteLine
    length_m: float
    unreachable: list[Point]


def owned_project(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def _latest_rasters(db: Session, project_ids: list[int]) -> dict[int, Raster]:
    if not project_ids:
        return {}
    rows = db.scalars(
        select(Raster)
        .where(Raster.project_id.in_(project_ids))
        .order_by(Raster.project_id, Raster.created_at.desc(), Raster.id)
        .ext(distinct_on(Raster.project_id))
    )
    return {raster.project_id: raster for raster in rows}


def _raster_out(request: Request, raster: Raster) -> RasterOut:
    return RasterOut(
        id=raster.id,
        boundsEpsg32635=tuple(raster.bounds_epsg32635),
        tileUrl=tile_url(request, raster.id),
        minzoom=raster.minzoom,
        maxzoom=raster.maxzoom,
    )


def _summaries(request: Request, db: Session, projects: list[Project]) -> list[ProjectSummary]:
    ids = [project.id for project in projects]
    rasters = _latest_rasters(db, ids)
    return [
        ProjectSummary(
            id=project.id,
            name=project.name,
            raster=_raster_out(request, rasters[project.id]) if project.id in rasters else None,
            createdAt=project.created_at,
            updatedAt=project.updated_at,
        )
        for project in projects
    ]


def _geojson(body: bytes) -> Response:
    return Response(content=body, media_type="application/json")


def _project_body(summary: ProjectSummary, features: bytes) -> bytes:
    """`ProjectOut` as JSON: the summary, with the already-rendered features as its last member."""
    return summary.model_dump_json().encode()[:-1] + b',"features":' + features + b"}"


@router.post("", status_code=201)
def create_project(
    body: ProjectWrite, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> ProjectSummary:
    project = Project(owner_id=user.id, name=body.name)
    db.add(project)
    db.commit()
    return _summaries(request, db, [project])[0]


@router.get("")
def list_projects(
    request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[ProjectSummary]:
    projects = list(
        db.scalars(select(Project).where(Project.owner_id == user.id).order_by(Project.updated_at.desc(), Project.id))
    )
    return _summaries(request, db, projects)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(request: Request, project: Project = Depends(owned_project), db: Session = Depends(get_db)) -> Response:
    summary = _summaries(request, db, [project])[0]
    return _geojson(_project_body(summary, features_json(db, project.id)))


@router.patch("/{project_id}")
def update_project(
    body: ProjectWrite, request: Request, project: Project = Depends(owned_project), db: Session = Depends(get_db)
) -> ProjectSummary:
    project.name = body.name
    db.commit()
    return _summaries(request, db, [project])[0]


@router.delete("/{project_id}", status_code=204, response_model=None)
def delete_project(project: Project = Depends(owned_project), db: Session = Depends(get_db)) -> Response:
    raster_ids = list(db.scalars(select(Raster.id).where(Raster.project_id == project.id)))
    db.delete(project)
    db.commit()
    forget_features(project.id)
    for raster_id in raster_ids:
        remove_raster(raster_id)
    return Response(status_code=204)


def _annotation_bodies(items: list[dict[str, Any]]) -> list[AnnotationCreate]:
    """Pixel shapes, as the same annotations `POST .../annotations` accepts.

    A shape with an unusable attribute is kept without its attributes; one with unusable geometry is skipped.
    """
    bodies: list[AnnotationCreate] = []
    for item in items:
        points = [(x, y) for x, y in item["points"]]
        if item["shape"] == "rectangle":
            xs = [x for x, _ in points]
            ys = [y for _, y in points]
            shape: dict[str, Any] = {"box": {"xtl": min(xs), "ytl": min(ys), "xbr": max(xs), "ybr": max(ys)}}
        else:
            shape = {"rings": points}
        attributes = {key: value for key, value in (item.get("attributes") or {}).items() if value != ""}
        for candidate in (attributes, {}):
            try:
                bodies.append(AnnotationCreate(label=item["label"], **shape, **candidate))
                break
            except ValidationError:
                continue
        else:
            logger.warning("Skipped %s %s: invalid shape.", item["label"], item.get("id"))
    return bodies


def store_catalog_annotations(
    db: Session, project: Project, raster: Raster, items: list[dict[str, Any]] | None = None
) -> int:
    """Replace the project's annotations with `items`, or with the catalog shapes on `raster`.

    `items` are already in this raster's pixels. None looks them up from annotations.xml.
    Keeps the existing annotations when there is nothing to store.
    """
    if items is None:
        items = items_on_raster(raster.transform, raster.crs_wkt, raster.width, raster.height, raster.bounds_epsg32635)
    bodies = _annotation_bodies(items)
    if not bodies:
        return 0
    if raster.srid is None:
        logger.warning("Raster %s has no EPSG code; its %d annotations were not stored.", raster.id, len(bodies))
        return 0
    # The raster's annotations describe the project now; the previous raster's would be duplicates.
    db.execute(delete(Annotation).where(Annotation.project_id == project.id))
    stored = 0
    for start in range(0, len(bodies), ANNOTATION_BATCH):
        stored += _store_annotation_batch(db, project.id, raster, bodies[start : start + ANNOTATION_BATCH])
    return stored


def _annotation_spec(body: AnnotationCreate) -> dict[str, Any]:
    return {
        "label": body.label,
        "shape": body.shape,
        "rings": body.pixel_rings(),
        "box": body.box.model_dump() if body.box else None,
        "attributes": body.model_dump(),
    }


def _store_annotation_batch(db: Session, project_id: int, raster: Raster, bodies: list[AnnotationCreate]) -> int:
    """One insert for the batch. A geometry PostGIS rejects is stored alone so the rest still land."""
    specs = [_annotation_spec(body) for body in bodies]
    try:
        with db.begin_nested():
            insert_annotations(db, project_id, raster, specs)
        return len(bodies)
    except (DataError, InternalError):
        logger.warning("Annotation batch of %d failed; retrying each shape.", len(bodies))
    stored = 0
    for spec in specs:
        try:
            with db.begin_nested():
                create_annotation(
                    db,
                    project_id,
                    raster,
                    label=spec["label"],
                    shape=spec["shape"],
                    rings=spec["rings"],
                    box=spec["box"],
                    attributes=spec["attributes"],
                )
            stored += 1
        except (DataError, InternalError):
            logger.warning("Skipped a %s annotation PostGIS could not place on raster %s.", spec["label"], raster.id)
    return stored


def _save_raster(
    db: Session, project: Project, stored: StoredRaster, items: list[dict[str, Any]] | None = None
) -> Raster:
    raster = Raster(
        id=stored.id,
        project_id=project.id,
        width=stored.width,
        height=stored.height,
        transform=list(stored.transform),
        crs_wkt=stored.crs_wkt,
        srid=stored.epsg,
        bounds_epsg32635=list(stored.bounds_epsg32635),
        minzoom=stored.minzoom,
        maxzoom=stored.maxzoom,
    )
    db.add(raster)
    db.flush()
    store_catalog_annotations(db, project, raster, items)
    project.updated_at = func.now()
    db.commit()
    return raster


@router.post("/{project_id}/raster")
async def upload_raster(
    request: Request,
    file: list[UploadFile] = File(default=[]),
    project: Project = Depends(owned_project),
    db: Session = Depends(get_db),
) -> RasterOut:
    """One GeoTIFF, or one or more zips. Every tile is mosaicked into a single map."""
    try:
        stored, items = await store_project_imagery(file)
    except RasterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        raster = await run_in_threadpool(_save_raster, db, project, stored, items)
    except BaseException:
        remove_raster(stored.id)
        raise
    return _raster_out(request, raster)


@router.get("/{project_id}/annotations", response_model=dict[str, Any])
def list_annotations(project: Project = Depends(owned_project), db: Session = Depends(get_db)) -> Response:
    return _geojson(features_json(db, project.id))


@router.post("/{project_id}/annotations", status_code=201)
def add_annotation(
    body: AnnotationCreate, project: Project = Depends(owned_project), db: Session = Depends(get_db)
) -> dict[str, Any]:
    raster = _latest_rasters(db, [project.id]).get(project.id)
    if raster is None:
        raise HTTPException(status_code=409, detail="Upload a raster to this project before adding annotations.")
    try:
        annotation = create_annotation(
            db,
            project.id,
            raster,
            label=body.label,
            shape=body.shape,
            rings=body.pixel_rings(),
            box=body.box.model_dump() if body.box else None,
            attributes=body.model_dump(),
        )
        feature = feature_by_id(db, annotation)
        db.commit()
    except UnplaceableRasterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (DataError, InternalError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="PostGIS could not place this geometry on the raster.") from exc
    return feature


@router.post("/{project_id}/routes")
def plan_route(body: RouteRequest, project: Project = Depends(owned_project)) -> RouteResponse:
    """Closed walk in EPSG:32635 metres that visits every reachable target and returns to the start."""
    try:
        planned = plan_walking_route(body.obstacles, body.start, body.targets, body.canopies)
    except StartInsideObstacle as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RouteResponse(
        route=RouteLine(coordinates=[(x, y) for x, y in planned.route.coords]),
        length_m=planned.length_m,
        unreachable=list(planned.unreachable),
    )
