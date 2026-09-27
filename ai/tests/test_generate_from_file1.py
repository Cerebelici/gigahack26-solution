"""
Unit tests for generate_from_file1.py mapping, block assignment, and CVAT XML generation.
"""

import sys
import unittest
from pathlib import Path
import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.generate_from_file1 import (
    load_file1_mapping,
    find_all_challenge_tiles,
    compute_block_reference_geometry,
    assign_canopy_block,
)


class GenerateFromFile1TestCase(unittest.TestCase):
    def setUp(self):
        self.file1_path = ROOT_DIR / "file1.txt"
        self.tiles_dir = ROOT_DIR / "assets/01_tiles"

    def test_load_file1_mapping(self):
        """Verify file1.txt contains 198 lines, 142 unique tiles, and 33 blocks."""
        tile_to_blocks, block_to_tiles = load_file1_mapping(str(self.file1_path))
        self.assertEqual(len(tile_to_blocks), 142)
        self.assertEqual(len(block_to_tiles), 33)
        self.assertIn("V01", block_to_tiles)
        self.assertIn("V34", block_to_tiles)
        self.assertNotIn("V07", block_to_tiles)  # V07 does not exist in challenge

        # Check multi-block tile
        self.assertIn("siret3_r006_c004.tif", tile_to_blocks)
        self.assertIn("V01", tile_to_blocks["siret3_r006_c004.tif"])
        self.assertIn("V02", tile_to_blocks["siret3_r006_c004.tif"])

    def test_find_all_challenge_tiles(self):
        """Verify all 311 challenge tiles are discovered across part folders."""
        tile_paths, tile_part_map = find_all_challenge_tiles(str(self.tiles_dir))
        self.assertEqual(len(tile_paths), 311)
        self.assertEqual(len(tile_part_map), 311)

        # Check that parts 1 to 5 are present
        parts = {p for p in tile_part_map.values()}
        expected_parts = {
            "siret3_challenge_tiles_part1of5",
            "siret3_challenge_tiles_part2of5",
            "siret3_challenge_tiles_part3of5",
            "siret3_challenge_tiles_part4of5",
            "siret3_challenge_tiles_part5of5",
        }
        self.assertTrue(expected_parts.issubset(parts))

    def test_compute_block_reference_geometry(self):
        """Verify block reference centroids and shared tile direction vectors."""
        tile_to_blocks, block_to_tiles = load_file1_mapping(str(self.file1_path))
        centroids, shared_dirs = compute_block_reference_geometry(block_to_tiles)

        self.assertEqual(len(centroids), 33)
        for vid, c in centroids.items():
            self.assertEqual(len(c), 2)
            self.assertGreater(c[0], 628000.0)  # EPSG:32635 Easting
            self.assertGreater(c[1], 5219000.0)  # EPSG:32635 Northing

        # V01 is north of V02 -> Northing of V01 > Northing of V02
        self.assertGreater(centroids["V01"][1], centroids["V02"][1])

    def test_assign_canopy_block(self):
        """Verify canopy assignment in shared tiles based on directional projection."""
        tile_to_blocks, block_to_tiles = load_file1_mapping(str(self.file1_path))
        centroids, shared_dirs = compute_block_reference_geometry(block_to_tiles)

        # Tile r007_c004 is shared between V01 (north) and V02 (south)
        candidates = ["V01", "V02"]
        r, c = 7, 4

        # Canopy near the top (y=200 px -> north) should be assigned to V01
        assigned_north = assign_canopy_block(
            r=r,
            c=c,
            px=1000.0,
            py=200.0,
            tile_name="siret3_r007_c004.tif",
            candidate_blocks=candidates,
            block_centroids=centroids,
            shared_tile_directions=shared_dirs,
        )
        self.assertEqual(assigned_north, "V01")

        # Canopy near the bottom (y=1900 px -> south) should be assigned to V02
        assigned_south = assign_canopy_block(
            r=r,
            c=c,
            px=1000.0,
            py=1900.0,
            tile_name="siret3_r007_c004.tif",
            candidate_blocks=candidates,
            block_centroids=centroids,
            shared_tile_directions=shared_dirs,
        )
        self.assertEqual(assigned_south, "V02")


if __name__ == "__main__":
    unittest.main()
