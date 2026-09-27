"""Write one folder per vineyard block: CVAT XML plus tiles masked to that block."""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize, shapes
from rasterio.transform import from_origin
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union

from src.blocks.catalog import TileSource
from src.blocks.mosaic import CoarseMosaic
from src.export.cvat_writer import format_points
from src.spatial.grid import TILE_PIXELS, TILE_SIZE_M, map_to_pixel, parse_tile_indices, tile_upper_left


def export_blocks(
    labels: np.ndarray,
    mosaic: CoarseMosaic,
    tiles: list[TileSource],
    output_dir: Path,
    min_tile_area_m2: float = 25.0,
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("V*"):
        if stale.is_dir() and stale.name[1:].isdigit():
            shutil.rmtree(stale)

    transform = from_origin(mosaic.origin_x, mosaic.origin_y, mosaic.gsd, mosaic.gsd)
    by_name = {tile.name: tile for tile in tiles}
    records = []
    ids = [int(i) for i in np.unique(labels) if i != 0]
    for block_id in ids:
        vineyard_id = f"V{block_id:02d}"
        geometry = _block_geometry(labels, block_id, transform)
        if geometry is None or geometry.is_empty:
            continue
        folder = output_dir / vineyard_id
        folder.mkdir(parents=True, exist_ok=True)
        tile_entries = []
        for name, (row0, col0) in mosaic.placements.items():
            window = labels[row0 : row0 + mosaic.cells, col0 : col0 + mosaic.cells]
            if not np.any(window == block_id):
                continue
            r, c = parse_tile_indices(name)
            x_ul, y_ul = tile_upper_left(r, c)
            tile_box = box(x_ul, y_ul - TILE_SIZE_M, x_ul + TILE_SIZE_M, y_ul)
            piece = geometry.intersection(tile_box)
            parts = _polygons(piece, min_tile_area_m2)
            if not parts:
                continue
            rings = [_pixel_ring(part, r, c) for part in parts]
            _write_masked_tile(by_name[name], folder / name, parts, x_ul, y_ul)
            tile_entries.append({"name": name, "rings": rings})
        if not tile_entries:
            shutil.rmtree(folder)
            continue
        area_m2 = float(geometry.area)
        _write_cvat(folder / "block.xml", vineyard_id, area_m2, tile_entries)
        records.append(
            {
                "vineyard_id": vineyard_id,
                "area_m2": area_m2,
                "tiles": [entry["name"] for entry in tile_entries],
                "geometry": geometry,
            }
        )
        print(f"  {vineyard_id}: {area_m2 / 10000:.3f} ha, {len(tile_entries)} tiles")

    _write_index(output_dir / "vineyard_blocks.xml", records)
    _write_zones_geojson(output_dir / "zones.geojson", records)
    return records


def rasterize_records(records: list[dict], height: int, width: int, origin_x: float, origin_y: float, gsd: float) -> np.ndarray:
    """Paint the convex block polygons onto the coarse map grid."""
    transform = from_origin(origin_x, origin_y, gsd, gsd)
    pairs = []
    for index, record in enumerate(records, start=1):
        pairs.append((record["geometry"], index))
    if not pairs:
        return np.zeros((height, width), dtype=np.int32)
    return rasterize(pairs, out_shape=(height, width), transform=transform, fill=0, dtype=np.int32)


def _block_geometry(labels: np.ndarray, block_id: int, transform):
    mask = labels == block_id
    parts = []
    for geom, value in shapes(labels.astype(np.int32), mask=mask, transform=transform):
        if int(value) != block_id:
            continue
        parts.append(shape(geom))
    if not parts:
        return None
    merged = unary_union(parts).buffer(0)
    # One convex outline. A concave edge was cutting through vine rows as a black notch.
    # 4.5 m keeps the outer vine row inside the outline. 1.5 m was clipping it.
    hull = merged.convex_hull.buffer(4.5, join_style=1)
    return hull.convex_hull


def _polygons(geom, min_area: float) -> list:
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom] if geom.area >= min_area else []
    if geom.geom_type in {"MultiPolygon", "GeometryCollection"}:
        found = []
        for part in geom.geoms:
            found.extend(_polygons(part, min_area))
        return found
    return []


def _pixel_ring(polygon, r: int, c: int) -> list[tuple[float, float]]:
    coords = list(polygon.exterior.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    ring = []
    for easting, northing in coords:
        px, py = map_to_pixel(r, c, easting, northing)
        ring.append((min(max(px, 0.0), TILE_PIXELS), min(max(py, 0.0), TILE_PIXELS)))
    return ring


def _write_masked_tile(tile: TileSource, dest: Path, parts: list, x_ul: float, y_ul: float) -> None:
    transform = from_origin(x_ul, y_ul, 0.025, 0.025)
    mask = rasterize(
        [(part, 1) for part in parts],
        out_shape=(TILE_PIXELS, TILE_PIXELS),
        transform=transform,
        fill=0,
        dtype=np.uint8,
    )
    with rasterio.open(tile.rasterio_path()) as src:
        image = src.read(indexes=(1, 2, 3))
        crs = src.crs
    if image.dtype != np.uint8:
        image = np.clip(image, 0, 255).astype(np.uint8)
    image[:, mask == 0] = 0
    profile = {
        "driver": "GTiff",
        "height": TILE_PIXELS,
        "width": TILE_PIXELS,
        "count": 3,
        "dtype": "uint8",
        "crs": crs or "EPSG:32635",
        "transform": transform,
        "compress": "deflate",
        "photometric": "RGB",
    }
    with rasterio.open(dest, "w", **profile) as dst:
        dst.write(image)


def _write_cvat(path: Path, vineyard_id: str, area_m2: float, tiles: list[dict]) -> None:
    root = ET.Element("annotations")
    root.append(ET.Comment(" Block territory for the next canopy model. Not a Marcaj canopy polygon. "))
    ET.SubElement(root, "version").text = "1.1"
    meta = ET.SubElement(root, "meta")
    task = ET.SubElement(meta, "task")
    ET.SubElement(task, "name").text = f"Vineyard block {vineyard_id}"
    labels = ET.SubElement(task, "labels")
    label = ET.SubElement(labels, "label")
    ET.SubElement(label, "name").text = "vineyard_block"
    ET.SubElement(label, "type").text = "polygon"
    attributes = ET.SubElement(label, "attributes")
    for attr_name in ("vineyard_id", "area_m2"):
        attribute = ET.SubElement(attributes, "attribute")
        ET.SubElement(attribute, "name").text = attr_name
        ET.SubElement(attribute, "input_type").text = "text"
    for image_id, tile in enumerate(tiles):
        image = ET.SubElement(
            root,
            "image",
            id=str(image_id),
            name=tile["name"],
            width=str(TILE_PIXELS),
            height=str(TILE_PIXELS),
        )
        for ring in tile["rings"]:
            if len(ring) < 3:
                continue
            polygon = ET.SubElement(
                image,
                "polygon",
                label="vineyard_block",
                source="auto",
                occluded="0",
                points=format_points(ring),
                z_order="0",
            )
            ET.SubElement(polygon, "attribute", name="vineyard_id").text = vineyard_id
            ET.SubElement(polygon, "attribute", name="area_m2").text = f"{area_m2:.1f}"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode"),
        encoding="utf-8",
    )


def _write_index(path: Path, records: list[dict]) -> None:
    root = ET.Element("vineyard_blocks", crs="EPSG:32635")
    for record in records:
        block = ET.SubElement(
            root,
            "block",
            id=record["vineyard_id"],
            area_m2=f"{record['area_m2']:.1f}",
            area_ha=f"{record['area_m2'] / 10000:.4f}",
        )
        geometry = record["geometry"]
        polygons = [geometry] if geometry.geom_type == "Polygon" else list(geometry.geoms)
        for polygon in polygons:
            if polygon.geom_type != "Polygon":
                continue
            coords = list(polygon.exterior.coords)
            text = ";".join(f"{x:.2f},{y:.2f}" for x, y in coords)
            ET.SubElement(block, "polygon").text = text
        for name in record["tiles"]:
            ET.SubElement(block, "tile", name=name)
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode"),
        encoding="utf-8",
    )


def _write_zones_geojson(path: Path, records: list[dict]) -> None:
    features = []
    for record in records:
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "vineyard_id": record["vineyard_id"],
                    "area_m2": round(record["area_m2"], 1),
                    "area_ha": round(record["area_m2"] / 10000, 4),
                    "tile_count": len(record["tiles"]),
                },
                "geometry": mapping(record["geometry"]),
            }
        )
    collection = {
        "type": "FeatureCollection",
        "name": "siret3_vineyard_blocks",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32635"}},
        "features": features,
    }
    path.write_text(json.dumps(collection))
