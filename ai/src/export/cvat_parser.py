"""
CVAT for Images 1.1 XML Parser.
Parses existing annotations.xml files into Python TileAnnotations objects.
"""

from pathlib import Path
from typing import List, Dict, Any, Tuple
import xml.etree.ElementTree as ET

from src.export.cvat_writer import (
    TileAnnotations,
    VineRow,
    InterRowArea,
    VineyardCanopy,
    WasteBox,
)


def parse_points(points_str: str) -> List[Tuple[float, float]]:
    """Parse 'x1,y1;x2,y2;...' into list of (x, y) tuples."""
    pts = []
    for pair in points_str.strip().split(";"):
        if pair.strip():
            x, y = pair.split(",")
            pts.append((float(x), float(y)))
    return pts


def parse_cvat_xml(xml_path: str) -> List[TileAnnotations]:
    """Parse CVAT 1.1 annotations.xml and return list of TileAnnotations."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    tiles: List[TileAnnotations] = []

    for img_el in root.findall("image"):
        tile = TileAnnotations(
            image_name=img_el.attrib["name"],
            width=int(img_el.attrib.get("width", 2048)),
            height=int(img_el.attrib.get("height", 2048)),
            image_id=int(img_el.attrib.get("id", 0)),
        )

        # Polylines (rows)
        for pl in img_el.findall("polyline"):
            label = pl.attrib.get("label")
            if label == "row":
                points = parse_points(pl.attrib["points"])
                attrs = {a.attrib["name"]: a.text for a in pl.findall("attribute")}
                tile.rows.append(
                    VineRow(
                        points=points,
                        vineyard_id=attrs.get("vineyard_id", "V01"),
                        row_id=attrs.get("row_id", "V01-R01"),
                        row_structure=attrs.get("row_structure", "regular"),
                    )
                )

        # Polygons (interrow_area and vineyard)
        for pg in img_el.findall("polygon"):
            label = pg.attrib.get("label")
            points = parse_points(pg.attrib["points"])
            attrs = {a.attrib["name"]: a.text for a in pg.findall("attribute")}

            if label == "interrow_area":
                tile.interrows.append(
                    InterRowArea(
                        points=points,
                        vineyard_id=attrs.get("vineyard_id", "V01"),
                        interrow_cover=attrs.get("interrow_cover", "bare_soil"),
                    )
                )
            elif label == "vineyard":
                tile.canopies.append(
                    VineyardCanopy(
                        points=points,
                        vineyard_id=attrs.get("vineyard_id", "V01"),
                    )
                )

        # Boxes (waste)
        for bx in img_el.findall("box"):
            label = bx.attrib.get("label")
            if label == "waste":
                attrs = {a.attrib["name"]: a.text for a in bx.findall("attribute")}
                tile.waste_boxes.append(
                    WasteBox(
                        xtl=float(bx.attrib["xtl"]),
                        ytl=float(bx.attrib["ytl"]),
                        xbr=float(bx.attrib["xbr"]),
                        ybr=float(bx.attrib["ybr"]),
                        vineyard_id=attrs.get("vineyard_id", ""),
                    )
                )

        tiles.append(tile)

    return tiles

