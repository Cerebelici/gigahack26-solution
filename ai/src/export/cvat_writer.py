"""
CVAT for Images 1.1 XML Writer and Data Classes.
Produces annotations.xml conforming strictly to the Marcaj competition standard.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import xml.etree.ElementTree as ET


@dataclass
class VineyardCanopy:
    points: List[Tuple[float, float]]  # List of (x, y) coordinates
    vineyard_id: str = "V01"


@dataclass
class WasteBox:
    xtl: float
    ytl: float
    xbr: float
    ybr: float
    vineyard_id: str = ""  # If >10m from vineyard, leave empty


@dataclass
class VineRow:
    points: List[Tuple[float, float]]  # Polyline vertices (x, y)
    vineyard_id: str = "V01"
    row_id: str = "V01-R01"
    row_structure: str = "regular"  # regular | disrupted | unassessable

    def __post_init__(self):
        valid = {"regular", "disrupted", "unassessable"}
        if self.row_structure not in valid:
            raise ValueError(f"Invalid row_structure '{self.row_structure}'. Allowed: {valid}")


@dataclass
class InterRowArea:
    points: List[Tuple[float, float]]  # Polygon vertices (x, y)
    vineyard_id: str = "V01"
    interrow_cover: str = "bare_soil"  # bare_soil | vegetation | mixed | unassessable

    def __post_init__(self):
        valid = {"bare_soil", "vegetation", "mixed", "unassessable"}
        if self.interrow_cover not in valid:
            raise ValueError(f"Invalid interrow_cover '{self.interrow_cover}'. Allowed: {valid}")


@dataclass
class TileAnnotations:
    image_name: str
    width: int = 2048
    height: int = 2048
    image_id: int = 0
    rows: List[VineRow] = field(default_factory=list)
    interrows: List[InterRowArea] = field(default_factory=list)
    canopies: List[VineyardCanopy] = field(default_factory=list)
    waste_boxes: List[WasteBox] = field(default_factory=list)


def format_points(points: List[Tuple[float, float]]) -> str:
    """Format coordinates as x1,y1;x2,y2;... with 1 decimal place."""
    return ";".join(f"{float(x):.1f},{float(y):.1f}" for x, y in points)


class CVATWriter:
    """Generates CVAT for images 1.1 annotations.xml file."""

    TASK_NAME = "Vineyard AI Field Challenge"

    def __init__(self, task_name: Optional[str] = None, canopies_only: bool = True):
        self.task_name = task_name or self.TASK_NAME
        self.canopies_only = canopies_only
        self.tiles: List[TileAnnotations] = []

    def add_tile(self, tile: TileAnnotations):
        tile.image_id = len(self.tiles)
        self.tiles.append(tile)

    def to_xml_string(self) -> str:
        root = ET.Element("annotations")
        version = ET.SubElement(root, "version")
        version.text = "1.1"

        # Metadata & Label schema
        meta = ET.SubElement(root, "meta")
        task = ET.SubElement(meta, "task")
        name = ET.SubElement(task, "name")
        name.text = self.task_name
        labels = ET.SubElement(task, "labels")

        # 1. vineyard label (always present)
        lbl_v = ET.SubElement(labels, "label")
        ET.SubElement(lbl_v, "name").text = "vineyard"
        ET.SubElement(lbl_v, "type").text = "polygon"
        attr_v = ET.SubElement(lbl_v, "attributes")
        a = ET.SubElement(attr_v, "attribute")
        ET.SubElement(a, "name").text = "vineyard_id"
        ET.SubElement(a, "mutable").text = "False"
        ET.SubElement(a, "input_type").text = "text"
        ET.SubElement(a, "default_value").text = ""
        ET.SubElement(a, "values").text = ""

        if not self.canopies_only:
            # 2. waste label
            lbl_w = ET.SubElement(labels, "label")
            ET.SubElement(lbl_w, "name").text = "waste"
            ET.SubElement(lbl_w, "type").text = "rectangle"
            attr_w = ET.SubElement(lbl_w, "attributes")
            a = ET.SubElement(attr_w, "attribute")
            ET.SubElement(a, "name").text = "vineyard_id"
            ET.SubElement(a, "mutable").text = "False"
            ET.SubElement(a, "input_type").text = "text"
            ET.SubElement(a, "default_value").text = ""
            ET.SubElement(a, "values").text = ""

            # 3. row label
            lbl_r = ET.SubElement(labels, "label")
            ET.SubElement(lbl_r, "name").text = "row"
            ET.SubElement(lbl_r, "type").text = "polyline"
            attr_r = ET.SubElement(lbl_r, "attributes")
            for attr_name in ["vineyard_id", "row_id"]:
                a = ET.SubElement(attr_r, "attribute")
                ET.SubElement(a, "name").text = attr_name
                ET.SubElement(a, "mutable").text = "False"
                ET.SubElement(a, "input_type").text = "text"
                ET.SubElement(a, "default_value").text = ""
                ET.SubElement(a, "values").text = ""
            a = ET.SubElement(attr_r, "attribute")
            ET.SubElement(a, "name").text = "row_structure"
            ET.SubElement(a, "mutable").text = "False"
            ET.SubElement(a, "input_type").text = "select"
            ET.SubElement(a, "default_value").text = "regular"
            ET.SubElement(a, "values").text = "regular\ndisrupted\nunassessable"

            # 4. interrow_area label
            lbl_i = ET.SubElement(labels, "label")
            ET.SubElement(lbl_i, "name").text = "interrow_area"
            ET.SubElement(lbl_i, "type").text = "polygon"
            attr_i = ET.SubElement(lbl_i, "attributes")
            a = ET.SubElement(attr_i, "attribute")
            ET.SubElement(a, "name").text = "vineyard_id"
            ET.SubElement(a, "mutable").text = "False"
            ET.SubElement(a, "input_type").text = "text"
            ET.SubElement(a, "default_value").text = ""
            ET.SubElement(a, "values").text = ""
            a = ET.SubElement(attr_i, "attribute")
            ET.SubElement(a, "name").text = "interrow_cover"
            ET.SubElement(a, "mutable").text = "False"
            ET.SubElement(a, "input_type").text = "select"
            ET.SubElement(a, "default_value").text = "bare_soil"
            ET.SubElement(a, "values").text = "bare_soil\nvegetation\nmixed\nunassessable"

        # Images & annotations
        for tile in self.tiles:
            img_el = ET.SubElement(
                root,
                "image",
                id=str(tile.image_id),
                name=tile.image_name,
                width=str(tile.width),
                height=str(tile.height),
            )

            # Canopies (always written)
            for c in tile.canopies:
                pg = ET.SubElement(
                    img_el,
                    "polygon",
                    label="vineyard",
                    source="manual",
                    occluded="0",
                    points=format_points(c.points),
                    z_order="0",
                )
                a1 = ET.SubElement(pg, "attribute", name="vineyard_id")
                a1.text = str(c.vineyard_id)

            if not self.canopies_only:
                # Rows
                for row in tile.rows:
                    pl = ET.SubElement(
                        img_el,
                        "polyline",
                        label="row",
                        source="manual",
                        occluded="0",
                        points=format_points(row.points),
                        z_order="0",
                    )
                    a1 = ET.SubElement(pl, "attribute", name="vineyard_id")
                    a1.text = str(row.vineyard_id)
                    a2 = ET.SubElement(pl, "attribute", name="row_id")
                    a2.text = str(row.row_id)
                    a3 = ET.SubElement(pl, "attribute", name="row_structure")
                    a3.text = str(row.row_structure)

                # Inter-rows
                for ir in tile.interrows:
                    pg = ET.SubElement(
                        img_el,
                        "polygon",
                        label="interrow_area",
                        source="manual",
                        occluded="0",
                        points=format_points(ir.points),
                        z_order="0",
                    )
                    a1 = ET.SubElement(pg, "attribute", name="vineyard_id")
                    a1.text = str(ir.vineyard_id)
                    a2 = ET.SubElement(pg, "attribute", name="interrow_cover")
                    a2.text = str(ir.interrow_cover)

                # Waste boxes
                for w in tile.waste_boxes:
                    bx = ET.SubElement(
                        img_el,
                        "box",
                        label="waste",
                        source="manual",
                        occluded="0",
                        xtl=f"{w.xtl:.1f}",
                        ytl=f"{w.ytl:.1f}",
                        xbr=f"{w.xbr:.1f}",
                        ybr=f"{w.ybr:.1f}",
                        z_order="0",
                    )
                    a1 = ET.SubElement(bx, "attribute", name="vineyard_id")
                    a1.text = str(w.vineyard_id)

        xml_bytes = ET.tostring(root, encoding="utf-8")
        return '<?xml version="1.0" encoding="utf-8"?>\n' + xml_bytes.decode("utf-8")

    def write(self, output_path: str):
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(self.to_xml_string())
