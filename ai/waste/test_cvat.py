"""CVAT waste XML, without the model."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from waste.cvat import annotations_xml


class CvatTest(unittest.TestCase):
    def test_box_uses_pixel_corners_and_empty_block_id(self):
        xml = annotations_xml(
            [
                {
                    "image": "siret3_r005_c004.tif",
                    "width": 2048,
                    "height": 2048,
                    "boxes": [
                        {
                            "xtl": 10.0,
                            "ytl": 20.5,
                            "xbr": 30.0,
                            "ybr": 40.25,
                        }
                    ],
                }
            ]
        )
        self.assertIn("<version>1.1</version>", xml)
        self.assertIn('<type>detection</type>', xml)
        self.assertNotIn("<name>vineyard</name>", xml)
        self.assertNotIn("<name>row</name>", xml)
        self.assertIn('name="siret3_r005_c004.tif"', xml)
        self.assertIn('xtl="10.00" ytl="20.50" xbr="30.00" ybr="40.25"', xml)
        self.assertIn('<attribute name="vineyard_id"></attribute>', xml)

    def test_tile_with_no_waste_is_omitted(self):
        xml = annotations_xml(
            [
                {"image": "siret3_r006_c002.tif", "width": 2048, "height": 2048, "boxes": []},
                {
                    "image": "siret3_r022_c015.tif",
                    "width": 2048,
                    "height": 2048,
                    "boxes": [{"xtl": 1.0, "ytl": 2.0, "xbr": 3.0, "ybr": 4.0}],
                },
            ]
        )
        self.assertNotIn('name="siret3_r006_c002.tif"', xml)
        self.assertIn('id="0" name="siret3_r022_c015.tif"', xml)


if __name__ == "__main__":
    unittest.main()
