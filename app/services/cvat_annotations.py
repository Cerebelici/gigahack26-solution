"""Example-tile annotations from the CVAT 1.1 file at the repository root.

Pixel coordinates follow CVAT: origin at the top-left, x to the right, y downward.
If the file is missing or cannot be parsed, lookups return nothing so a valid TIFF
upload can still be streamed.
"""

import logging
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, fromstring

logger = logging.getLogger(__name__)

ANNOTATIONS_PATH = Path(__file__).resolve().parents[2] / "annotations.xml"

_SHAPE_BY_TAG = {
    "polygon": "polygon",
    "polyline": "polyline",
    "box": "rectangle",
}

_catalogs: dict[str, dict[str, dict[str, Any]] | None] = {}


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
