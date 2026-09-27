"""
Unit tests for grid georeferencing and CVAT XML serialization.
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import xml.etree.ElementTree as ET

from src.spatial.grid import (
    parse_tile_indices,
    tile_upper_left,
    pixel_to_map,
    map_to_pixel,
    map_to_tile_indices,
    START_POINT,
    START_TILE,
)
from src.export.cvat_writer import (
    CVATWriter,
    TileAnnotations,
    VineRow,
    InterRowArea,
    VineyardCanopy,
    WasteBox,
)


def test_start_point_grid_mapping():
    """Verify start point lands in siret3_r018_c010.tif."""
    easting, northing = START_POINT
    r, c = map_to_tile_indices(easting, northing)
    assert (r, c) == (18, 10), f"Expected (18, 10), got ({r}, {c})"
    assert parse_tile_indices(START_TILE) == (18, 10)

    # Check pixel position in tile r018_c010
    px, py = map_to_pixel(18, 10, easting, northing)
    # Stated in KB: about 28 px from west edge, ~2002 px from north edge
    assert 20 <= px <= 35, f"Unexpected px {px}"
    assert 1990 <= py <= 2010, f"Unexpected py {py}"
    print(f"Start point verified at tile ({r}, {c}), pixel ({px:.1f}, {py:.1f})")


def test_tile_ul_coordinates():
    """Verify tile upper-left coordinates from knowledge base."""
    # r021_c012: X_ul = 628992.0 + 12 * 51.2 = 629606.4, Y_ul = 5221222.4 - 21 * 51.2 = 5220147.2
    x_ul, y_ul = tile_upper_left(21, 12)
    assert x_ul == 629606.4
    assert y_ul == 5220147.2
    print(f"Tile r021_c012 UL verified at ({x_ul}, {y_ul})")


def test_cvat_writer_serialization():
    """Verify CVATWriter produces valid XML with required labels and attributes."""
    writer = CVATWriter()
    tile = TileAnnotations(image_name="siret3_r021_c012.tif", width=2048, height=2048)
    tile.rows.append(
        VineRow(
            points=[(2048.0, 32.1), (2017.8, 0.0)],
            vineyard_id="V01",
            row_id="V01-R01",
            row_structure="regular",
        )
    )
    tile.interrows.append(
        InterRowArea(
            points=[(2048.0, 49.6), (2001.4, 0.0), (1902.3, 0.0), (2048.0, 179.8)],
            vineyard_id="V01",
            interrow_cover="bare_soil",
        )
    )
    tile.canopies.append(
        VineyardCanopy(
            points=[(2022.0, 0.0), (2019.0, 8.0), (2021.0, 19.0), (2022.0, 0.0)],
            vineyard_id="V01",
        )
    )
    tile.waste_boxes.append(
        WasteBox(
            xtl=100.0,
            ytl=150.0,
            xbr=120.0,
            ybr=170.0,
            vineyard_id="V01",
        )
    )
    writer.add_tile(tile)

    # Test canopies_only=False mode
    writer_full = CVATWriter(canopies_only=False)
    writer_full.add_tile(tile)
    xml_full = writer_full.to_xml_string()
    root_full = ET.fromstring(xml_full)
    assert root_full.find("version").text == "1.1"
    labels_full = {l.text for l in root_full.findall(".//label/name")}
    assert labels_full == {"vineyard", "waste", "row", "interrow_area"}
    assert root_full.find(".//image").find("polygon") is not None
    assert root_full.find(".//image").find("polyline") is not None

    # Test canopies_only=True mode (default)
    writer_canopy = CVATWriter(canopies_only=True)
    writer_canopy.add_tile(tile)
    xml_canopy = writer_canopy.to_xml_string()
    root_canopy = ET.fromstring(xml_canopy)
    labels_canopy = {l.text for l in root_canopy.findall(".//label/name")}
    assert labels_canopy == {"vineyard"}
    assert root_canopy.find(".//image").find("polygon") is not None
    assert root_canopy.find(".//image").find("polyline") is None
    assert root_canopy.find(".//image").find("box") is None

    print("CVAT XML generation and validation verified successfully for both modes.")


import unittest


class GridAndCvatTestCase(unittest.TestCase):
    def test_start_point_grid_mapping(self):
        test_start_point_grid_mapping()

    def test_tile_ul_coordinates(self):
        test_tile_ul_coordinates()

    def test_cvat_writer_serialization(self):
        test_cvat_writer_serialization()


if __name__ == "__main__":
    unittest.main()


