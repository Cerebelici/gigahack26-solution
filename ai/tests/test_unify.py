"""
Unit tests for whole-map unification (src/spatial/unify.py): rows that cross
tile edges become one physical row with one row_id, pieces meet at the edge,
roads split rows and blocks, and inter-rows are derived across tiles.
"""

import sys
import unittest
from pathlib import Path

import numpy as np
from shapely.geometry import Polygon, box

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.spatial.grid import tile_bounds, map_to_tile_indices
from src.spatial.unify import (
    TileSegment,
    build_interrows,
    build_physical_rows,
    cut_polygons_to_tiles,
    cut_rows_to_tiles,
    link_segments,
    merge_collinear_rows,
    number_rows,
    regroup_blocks,
    split_rows_at_passages,
    suppress_parallel_duplicates,
)

# Tiles r021_c012 and r021_c013 share the edge x = X_EDGE
LEFT, RIGHT = "siret3_r021_c012.tif", "siret3_r021_c013.tif"
X0, Y0, X_EDGE, Y1 = tile_bounds(21, 12)
Y_MID = 0.5 * (Y0 + Y1)
ANGLE = np.radians(8.0)  # rows run a little north of east
U = np.array([np.cos(ANGLE), np.sin(ANGLE)])
N = np.array([-U[1], U[0]])


def row_vines(offset_m, s_from, s_to, spacing=1.2, skip=None):
    """Vine centroids along a row through (X_EDGE, Y_MID) + offset * N."""
    base = np.array([X_EDGE, Y_MID]) + offset_m * N
    s = np.arange(s_from, s_to + 1e-6, spacing)
    if skip is not None:
        s = s[(s < skip[0]) | (s > skip[1])]
    return base + np.outer(s, U)


def segments_for(vines, block="V01"):
    """Split vines at the tile edge into per-tile segments, like per-tile extraction does."""
    out = []
    for tname in (LEFT, RIGHT):
        r, c = map(int, (tname[8:11], tname[13:16]))
        tb = box(*tile_bounds(r, c))
        v = np.array([p for p in vines if tb.contains(Polygon([
            (p[0] - 1e-3, p[1] - 1e-3), (p[0] + 1e-3, p[1] - 1e-3), (p[0], p[1] + 1e-3)]))])
        if len(v) < 2:
            continue
        # Per-tile line: slightly wrong angle and offset, as per-tile fitting produces
        jitter = 0.15 if tname == LEFT else -0.15
        p0 = v[0] + jitter * N
        p1 = v[-1] - jitter * N
        out.append(TileSegment(tile_name=tname, block_id=block, p0=tuple(p0), p1=tuple(p1), vines=v))
    return out


class UnifyRowsTestCase(unittest.TestCase):
    def setUp(self):
        self.valid_tiles = {LEFT, RIGHT}
        self.segs = []
        for k in range(4):  # four parallel rows 2.5 m apart crossing the edge
            self.segs += segments_for(row_vines(k * 2.5, -30.0, 30.0))

    def _rows(self, passages=None):
        chains = link_segments(self.segs, passages=passages)
        rows = build_physical_rows(self.segs, chains)
        rows = merge_collinear_rows(rows, passages=passages)
        rows = split_rows_at_passages(rows, passages)
        frames = number_rows(rows)
        return rows, frames

    def test_segments_across_edge_become_one_row(self):
        rows, _ = self._rows()
        self.assertEqual(len(rows), 4)
        for r in rows:
            self.assertEqual({self.segs[i].tile_name for i in r.segment_ids}, {LEFT, RIGHT})
            self.assertGreater(r.length_m, 59.0)
        self.assertEqual(sorted(r.row_id for r in rows), ["V01-R01", "V01-R02", "V01-R03", "V01-R04"])

    def test_pieces_share_row_id_and_meet_at_edge(self):
        rows, _ = self._rows()
        pieces = cut_rows_to_tiles(rows, self.valid_tiles)
        self.assertEqual(len(pieces[LEFT]), 4)
        self.assertEqual(len(pieces[RIGHT]), 4)
        for pl in pieces[LEFT]:
            pr = next(p for p in pieces[RIGHT] if p.owner == pl.owner)
            left_end = max(pl.points, key=lambda q: q[0])
            right_start = min(pr.points, key=lambda q: q[0])
            self.assertAlmostEqual(left_end[0], 2048.0, places=1)
            self.assertAlmostEqual(right_start[0], 0.0, places=1)
            self.assertLessEqual(abs(left_end[1] - right_start[1]), 0.2)  # same pixel row, 0.5 cm

    def test_gap_disrupts_only_the_tile_it_is_in(self):
        self.segs = segments_for(row_vines(0.0, -30.0, 30.0, skip=(8.0, 16.0)))
        self.segs += segments_for(row_vines(2.5, -30.0, 30.0))
        self.segs += segments_for(row_vines(5.0, -30.0, 30.0))
        rows, _ = self._rows()
        pieces = cut_rows_to_tiles(rows, self.valid_tiles)
        gap_row = min(range(len(rows)), key=lambda k: rows[k].vines[:, 1].mean())
        by_tile = {t: next(p for p in pieces[t] if p.owner == gap_row) for t in (LEFT, RIGHT)}
        self.assertEqual(by_tile[LEFT].row_structure, "regular")
        self.assertEqual(by_tile[RIGHT].row_structure, "disrupted")
        self.assertEqual(len(rows[gap_row].gaps()), 1)

    def test_road_across_rows_splits_rows_and_blocks(self):
        # 6 m wide track across all rows at s in [10, 16] m, with a few false vines on it
        track = Polygon([
            tuple(np.array([X_EDGE, Y_MID]) + s * U + t * N)
            for s, t in [(10, -5), (16, -5), (16, 15), (10, 15)]
        ])
        passages = track.buffer(0)
        rows, _ = self._rows(passages=passages)
        self.assertEqual(len(rows), 8)
        regroup_blocks(rows, passages=passages)
        self.assertEqual(len({r.vineyard_id for r in rows}), 2)

    def test_parallel_duplicate_is_suppressed(self):
        self.segs += segments_for(row_vines(0.9, -20.0, 20.0, spacing=3.0))  # weeds 0.9 m beside row 1
        chains = link_segments(self.segs)
        rows = build_physical_rows(self.segs, chains)
        rows = merge_collinear_rows(rows)
        self.assertEqual(len(suppress_parallel_duplicates(rows)), 4)

    def test_interrows_between_neighbours_and_cut_to_tiles(self):
        rows, frames = self._rows()
        interrows = build_interrows(rows, frames, margin_m=0.3)
        self.assertEqual(len(interrows), 3)
        for ir in interrows:
            # 2.5 m pitch minus 2 x 0.3 m margins = 1.9 m wide, ~61 m long
            self.assertAlmostEqual(ir.polygon.area, 1.9 * 61.0, delta=8.0)
        pieces = cut_polygons_to_tiles([ir.polygon for ir in interrows], self.valid_tiles)
        self.assertEqual(len(pieces[LEFT]), 3)
        self.assertEqual(len(pieces[RIGHT]), 3)
        for pl in pieces[LEFT] + pieces[RIGHT]:
            self.assertTrue(Polygon(pl.points).is_valid)


if __name__ == "__main__":
    unittest.main()
