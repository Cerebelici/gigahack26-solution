"""Example-tile annotations from the CVAT 1.1 file at the repository root.

Pixel coordinates follow CVAT: origin at the top-left, x to the right, y downward.
If the file is missing or cannot be parsed, lookups return nothing so a valid TIFF
upload can still be streamed.
"""

import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, fromstring

from rasterio.crs import CRS
from rasterio.transform import Affine
from rasterio.warp import transform as reproject_points

logger = logging.getLogger(__name__)

ANNOTATIONS_PATH = Path(__file__).resolve().parents[2] / "annotations.xml"

_SHAPE_BY_TAG = {
    "polygon": "polygon",
    "polyline": "polyline",
    "box": "rectangle",
}

_catalogs: dict[str, dict[str, dict[str, Any]] | None] = {}


# Challenge tile grid in EPSG:32635: tile rNNN_cNNN has its top-left corner here and is 51.2 m square.
GRID_ORIGIN = (628992.0, 5221222.4)
TILE_SIZE_M = 51.2
TILE_NAME = re.compile(r"siret3_r(\d+)_c(\d+)\.tiff?$", re.IGNORECASE)
UTM = CRS.from_epsg(32635)


def catalog() -> dict[str, dict[str, Any]] | None:
    return load_catalog(ANNOTATIONS_PATH)


def tile_origin(name: str) -> tuple[float, float] | None:
    """EPSG:32635 top-left corner of a challenge tile, from its file name."""
    match = TILE_NAME.search(name)
    if not match:
        return None
    row, col = int(match[1]), int(match[2])
    return GRID_ORIGIN[0] + col * TILE_SIZE_M, GRID_ORIGIN[1] - row * TILE_SIZE_M


def items_on_raster(
    transform: Sequence[float],
    crs_wkt: str,
    width: int,
    height: int,
    bounds_epsg32635: Sequence[float],
) -> list[dict[str, Any]]:
    """Every catalog shape that lies on this raster, with its points in the raster's pixels.

    Shapes are placed by where their tile is on the challenge grid, not by the uploaded file's name,
    so a renamed tile, a resampled tile, and the whole mosaic all get them. A shape that is not
    entirely on the raster is left out.
    """
    images = catalog()
    if not images:
        return []
    min_x, min_y, max_x, max_y = bounds_epsg32635
    to_pixel = ~Affine(*transform)
    crs = CRS.from_wkt(crs_wkt)
    placed: list[dict[str, Any]] = []
    for name, image in images.items():
        origin = tile_origin(name)
        if origin is None:
            continue
        west, north = origin
        if west >= max_x or west + TILE_SIZE_M <= min_x or north <= min_y or north - TILE_SIZE_M >= max_y:
            continue
        sx = TILE_SIZE_M / image["width"]
        sy = TILE_SIZE_M / image["height"]
        for item in image["items"]:
            xs = [west + x * sx for x, _ in item["points"]]
            ys = [north - y * sy for _, y in item["points"]]
            if crs != UTM:
                xs, ys = reproject_points(UTM, crs, xs, ys)
            points = [to_pixel @ (x, y) for x, y in zip(xs, ys)]
            if all(0 <= px <= width and 0 <= py <= height for px, py in points):
                placed.append({**item, "points": [[px, py] for px, py in points]})
    return placed


def file_basename(filename: str | None) -> str:
    if not filename:
        return ""
    return filename.replace("\\", "/").rsplit("/", 1)[-1]


def annotations_for_filename(filename: str | None) -> dict[str, Any] | None:
    """The XML image whose `name` equals `filename`'s basename, or None."""
    catalog = load_catalog(ANNOTATIONS_PATH)
    if not catalog:
        return None
    return catalog.get(file_basename(filename))


def load_catalog(path: Path) -> dict[str, dict[str, Any]] | None:
    key = str(path)
    if key in _catalogs:
        return _catalogs[key]
    try:
        parsed = parse_annotations(path.read_bytes())
    except Exception:
        logger.exception("Could not load CVAT annotations from %s", path)
        parsed = None
    _catalogs[key] = parsed
    return parsed


def parse_annotations(source: str | bytes) -> dict[str, dict[str, Any]]:
    root = fromstring(source)
    images: dict[str, dict[str, Any]] = {}
    for image in root.findall("image"):
        name = image.get("name")
        if not name:
            continue
        images[name] = {
            "image": name,
            "width": int(image.attrib["width"]),
            "height": int(image.attrib["height"]),
            "items": [_shape_item(child) for child in image if child.tag in _SHAPE_BY_TAG],
        }
    return images


def _shape_item(element: Element) -> dict[str, Any]:
    shape = _SHAPE_BY_TAG[element.tag]
    points = _rectangle_points(element) if shape == "rectangle" else _parse_points(element.attrib["points"])
    item: dict[str, Any] = {}
    if (shape_id := element.get("id")) is not None:
        item["id"] = shape_id
    item["label"] = element.attrib["label"]
    item["shape"] = shape
    item["points"] = points
    item["attributes"] = _attributes(element)
    return item


def _rectangle_points(element: Element) -> list[list[float]]:
    xtl = float(element.attrib["xtl"])
    ytl = float(element.attrib["ytl"])
    xbr = float(element.attrib["xbr"])
    ybr = float(element.attrib["ybr"])
    return [[xtl, ytl], [xbr, ytl], [xbr, ybr], [xtl, ybr]]


def _parse_points(raw: str) -> list[list[float]]:
    points: list[list[float]] = []
    for pair in raw.split(";"):
        pair = pair.strip()
        if not pair:
            continue
        x_str, y_str = (part.strip() for part in pair.split(","))
        points.append([float(x_str), float(y_str)])
    return points


def _attributes(element: Element) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for node in element.findall("attribute"):
        name = node.get("name")
        if name is None:
            continue
        attributes[name] = node.text if node.text is not None else ""
    return attributes
