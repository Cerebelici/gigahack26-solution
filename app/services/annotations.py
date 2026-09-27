"""Pixel annotations from the CV model, stored alongside their EPSG:32635 map geometry.

Pixel coordinates follow CVAT: origin at the top-left corner of pixel (0, 0), x to the right,
y downward. The raster's affine maps a pixel corner to its CRS; PostGIS applies it and then
reprojects to EPSG:32635, so the conversion never assumes a pixel size or a CRS.
"""

import json
from typing import Any

from sqlalchemy import Double, Integer, Text, bindparam, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY
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


_INSERT_ANNOTATIONS = text("""
INSERT INTO annotations (
    project_id, raster_id, label, shape, pixel_rings, pixel_box, geom,
    vineyard_id, row_id, row_structure, interrow_cover,
    length_m, grapevine_count, area_m2, area_ha
)
SELECT
    :project_id,
    :raster_id,
    label,
    shape,
    pixel_rings,
    pixel_box,
    ST_Transform(
        ST_SetSRID(ST_Affine(ST_GeomFromText(wkt, 0), :a, :b, :d, :e, :c, :f), :srid),
        :map_srid
    ),
    vineyard_id,
    row_id,
    row_structure,
    interrow_cover,
    length_m,
    grapevine_count,
    area_m2,
    area_ha
FROM unnest(
    CAST(:labels AS text[]),
    CAST(:shapes AS text[]),
    CAST(:pixel_rings AS text[])::jsonb[],
    CAST(:pixel_boxes AS text[])::jsonb[],
    CAST(:wkts AS text[]),
    CAST(:vineyard_ids AS text[]),
    CAST(:row_ids AS text[]),
    CAST(:row_structures AS text[]),
    CAST(:interrow_covers AS text[]),
    CAST(:lengths AS double precision[]),
    CAST(:grapevine_counts AS integer[]),
    CAST(:areas_m2 AS double precision[]),
    CAST(:areas_ha AS double precision[])
) AS t(
    label, shape, pixel_rings, pixel_box, wkt,
    vineyard_id, row_id, row_structure, interrow_cover,
    length_m, grapevine_count, area_m2, area_ha
)
""").bindparams(
    bindparam("labels", type_=ARRAY(Text())),
    bindparam("shapes", type_=ARRAY(Text())),
    bindparam("pixel_rings", type_=ARRAY(Text())),
    bindparam("pixel_boxes", type_=ARRAY(Text())),
    bindparam("wkts", type_=ARRAY(Text())),
    bindparam("vineyard_ids", type_=ARRAY(Text())),
    bindparam("row_ids", type_=ARRAY(Text())),
    bindparam("row_structures", type_=ARRAY(Text())),
    bindparam("interrow_covers", type_=ARRAY(Text())),
    bindparam("lengths", type_=ARRAY(Double())),
    bindparam("grapevine_counts", type_=ARRAY(Integer())),
    bindparam("areas_m2", type_=ARRAY(Double())),
    bindparam("areas_ha", type_=ARRAY(Double())),
)


def insert_annotations(db: Session, project_id: int, raster: Raster, specs: list[dict[str, Any]]) -> None:
    """Insert every spec in one statement. `rings` are pixel rings; `attributes` holds the optional fields."""
    if not specs:
        return
    a, b, c, d, e, f = raster.transform
    columns: dict[str, list[Any]] = {key: [] for key in ("label", "shape", "rings", "box", "wkt", *ATTRIBUTES)}
    for spec in specs:
        attributes = spec["attributes"]
        columns["label"].append(spec["label"])
        columns["shape"].append(spec["shape"])
        columns["rings"].append(json.dumps(spec["rings"]))
        columns["box"].append(json.dumps(spec["box"]) if spec["box"] is not None else None)
        columns["wkt"].append(pixel_wkt(spec["shape"], spec["rings"]))
        for key in ATTRIBUTES:
            columns[key].append(attributes.get(key))
    db.execute(
        _INSERT_ANNOTATIONS,
        {
            "project_id": project_id,
            "raster_id": raster.id,
            "a": a,
            "b": b,
            "c": c,
            "d": d,
            "e": e,
            "f": f,
            "srid": raster.srid,
            "map_srid": MAP_SRID,
            "labels": columns["label"],
            "shapes": columns["shape"],
            "pixel_rings": columns["rings"],
            "pixel_boxes": columns["box"],
            "wkts": columns["wkt"],
            "vineyard_ids": columns["vineyard_id"],
            "row_ids": columns["row_id"],
            "row_structures": columns["row_structure"],
            "interrow_covers": columns["interrow_cover"],
            "lengths": columns["length_m"],
            "grapevine_counts": columns["grapevine_count"],
            "areas_m2": columns["area_m2"],
            "areas_ha": columns["area_ha"],
        },
    )


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
