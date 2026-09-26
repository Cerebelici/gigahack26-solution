"""Pixel annotations from the CV model, stored alongside their EPSG:32635 map geometry.

Pixel coordinates follow CVAT: origin at the top-left corner of pixel (0, 0), x to the right,
y downward. The raster's affine maps a pixel corner to its CRS; PostGIS applies it and then
reprojects to EPSG:32635, so the conversion never assumes a pixel size or a CRS.
"""

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import MAP_SRID, Annotation, Raster

Point = list[float]
Ring = list[Point]

ATTRIBUTES = (
    "vineyard_id",
    "row_id",
    "row_structure",
    "interrow_cover",
    "length_m",
    "grapevine_count",
    "area_m2",
    "area_ha",
)

GEOJSON_CRS = {"type": "name", "properties": {"name": f"urn:ogc:def:crs:EPSG::{MAP_SRID}"}}


def _as_geojson(geom):
    # Options 0: no per-geometry "crs" member; the collection declares EPSG:32635 once.
    return func.ST_AsGeoJSON(geom, 9, 0)


class UnplaceableRasterError(Exception):
    """The raster's CRS cannot be used by PostGIS to place pixel coordinates."""


def box_ring(box: dict[str, float]) -> Ring:
    return [
        [box["xtl"], box["ytl"]],
        [box["xbr"], box["ytl"]],
        [box["xbr"], box["ybr"]],
        [box["xtl"], box["ybr"]],
    ]


def _coords(ring: Ring, close: bool) -> str:
    points = ring + [ring[0]] if close and ring[0] != ring[-1] else ring
    return ", ".join(f"{x!r} {y!r}" for x, y in points)


def pixel_wkt(shape: str, rings: list[Ring]) -> str:
    if shape == "polyline":
        return f"LINESTRING({_coords(rings[0], close=False)})"
    return "POLYGON(" + ", ".join(f"({_coords(ring, close=True)})" for ring in rings) + ")"


def map_geometry(wkt: str, raster: Raster):
    """SQL expression placing pixel-space WKT on the map through the raster's geotransform and CRS."""
    if raster.srid is None:
        raise UnplaceableRasterError("The raster's CRS has no EPSG code, so annotations cannot be placed on it.")
    a, b, c, d, e, f = raster.transform
    # ST_Affine(g, a, b, d, e, xoff, yoff): x' = a*x + b*y + xoff, y' = d*x + e*y + yoff.
    in_raster_crs = func.ST_SetSRID(func.ST_Affine(func.ST_GeomFromText(wkt, 0), a, b, d, e, c, f), raster.srid)
    return func.ST_Transform(in_raster_crs, MAP_SRID)


def create_annotation(
    db: Session,
    project_id: int,
    raster: Raster,
    label: str,
    shape: str,
    rings: list[Ring],
    box: dict[str, float] | None,
    attributes: dict[str, Any],
) -> Annotation:
    annotation = Annotation(
        project_id=project_id,
        raster_id=raster.id,
        label=label,
        shape=shape,
        pixel_rings=rings,
        pixel_box=box,
        geom=map_geometry(pixel_wkt(shape, rings), raster),
        **{key: attributes.get(key) for key in ATTRIBUTES},
    )
    db.add(annotation)
    db.flush()
    return annotation


def to_feature(annotation: Annotation, geojson: str) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "id": annotation.id,
        "label": annotation.label,
        **{key: getattr(annotation, key) for key in ATTRIBUTES},
        "pixelRings": annotation.pixel_rings,
        "rasterId": annotation.raster_id,
    }
    if annotation.pixel_box is not None:
        properties["pixelBox"] = annotation.pixel_box
    return {"type": "Feature", "id": annotation.id, "geometry": json.loads(geojson), "properties": properties}


def feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "crs": GEOJSON_CRS, "features": features}


def features_by_project(db: Session, project_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {pid: [] for pid in project_ids}
    if not project_ids:
        return grouped
    rows = db.execute(
        select(Annotation, _as_geojson(Annotation.geom))
        .where(Annotation.project_id.in_(project_ids))
        .order_by(Annotation.id)
    )
    for annotation, geojson in rows:
        grouped[annotation.project_id].append(to_feature(annotation, geojson))
    return grouped


def feature_by_id(db: Session, annotation: Annotation) -> dict[str, Any]:
    geojson = db.scalar(select(_as_geojson(Annotation.geom)).where(Annotation.id == annotation.id))
    return to_feature(annotation, geojson)
