"""
Unit tests for row extraction and quadrilateral interrow area derivation.
"""

import sys
import unittest
from pathlib import Path
import numpy as np
from shapely.geometry import Polygon

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.spatial.row_extractor import (
    estimate_row_angle,
    clip_line_to_tile,
    extract_rows_from_canopies,
    partition_canopies_by_orientation,
)
from src.spatial.interrow import (
    derive_interrow_quadrilaterals,
    classify_interrow_cover,
)
from src.pipeline import nms_canopy_polygons
from src.spatial.row_stitcher import GlobalRowStitcher, LocalRowSegment
from src.export.cvat_writer import CVATWriter, TileAnnotations


class RowAndInterrowTestCase(unittest.TestCase):
    def test_line_clipping_to_tile(self):
        """Test straight line clipping to [0, 2048] x [0, 2048] box."""
        rad = np.radians(45.0)
        norm_vec = np.array([-np.sin(rad), np.cos(rad)])
        prim_vec = np.array([np.cos(rad), np.sin(rad)])

        # Line passing through (1024, 1024): c = -1024*sin(45) + 1024*cos(45) = 0
        pts = clip_line_to_tile(c_val=0.0, normal_dir=norm_vec, primary_dir=prim_vec)
        self.assertEqual(len(pts), 2)
        self.assertEqual(pts[0], (0.0, 0.0))
        self.assertEqual(pts[1], (2048.0, 2048.0))

    def test_row_extraction_and_disruption(self):
        """Test clustering and gap detection (>= 5m / 200px gap triggers 'disrupted')."""
        # Row 1: Regular (spacing 50px = 1.25m)
        r1_pts = [(100.0, y) for y in range(200, 1000, 50)]
        # Row 2: Disrupted (contains a 250px gap from y=400 to y=650)
        r2_pts = [(200.0, y) for y in [200, 250, 300, 350, 400, 650, 700, 750, 800]]

        all_cents = r1_pts + r2_pts
        rows, targets, meta = extract_rows_from_canopies(all_cents, min_vines_per_row=3)

        self.assertEqual(len(rows), 2)
        # Check that one row is regular and one is disrupted
        structures = {r.row_structure for r in rows}
        self.assertIn("regular", structures)
        self.assertIn("disrupted", structures)
        self.assertGreaterEqual(len(targets), 1)

    def test_row_gap_continuity_single_polyline(self):
        """Test that a large gap (>= 5m / 200px) does not split the row into multiple polylines or row_ids."""
        # Row with 500px gap (12.5 meters) between y=500 and y=1000
        row_pts = [(300.0, float(y)) for y in [200, 250, 300, 350, 400, 450, 500, 1000, 1050, 1100, 1150, 1200]]
        rows, targets, meta = extract_rows_from_canopies(row_pts, min_vines_per_row=2)

        # Must produce exactly ONE single polyline, NOT split into two
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.row_structure, "disrupted")
        self.assertEqual(len(row.points), 2)

        # Polyline must span through the gap from first vine to last vine
        y_pts = [p[1] for p in row.points]
        self.assertLessEqual(min(y_pts), 200.0)
        self.assertGreaterEqual(max(y_pts), 1200.0)

        # Inspection target must be recorded inside the gap
        self.assertGreaterEqual(len(targets), 1)
        self.assertAlmostEqual(targets[0][0], 300.0, delta=5.0)
        self.assertAlmostEqual(targets[0][1], 750.0, delta=10.0)

    def test_collinear_cluster_unification(self):
        """Test that collinear canopy clusters along the same physical row are unified into one row."""
        # Two clusters separated by 400px gap, with slight normal jitter (dx=10px, well within 35px tolerance)
        cluster_a = [(500.0, float(y)) for y in [100, 150, 200, 250]]
        cluster_b = [(510.0, float(y)) for y in [650, 700, 750, 800]]

        rows, targets, meta = extract_rows_from_canopies(cluster_a + cluster_b, min_vines_per_row=2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].row_structure, "disrupted")
        y_pts = [p[1] for p in rows[0].points]
        self.assertLessEqual(min(y_pts), 100.0)
        self.assertGreaterEqual(max(y_pts), 800.0)

    def test_interrow_quadrilaterals(self):
        """Test that interrow areas between adjacent rows form clean straight quadrilaterals."""
        # 3 parallel vertical rows at x=200, x=350, x=500
        cents_r1 = [(200.0, y) for y in range(100, 1900, 60)]
        cents_r2 = [(350.0, y) for y in range(100, 1900, 60)]
        cents_r3 = [(500.0, y) for y in range(100, 1900, 60)]

        rows, targets, meta = extract_rows_from_canopies(cents_r1 + cents_r2 + cents_r3)
        self.assertEqual(len(rows), 3)

        margin_px = 12.0
        interrows = derive_interrow_quadrilaterals(
            rows_metadata=meta["rows_data"],
            normal_dir=meta["normal_dir"],
            primary_dir=meta["primary_dir"],
            vineyard_id="V01",
            margin_px=margin_px,
        )

        # 3 rows yield exactly 2 interrow corridors
        self.assertEqual(len(interrows), 2)

        for ir in interrows:
            self.assertEqual(ir.vineyard_id, "V01")
            self.assertIn(ir.interrow_cover, {"bare_soil", "vegetation", "mixed", "unassessable"})

            # Must be a quadrilateral (4 vertices)
            self.assertEqual(len(ir.points), 4)

            # Must be a strictly valid simple polygon
            poly = Polygon(ir.points)
            self.assertTrue(poly.is_valid)
            self.assertTrue(poly.exterior.is_simple)
            self.assertGreater(poly.area, 1000.0)

    def test_interrow_cover_classification(self):
        """Test Excess Green Index ground cover classifier."""
        # Clean green image (vegetation)
        green_img = np.zeros((100, 100, 3), dtype=np.uint8)
        green_img[:, :, 1] = 180  # high green
        pts = [(10.0, 10.0), (90.0, 10.0), (90.0, 90.0), (10.0, 90.0)]
        self.assertEqual(classify_interrow_cover(pts, green_img), "vegetation")

        # Clean brown/soil image (bare_soil: high red and blue, low green)
        soil_img = np.zeros((100, 100, 3), dtype=np.uint8)
        soil_img[:, :, 0] = 160  # Red
        soil_img[:, :, 1] = 100  # Green
        soil_img[:, :, 2] = 70   # Blue
        self.assertEqual(classify_interrow_cover(pts, soil_img), "bare_soil")

    def test_row_bounded_to_planting_extent(self):
        """Test that rows do not extend to 0 or 2048 when vines end in tile interior."""
        # Vines from y=500 to y=1200 at x=800
        cents = [(800.0, float(y)) for y in range(500, 1201, 50)]
        rows, targets, meta = extract_rows_from_canopies(cents, headland_margin_px=60.0)
        self.assertEqual(len(rows), 1)

        row = rows[0]
        y_pts = [p[1] for p in row.points]
        min_y, max_y = min(y_pts), max(y_pts)

        # Must not extend all the way to 0.0 or 2048.0
        self.assertGreater(min_y, 400.0)
        self.assertLess(max_y, 1300.0)
        # Must extend ~60px past outermost vines (500-60=440, 1200+60=1260)
        self.assertAlmostEqual(min_y, 440.0, delta=5.0)
        self.assertAlmostEqual(max_y, 1260.0, delta=5.0)

    def test_row_black_nodata_exclusion(self):
        """Test that rows terminate before entering black/nodata borders."""
        # Create 2048x2048 image with black border from y=0 to y=400
        mock_img = np.ones((2048, 2048, 3), dtype=np.uint8) * 150
        mock_img[:400, :] = 0  # black nodata

        # Vines start at y=420 (close to black border) and end at y=1500
        cents = [(500.0, float(y)) for y in range(420, 1501, 50)]
        rows, targets, meta = extract_rows_from_canopies(
            cents, image_rgb=mock_img, headland_margin_px=60.0
        )
        self.assertEqual(len(rows), 1)

        row = rows[0]
        y_pts = [p[1] for p in row.points]
        min_y = min(y_pts)

        # 420 - 60 = 360 would be in black area (< 400), but row must stop >= 400!
        self.assertGreaterEqual(min_y, 399.0)

    def test_interrow_stops_at_shorter_row(self):
        """Test that interrow quadrilateral corridor stops where the shorter row ends."""
        # Row 1: spans y=200 to y=1600 at x=300
        cents_r1 = [(300.0, float(y)) for y in range(200, 1601, 60)]
        # Row 2: shorter, spans y=500 to y=1100 at x=450
        cents_r2 = [(450.0, float(y)) for y in range(500, 1101, 60)]

        rows, targets, meta = extract_rows_from_canopies(cents_r1 + cents_r2, headland_margin_px=60.0)
        self.assertEqual(len(rows), 2)

        interrows = derive_interrow_quadrilaterals(
            rows_metadata=meta["rows_data"],
            normal_dir=meta["normal_dir"],
            primary_dir=meta["primary_dir"],
            vineyard_id="V01",
        )
        self.assertEqual(len(interrows), 1)

        ir = interrows[0]
        self.assertEqual(len(ir.points), 4)

        poly = Polygon(ir.points)
        self.assertTrue(poly.is_valid)

        # Corridor bounds: Row 2 spans 500-60=440 to 1100+60=1160.
        # Short sides must stop where the shorter row ends (around y=440 and y=1160, NOT y=140 or y=1660)
        y_pts = [p[1] for p in ir.points]
        min_ir_y = min(y_pts)
        max_ir_y = max(y_pts)
        self.assertGreater(min_ir_y, 400.0)
        self.assertLess(max_ir_y, 1200.0)

    def test_canopy_nms_deduplication(self):
        """Test that overlapping polygons on the same plant are deduplicated to the best single polygon."""
        # Plant A: two duplicate predictions with IoU ~0.7
        poly_a1 = [(100.0, 100.0), (140.0, 100.0), (140.0, 140.0), (100.0, 140.0)]
        poly_a2 = [(105.0, 105.0), (145.0, 105.0), (145.0, 145.0), (105.0, 145.0)]

        # Plant B: distinct vine 80px away along the row
        poly_b = [(100.0, 220.0), (140.0, 220.0), (140.0, 260.0), (100.0, 260.0)]

        candidates = [
            (0.55, poly_a2),  # lower confidence duplicate
            (0.88, poly_a1),  # higher confidence duplicate
            (0.75, poly_b),   # distinct plant
        ]

        deduped = nms_canopy_polygons(candidates)

        # 3 raw candidates deduplicate down to exactly 2 distinct canopies
        self.assertEqual(len(deduped), 2)

        # Higher confidence poly_a1 should be retained, poly_a2 suppressed
        self.assertEqual(deduped[0], poly_a1)
        self.assertEqual(deduped[1], poly_b)

    def test_interrow_black_nodata_exclusion(self):
        """Test that interrow corridors stop before entering black/nodata borders and remain 4-point quadrilaterals."""
        # Create 2048x2048 image with black border from y=0 to y=400
        mock_img = np.ones((2048, 2048, 3), dtype=np.uint8) * 150
        mock_img[:400, :] = 0  # black nodata

        cents_r1 = [(400.0, float(y)) for y in range(420, 1501, 60)]
        cents_r2 = [(550.0, float(y)) for y in range(420, 1501, 60)]

        rows, targets, meta = extract_rows_from_canopies(
            cents_r1 + cents_r2, image_rgb=mock_img, headland_margin_px=60.0
        )
        self.assertEqual(len(rows), 2)

        interrows = derive_interrow_quadrilaterals(
            rows_metadata=meta["rows_data"],
            normal_dir=meta["normal_dir"],
            primary_dir=meta["primary_dir"],
            vineyard_id="V01",
            image_rgb=mock_img,
        )
        self.assertEqual(len(interrows), 1)
        ir = interrows[0]
        self.assertEqual(len(ir.points), 4)

        poly = Polygon(ir.points)
        self.assertTrue(poly.is_valid)
        self.assertTrue(poly.exterior.is_simple)

        # Short side at top must stop >= 399.0 (outside black border)
        for pt in ir.points:
            self.assertGreaterEqual(pt[1], 399.0)

    def test_interrow_tile_boundary_clamping_exact_quad(self):
        """Test that corridors reaching tile boundaries remain strict 4-point quadrilaterals."""
        # Diagonal rows that reach the left border x=0 at an angle
        # Direction ~ 25 degrees
        rad = np.radians(25.0)
        norm_vec = np.array([-np.sin(rad), np.cos(rad)])
        prim_vec = np.array([np.cos(rad), np.sin(rad)])

        # Construct 2 rows where one vine is very close to x=0
        row1_meta = {
            "c_val": 500.0,
            "row_id": "V01-R01",
            "row_structure": "regular",
            "points": [(0.0, 550.0), (1500.0, 1250.0)],
            "s_min": 230.0,
            "s_max": 1800.0,
        }
        row2_meta = {
            "c_val": 800.0,
            "row_id": "V01-R02",
            "row_structure": "regular",
            "points": [(0.0, 880.0), (1500.0, 1580.0)],
            "s_min": 320.0,
            "s_max": 1800.0,
        }

        interrows = derive_interrow_quadrilaterals(
            rows_metadata=[row1_meta, row2_meta],
            normal_dir=norm_vec,
            primary_dir=prim_vec,
            vineyard_id="V01",
        )
        self.assertEqual(len(interrows), 1)
        ir = interrows[0]
        self.assertEqual(len(ir.points), 4)
        for pt in ir.points:
            self.assertGreaterEqual(pt[0], 0.0)
            self.assertLessEqual(pt[0], 2048.0)
            self.assertGreaterEqual(pt[1], 0.0)
            self.assertLessEqual(pt[1], 2048.0)
        poly = Polygon(ir.points)
        self.assertTrue(poly.is_valid)

    def test_row_stitcher_same_tile_unification(self):
        """Test that GlobalRowStitcher unifies multiple collinear segments on the same tile into one segment."""
        stitcher = GlobalRowStitcher(offset_tolerance_m=0.40)
        # Two segments on the same tile (siret3_r006_c004.tif) that are collinear
        # Easting/Northing offsets are collinear (< 0.40m)
        seg1 = LocalRowSegment(
            tile_name="siret3_r006_c004.tif",
            local_points=[(100.0, 200.0), (100.0, 600.0)],
            global_points=[(629100.0, 5220200.0), (629100.0, 5220600.0)],
            block_id="V01",
            row_structure="regular",
        )
        seg2 = LocalRowSegment(
            tile_name="siret3_r006_c004.tif",
            local_points=[(100.0, 900.0), (100.0, 1500.0)],
            global_points=[(629100.0, 5220900.0), (629100.0, 5221500.0)],
            block_id="V01",
            row_structure="regular",
        )

        unified = stitcher.stitch_block_rows("V01", [seg1, seg2])
        # Two segments on the same tile must be unified into exactly ONE segment (Rule 3)
        self.assertEqual(len(unified), 1)
        self.assertEqual(unified[0].assigned_row_id, "V01-R01")
        # Gap between y=600 and y=900 is 300px (7.5m >= 5m) -> row_structure must be disrupted
        self.assertEqual(unified[0].row_structure, "disrupted")
        # Points must span from min to max
        y_pts = [p[1] for p in unified[0].local_points]
        self.assertEqual(min(y_pts), 200.0)
        self.assertEqual(max(y_pts), 1500.0)

    def test_parallel_rows_not_merged_by_collinear_unification(self):
        """Test that parallel adjacent rows overlapping along row axis are NOT merged into a single row."""
        # 3 parallel rows at x=100, x=130, x=160 (30px apart, < 35px threshold, but overlapping in y)
        pts1 = [(100.0, float(y)) for y in range(100, 600, 50)]
        pts2 = [(130.0, float(y)) for y in range(100, 600, 50)]
        pts3 = [(160.0, float(y)) for y in range(100, 600, 50)]

        rows, targets, meta = extract_rows_from_canopies(pts1 + pts2 + pts3, min_vines_per_row=2)
        # Must retain 3 distinct rows, NOT merge them into 1
        self.assertEqual(len(rows), 3)

    def test_multiple_gaps_unified_into_single_polyline(self):
        """Test that a row with multiple large gaps is unified into exactly ONE polyline with single row_id."""
        # 3 segments along Row 1 with two 300px gaps: y=[100..300], y=[600..800], y=[1100..1300]
        c1 = [(200.0, float(y)) for y in range(100, 301, 50)]
        c2 = [(205.0, float(y)) for y in range(600, 801, 50)]
        c3 = [(202.0, float(y)) for y in range(1100, 1301, 50)]

        rows, targets, meta = extract_rows_from_canopies(c1 + c2 + c3, min_vines_per_row=2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].row_structure, "disrupted")
        self.assertEqual(len(rows[0].points), 2)
        y_pts = [p[1] for p in rows[0].points]
        self.assertLessEqual(min(y_pts), 100.0)
        self.assertGreaterEqual(max(y_pts), 1300.0)
        # Should record at least 2 inspection targets (one for each gap)
        self.assertGreaterEqual(len(targets), 2)

    def test_partition_canopies_by_orientation(self):
        """Test partitioning of canopies into distinct orientation groups."""
        # Group 1: 45 deg orientation
        rad1 = np.radians(45.0)
        u1 = np.array([np.cos(rad1), np.sin(rad1)])
        g1 = []
        for row_off in [-100, 0, 100]:
            n1 = np.array([-np.sin(rad1), np.cos(rad1)])
            for s in range(100, 500, 50):
                p = 500.0 + s * u1 + row_off * n1
                g1.append((float(p[0]), float(p[1])))

        # Group 2: 125 deg orientation (diff = 80 deg)
        rad2 = np.radians(125.0)
        u2 = np.array([np.cos(rad2), np.sin(rad2)])
        g2 = []
        for row_off in [-100, 0, 100]:
            n2 = np.array([-np.sin(rad2), np.cos(rad2)])
            for s in range(100, 500, 50):
                p = 1500.0 + s * u2 + row_off * n2
                g2.append((float(p[0]), float(p[1])))

        groups = partition_canopies_by_orientation(g1 + g2, min_angle_diff=25.0)
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups[0][0]), len(g1))
        self.assertEqual(len(groups[1][0]), len(g2))

    def test_cross_tile_boundary_matching_with_angle_jitter_east_west(self):
        """Test that collinear row segments crossing an East-West tile boundary receive identical row_ids despite angle jitter."""
        from src.spatial.grid import pixel_to_map
        stitcher = GlobalRowStitcher(offset_tolerance_m=0.40, boundary_tolerance_m=1.00)

        # Tile A: siret3_r006_c002.tif (West), Tile B: siret3_r006_c003.tif (East)
        # Tile A row ends near x=2048 at y=1000.
        # Tile B row starts near x=0 at y=1010 (10px = 0.25m boundary offset, well within 1.0m).
        # Introduce 2.0 degrees of angle jitter between tile A (angle ~25 deg) and tile B (angle ~23 deg).
        pts_a_local = [(200.0, 140.0), (2048.0, 1000.0)]
        pts_a_global = [pixel_to_map(6, 2, px, py) for px, py in pts_a_local]

        pts_b_local = [(0.0, 1010.0), (1800.0, 1780.0)]
        pts_b_global = [pixel_to_map(6, 3, px, py) for px, py in pts_b_local]

        seg_a = LocalRowSegment(
            tile_name="siret3_r006_c002.tif",
            local_points=pts_a_local,
            global_points=pts_a_global,
            block_id="V01",
            row_structure="regular",
        )
        seg_b = LocalRowSegment(
            tile_name="siret3_r006_c003.tif",
            local_points=pts_b_local,
            global_points=pts_b_global,
            block_id="V01",
            row_structure="regular",
        )

        stitched = stitcher.stitch_block_rows("V01", [seg_a, seg_b])
        self.assertEqual(len(stitched), 2)
        # Both segments must receive identical row_id without off-by-1 mismatch
        self.assertEqual(stitched[0].assigned_row_id, stitched[1].assigned_row_id)
        self.assertEqual(stitched[0].assigned_row_id, "V01-R01")

    def test_cross_tile_boundary_matching_with_angle_jitter_north_south(self):
        """Test that collinear row segments crossing a North-South tile boundary receive identical row_ids (reproducing V02-R100/V02-R101 case)."""
        from src.spatial.grid import pixel_to_map
        stitcher = GlobalRowStitcher(offset_tolerance_m=0.40, boundary_tolerance_m=1.00)

        # Tile A: siret3_r007_c003.tif (North), Tile B: siret3_r008_c003.tif (South)
        # Actual coordinates reproducing V02-R100 and V02-R101 boundary crossing
        # Angle ~113 deg. Tile A terminates near y=2048 (bottom). Tile B starts near y=0 (top).
        pts_a_local = [(672.5, 0.0), (1532.3, 2025.5)]
        pts_a_global = [pixel_to_map(7, 3, px, py) for px, py in pts_a_local]

        pts_b_local = [(1517.5, 0.0), (2048.0, 1249.8)]
        pts_b_global = [pixel_to_map(8, 3, px, py) for px, py in pts_b_local]

        seg_a = LocalRowSegment(
            tile_name="siret3_r007_c003.tif",
            local_points=pts_a_local,
            global_points=pts_a_global,
            block_id="V02",
            row_structure="regular",
        )
        seg_b = LocalRowSegment(
            tile_name="siret3_r008_c003.tif",
            local_points=pts_b_local,
            global_points=pts_b_global,
            block_id="V02",
            row_structure="regular",
        )

        stitched = stitcher.stitch_block_rows("V02", [seg_a, seg_b])
        self.assertEqual(len(stitched), 2)
        # Segments must be unified into the same physical row with identical row_id!
        self.assertEqual(stitched[0].assigned_row_id, stitched[1].assigned_row_id)
        self.assertEqual(stitched[0].assigned_row_id, "V02-R01")

    def test_cross_tile_chain_three_adjacent_tiles(self):
        """Test continuous physical row running across 3 consecutive tiles (A -> B -> C)."""
        from src.spatial.grid import pixel_to_map
        stitcher = GlobalRowStitcher()

        # Tiles along column: c001 -> c002 -> c003 at r009
        pts_a = [(100.0, 500.0), (2048.0, 1000.0)]
        pts_b = [(0.0, 1000.0), (2048.0, 1500.0)]
        pts_c = [(0.0, 1505.0), (1500.0, 1850.0)]

        seg_a = LocalRowSegment(
            tile_name="siret3_r009_c001.tif",
            local_points=pts_a,
            global_points=[pixel_to_map(9, 1, px, py) for px, py in pts_a],
            block_id="V03",
        )
        seg_b = LocalRowSegment(
            tile_name="siret3_r009_c002.tif",
            local_points=pts_b,
            global_points=[pixel_to_map(9, 2, px, py) for px, py in pts_b],
            block_id="V03",
        )
        seg_c = LocalRowSegment(
            tile_name="siret3_r009_c003.tif",
            local_points=pts_c,
            global_points=[pixel_to_map(9, 3, px, py) for px, py in pts_c],
            block_id="V03",
        )

        stitched = stitcher.stitch_block_rows("V03", [seg_a, seg_b, seg_c])
        self.assertEqual(len(stitched), 3)
        row_ids = [s.assigned_row_id for s in stitched]
        self.assertEqual(row_ids[0], row_ids[1])
        self.assertEqual(row_ids[1], row_ids[2])
        self.assertEqual(row_ids[0], "V03-R01")

    def test_multiple_parallel_rows_across_boundary_no_off_by_one(self):
        """Test multiple parallel rows crossing adjacent tiles without index drift or off-by-1 errors."""
        from src.spatial.grid import pixel_to_map
        stitcher = GlobalRowStitcher()

        # 3 parallel rows crossing from r006_c002 to r006_c003
        segments = []
        for i, y_cross in enumerate([400.0, 800.0, 1200.0], start=1):
            pts_a = [(200.0, y_cross - 200.0), (2048.0, y_cross)]
            pts_b = [(0.0, y_cross + 5.0), (1800.0, y_cross + 190.0)]
            segments.append(
                LocalRowSegment(
                    tile_name="siret3_r006_c002.tif",
                    local_points=pts_a,
                    global_points=[pixel_to_map(6, 2, px, py) for px, py in pts_a],
                    block_id="V01",
                )
            )
            segments.append(
                LocalRowSegment(
                    tile_name="siret3_r006_c003.tif",
                    local_points=pts_b,
                    global_points=[pixel_to_map(6, 3, px, py) for px, py in pts_b],
                    block_id="V01",
                )
            )

        stitched = stitcher.stitch_block_rows("V01", segments)
        self.assertEqual(len(stitched), 6)

        # Group by tile
        t2_segs = {s.local_points[1][1]: s.assigned_row_id for s in stitched if "c002" in s.tile_name}
        t3_segs = {s.local_points[0][1]: s.assigned_row_id for s in stitched if "c003" in s.tile_name}

        # Each pair crossing at the boundary must share the exact same row_id
        self.assertEqual(t2_segs[400.0], t3_segs[405.0])
        self.assertEqual(t2_segs[800.0], t3_segs[805.0])
        self.assertEqual(t2_segs[1200.0], t3_segs[1205.0])

        # Exactly 3 distinct row_ids must be assigned across the 6 segments
        unique_ids = set(s.assigned_row_id for s in stitched)
        self.assertEqual(len(unique_ids), 3)
        self.assertEqual(sorted(unique_ids), ["V01-R01", "V01-R02", "V01-R03"])

    def test_boundary_greedy_matching_does_not_merge_parallel_rows_on_same_tile(self):
        """Test that greedy boundary matching does not collapse two parallel rows on tile A when both are within candidate range of a single row on tile B."""
        from src.spatial.grid import pixel_to_map
        stitcher = GlobalRowStitcher()

        # seg1 on tile A: ends at x=2048, y=1000
        # seg2 on tile B: starts at x=0, y=1000 (direct continuation of seg1)
        # seg3 on tile A: ends at x=2048, y=1010 (parallel row on tile A, 0.25m away)
        s1 = LocalRowSegment("siret3_r001_c001.tif", [(1000.0, 1000.0), (2048.0, 1000.0)], [pixel_to_map(1, 1, 1000.0, 1000.0), pixel_to_map(1, 1, 2048.0, 1000.0)], "V01")
        s2 = LocalRowSegment("siret3_r001_c002.tif", [(0.0, 1000.0), (1000.0, 1000.0)], [pixel_to_map(1, 2, 0.0, 1000.0), pixel_to_map(1, 2, 1000.0, 1000.0)], "V01")
        s3 = LocalRowSegment("siret3_r001_c001.tif", [(1000.0, 1010.0), (2048.0, 1010.0)], [pixel_to_map(1, 1, 1000.0, 1010.0), pixel_to_map(1, 1, 2048.0, 1010.0)], "V01")

        # Provide in order [s1, s2, s3] where s2 appears between s1 and s3
        res = stitcher.stitch_block_rows("V01", [s1, s2, s3])
        # Two distinct rows on tile A must be preserved; s3 must NOT be merged into s1/s2!
        t1_segs = [r for r in res if r.tile_name == "siret3_r001_c001.tif"]
        self.assertEqual(len(t1_segs), 2)
        # Distinct row IDs
        self.assertNotEqual(t1_segs[0].assigned_row_id, t1_segs[1].assigned_row_id)
        # s2 (y=1000 on tile B) must share row_id with s1 (y=1000 on tile A), not s3 (y=1010)
        t1_by_y = {round(r.local_points[0][1]): r.assigned_row_id for r in t1_segs}
        t2_segs = [r for r in res if r.tile_name == "siret3_r001_c002.tif"]
        self.assertEqual(len(t2_segs), 1)
        self.assertEqual(t2_segs[0].assigned_row_id, t1_by_y[1000])
        self.assertNotEqual(t2_segs[0].assigned_row_id, t1_by_y[1010])

    def test_collinear_clustering_with_gap_across_boundary_no_boundary_contact(self):
        """Test that collinear row segments on adjacent tiles that do not reach the boundary (gap of 4m) still receive identical row_id."""
        from src.spatial.grid import pixel_to_map
        stitcher = GlobalRowStitcher()

        # Tile A: siret3_r001_c001.tif ends 2.0m (80px) before boundary (at x=1968)
        # Tile B: siret3_r001_c002.tif starts 2.0m (80px) after boundary (at x=80)
        # Total gap across boundary = 4.0m
        pts_a = [(100.0, 1000.0), (1968.0, 1000.0)]
        pts_b = [(80.0, 1005.0), (1900.0, 1005.0)]  # 0.125m normal offset, well within 0.40m tolerance
        s_a = LocalRowSegment("siret3_r001_c001.tif", pts_a, [pixel_to_map(1, 1, px, py) for px, py in pts_a], "V01")
        s_b = LocalRowSegment("siret3_r001_c002.tif", pts_b, [pixel_to_map(1, 2, px, py) for px, py in pts_b], "V01")

        res = stitcher.stitch_block_rows("V01", [s_a, s_b])
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0].assigned_row_id, res[1].assigned_row_id)
        self.assertEqual(res[0].assigned_row_id, "V01-R01")

    def test_boundary_matching_rejects_incompatible_orientation(self):
        """Test that segments meeting near a boundary but having orthogonal orientations are not merged."""
        from src.spatial.grid import pixel_to_map
        stitcher = GlobalRowStitcher()

        # Segment A along row direction (~25 deg)
        pts_a = [(1000.0, 600.0), (2048.0, 1000.0)]
        # Segment B perpendicular (~115 deg)
        pts_b = [(0.0, 1000.0), (500.0, 2048.0)]
        s_a = LocalRowSegment("siret3_r006_c002.tif", pts_a, [pixel_to_map(6, 2, px, py) for px, py in pts_a], "V01")
        s_b = LocalRowSegment("siret3_r006_c003.tif", pts_b, [pixel_to_map(6, 3, px, py) for px, py in pts_b], "V01")

        res = stitcher.stitch_block_rows("V01", [s_a, s_b])
        self.assertEqual(len(res), 2)
        self.assertNotEqual(res[0].assigned_row_id, res[1].assigned_row_id)

    def test_boundary_matching_with_normal_offset_merged_same_row_id(self):
        """
        Test that boundary crossings with normal offset 0.6m - 1.35m
        (reproducing siret3_r008_c002 vs siret3_r008_c003 V02-R100/V02-R99 case with 1.04m normal offset)
        successfully merge into the exact same row_id.
        """
        from src.spatial.grid import pixel_to_map
        stitcher = GlobalRowStitcher()

        # Real coordinates reproducing V02-R100 and V02-R99 across EW boundary:
        # Tile A (c002): ends at (2048.0, 1869.1) on East boundary
        # Tile B (c003): starts at (46.9, 1872.9) on West boundary
        # Normal distance is 1.04m, along-boundary coordinate alignment is 0.095m
        pts_a = [(1254.6, 0.0), (2048.0, 1869.1)]
        pts_b = [(46.9, 1872.9), (121.2, 2048.0)]
        seg_a = LocalRowSegment("siret3_r008_c002.tif", pts_a, [pixel_to_map(8, 2, px, py) for px, py in pts_a], "V02")
        seg_b = LocalRowSegment("siret3_r008_c003.tif", pts_b, [pixel_to_map(8, 3, px, py) for px, py in pts_b], "V02")

        res = stitcher.stitch_block_rows("V02", [seg_a, seg_b])
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0].assigned_row_id, res[1].assigned_row_id)
        self.assertEqual(res[0].assigned_row_id, "V02-R01")

        # Also test boundary crossing with 1.30m normal offset (close to 1.40m limit)
        # Shift seg_b by 1.25m normal offset (~50px)
        pts_c = [(1000.0, 0.0), (2048.0, 1000.0)]
        pts_d = [(0.0, 1050.0), (1000.0, 2048.0)]  # 50px = 1.25m offset along boundary
        seg_c = LocalRowSegment("siret3_r001_c001.tif", pts_c, [pixel_to_map(1, 1, px, py) for px, py in pts_c], "V01")
        seg_d = LocalRowSegment("siret3_r001_c002.tif", pts_d, [pixel_to_map(1, 2, px, py) for px, py in pts_d], "V01")

        res_cd = stitcher.stitch_block_rows("V01", [seg_c, seg_d])
        self.assertEqual(len(res_cd), 2)
        self.assertEqual(res_cd[0].assigned_row_id, res_cd[1].assigned_row_id)
        self.assertEqual(res_cd[0].assigned_row_id, "V01-R01")

    def test_boundary_matching_with_slanted_endpoints_away_from_boundary_merged_same_id(self):
        """
        Test that slanted boundary crossings where endpoints terminate before/after the
        shared tile seam (causing unprojected dy > 1.60m, e.g. 2.80m) successfully merge
        into the exact same row_id because their normal offset is <= 1.40m and along-row gap <= 18m.
        (Reproduces the real failure case in siret3_r007_c003 vs siret3_r007_c004 V02-R57/R58).
        """
        from src.spatial.grid import pixel_to_map
        stitcher = GlobalRowStitcher()

        # Real coordinates from siret3_r007_c003 vs siret3_r007_c004:
        # Tile A (c003): ends at (2011.7, 1314.3), 36.3px (0.9m) from East boundary
        # Tile B (c004): starts at (0.0, 1426.4) on West boundary
        # Unprojected dy = 112.1px = 2.80m (> 1.60m!), but normal offset is only 0.26m!
        pts_a = [(1455.0, 2.8), (2011.7, 1314.3)]
        pts_b = [(0.0, 1426.4), (263.8, 2048.0)]
        seg_a = LocalRowSegment("siret3_r007_c003.tif", pts_a, [pixel_to_map(7, 3, px, py) for px, py in pts_a], "V02")
        seg_b = LocalRowSegment("siret3_r007_c004.tif", pts_b, [pixel_to_map(7, 4, px, py) for px, py in pts_b], "V02")

        res = stitcher.stitch_block_rows("V02", [seg_a, seg_b])
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0].assigned_row_id, res[1].assigned_row_id)
        self.assertEqual(res[0].assigned_row_id, "V02-R01")

    def test_boundary_matching_with_local_orientation_variation(self):
        """
        Test that row segments matching locally at an angle that deviates ~15 degrees
        from the block modal angle still merge properly using local pair normal projection.
        (Reproduces V27 case across siret3_r034_c025 and siret3_r034_c026).
        """
        from src.spatial.grid import pixel_to_map
        stitcher = GlobalRowStitcher()

        # Dominant block orientation is ~55 degrees (from segments 1-4)
        # Segments 5 and 6 crossing the boundary between c025 and c026 run at ~40 degrees
        segs = []
        for i in range(4):
            y_base = 500.0 + i * 200.0
            p_1 = [(0.0, y_base), (2048.0, y_base + 1400.0)]  # ~55 deg
            segs.append(LocalRowSegment(f"siret3_r036_c026.tif", p_1, [pixel_to_map(36, 26, px, py) for px, py in p_1], "V27"))

        # Pair crossing at ~40 deg
        pts_cross_a = [(1500.0, 100.0), (2048.0, 1500.0)]
        pts_cross_b = [(50.0, 1530.0), (1000.0, 3000.0)]
        segs.append(LocalRowSegment("siret3_r034_c025.tif", pts_cross_a, [pixel_to_map(34, 25, px, py) for px, py in pts_cross_a], "V27"))
        segs.append(LocalRowSegment("siret3_r034_c026.tif", pts_cross_b, [pixel_to_map(34, 26, px, py) for px, py in pts_cross_b], "V27"))

        res = stitcher.stitch_block_rows("V27", segs)
        # Find segments on c025 and c026
        seg_c25 = [s for s in res if s.tile_name == "siret3_r034_c025.tif"][0]
        seg_c26 = [s for s in res if s.tile_name == "siret3_r034_c026.tif"][0]
        self.assertEqual(seg_c25.assigned_row_id, seg_c26.assigned_row_id)


if __name__ == "__main__":
    unittest.main()



