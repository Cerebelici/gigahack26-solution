"""
Whole-map unification of per-tile detections (EPSG:32635).

Per-tile extraction sees a physical row only inside one 51.2 m tile, so a long
row arrives as several segments with slightly different positions and angles.
This module rebuilds the vineyard as a whole:

1. Links per-tile row segments end-to-end across tile edges into physical rows.
   Linking is local (end of one segment to the start of the next), so it stays
   correct when a block is long or its rows are not perfectly parallel.
2. Refits each physical row from all of its vines in map space, so the pieces
   of one row are one straight (or gently bent) line through every tile.
3. Splits a row where a gap crosses an authorised passage (a road always
   separates blocks) and numbers rows per block (V01-R01, V01-R02, ...).
4. Derives whole-map inter-row polygons between neighbouring rows of a block.
5. Cuts rows and inter-rows back to per-tile pixel geometry for Marcaj, so all
   pieces of a row share one row_id and meet exactly at the tile edge.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union
from shapely.prepared import prep
from shapely.validation import make_valid

from src.spatial.grid import GSD, map_to_pixel, parse_tile_indices, tile_bounds, TILE_PIXELS

GAP_DISRUPTED_M = 5.0


@dataclass
class TileSegment:
    """One row polyline found on one tile, in map coordinates."""
    tile_name: str
    block_id: str
    p0: Tuple[float, float]
    p1: Tuple[float, float]
    vines: np.ndarray  # (n, 2) canopy centroids of this row on this tile


@dataclass
class PhysicalRow:
    """One physical vine row on the whole map."""
    vineyard_id: str
    coords: List[Tuple[float, float]]  # map polyline, first vine to last vine
    vines: np.ndarray  # (n, 2) sorted along the row
    vine_s: np.ndarray  # distance of each vine along `coords`
    segment_ids: List[int] = field(default_factory=list)
    row_id: str = ""

    @property
    def line(self) -> LineString:
        return LineString(self.coords)

    @property
    def length_m(self) -> float:
        return float(self.line.length)

    def gaps(self, min_gap_m: float = GAP_DISRUPTED_M) -> List[Tuple[float, float]]:
        """Intervals (s_start, s_end) along the row with no vine for at least min_gap_m."""
        s = self.vine_s
        return [(float(a), float(b)) for a, b in zip(s[:-1], s[1:]) if b - a >= min_gap_m]


@dataclass
class PhysicalInterrow:
    vineyard_id: str
    polygon: Polygon  # map coordinates
    row_ids: Tuple[str, str]
    interrow_id: str = ""
    interrow_cover: str = "bare_soil"


@dataclass
class TilePiece:
    """A physical object cut to one tile, in pixel coordinates."""
    tile_name: str
    points: List[Tuple[float, float]]
    owner: int  # index of the PhysicalRow / PhysicalInterrow
    row_structure: str = "regular"


class _DSU:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> bool:
        ri, rj = self.find(i), self.find(j)
        if ri == rj:
            return False
        self.parent[rj] = ri
        return True


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else np.array([1.0, 0.0])


def _point_line_distance(p: np.ndarray, a: np.ndarray, d: np.ndarray) -> float:
    """Distance from p to the infinite line through a with unit direction d."""
    w = p - a
    return abs(float(w[0] * d[1] - w[1] * d[0]))


def _mean_axis(dirs: Sequence[np.ndarray], weights: Sequence[float]) -> np.ndarray:
    """Weighted mean of undirected axes (double-angle average)."""
    ang = np.array([np.arctan2(d[1], d[0]) for d in dirs])
    w = np.asarray(weights, dtype=float)
    a2 = np.arctan2(np.sum(w * np.sin(2 * ang)), np.sum(w * np.cos(2 * ang))) / 2.0
    return np.array([np.cos(a2), np.sin(a2)])


# ---------------------------------------------------------------------------
# 1. Link segments across tile edges
# ---------------------------------------------------------------------------

def _segment_axis(seg: TileSegment) -> Tuple[np.ndarray, np.ndarray]:
    """(centre, unit direction) of a segment's vines. Per-tile lines are snapped
    to whole degrees, which moves a 51 m line end by up to ~0.45 m, so the vines
    are the reliable geometry. Short segments keep the per-tile direction."""
    d_tile = _unit(np.subtract(seg.p1, seg.p0))
    v = np.asarray(seg.vines, dtype=float)
    if len(v) == 0:
        return 0.5 * (np.asarray(seg.p0) + np.asarray(seg.p1)), d_tile
    centre = v.mean(axis=0)
    if len(v) >= 4:
        _, _, vt = np.linalg.svd(v - centre, full_matrices=False)
        d = vt[0]
        extent = float(np.ptp((v - centre) @ d))
        if extent >= 8.0:
            return centre, d if np.dot(d, d_tile) >= 0 else -d
    return centre, d_tile


def link_segments(
    segments: List[TileSegment],
    passages=None,
    lateral_tol_m: float = 0.5,
    max_gap_m: float = 30.0,
    max_angle_deg: float = 8.0,
) -> List[List[int]]:
    """
    Chain segments that continue each other on the same or a neighbouring tile
    (8-neighbourhood). The longer segment's vine line is extended across the gap
    and the shorter segment's vines must sit on it (rows are ~2.5 m apart, so a
    neighbouring row is far outside the tolerance). Each end of a segment links
    at most once, so a chain is a simple path along one physical row.
    Returns chains as lists of segment indices.
    """
    n = len(segments)
    if n == 0:
        return []

    axes = [_segment_axis(s) for s in segments]
    centres = np.array([a[0] for a in axes])
    dirs = np.array([a[1] for a in axes])
    vines = [np.asarray(s.vines, dtype=float).reshape(-1, 2) for s in segments]
    for k, s in enumerate(segments):
        if len(vines[k]) == 0:
            vines[k] = np.array([s.p0, s.p1], dtype=float)
    cos_tol = np.cos(np.radians(max_angle_deg))
    prep_pass = prep(passages) if passages is not None else None

    by_tile: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    tile_rc = []
    for i, s in enumerate(segments):
        rc = parse_tile_indices(s.tile_name)
        tile_rc.append(rc)
        by_tile[rc].append(i)

    cands = []
    for i in range(n):
        r, c = tile_rc[i]
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                for j in by_tile.get((r + dr, c + dc), []):
                    if j <= i:
                        continue
                    dot = float(np.dot(dirs[i], dirs[j]))
                    if abs(dot) < cos_tol:
                        continue
                    u = _unit(dirs[i] + (dirs[j] if dot > 0 else -dirs[j]))

                    ai = vines[i] @ u
                    aj = vines[j] @ u
                    i_first = ai.mean() <= aj.mean()
                    gap = float(aj.min() - ai.max()) if i_first else float(ai.min() - aj.max())
                    if gap < -1.5 or gap > max_gap_m:
                        continue
                    # End flag 1 = the end along the segment's own +direction
                    ei = int((np.dot(u, dirs[i]) > 0) == i_first)
                    ej = int((np.dot(u, dirs[j]) > 0) != i_first)

                    long_k, short_k = (i, j) if len(vines[i]) >= len(vines[j]) else (j, i)
                    lateral = float(np.mean([
                        _point_line_distance(p, centres[long_k], dirs[long_k]) for p in vines[short_k]
                    ]))
                    if lateral > lateral_tol_m + 0.01 * max(gap, 0.0):
                        continue

                    if i_first:
                        end_i, end_j = vines[i][np.argmax(ai)], vines[j][np.argmin(aj)]
                    else:
                        end_i, end_j = vines[i][np.argmin(ai)], vines[j][np.argmax(aj)]

                    if prep_pass is not None and gap > 2.0:
                        bridge = LineString([end_i, end_j])
                        if prep_pass.intersects(bridge) and bridge.intersection(passages).length > 2.0:
                            continue

                    cost = lateral + 0.01 * max(gap, 0.0)
                    cands.append((cost, i, ei, j, ej))

    cands.sort(key=lambda x: x[0])
    used_ends = set()
    dsu = _DSU(n)
    for _, i, ei, j, ej in cands:
        if (i, ei) in used_ends or (j, ej) in used_ends:
            continue
        if not dsu.union(i, j):
            continue
        used_ends.add((i, ei))
        used_ends.add((j, ej))

    chains: Dict[int, List[int]] = defaultdict(list)
    for i in range(n):
        chains[dsu.find(i)].append(i)
    return list(chains.values())


# ---------------------------------------------------------------------------
# 2. Fit one physical row from its vines
# ---------------------------------------------------------------------------

def _dp_simplify(pts: np.ndarray, tol: float) -> np.ndarray:
    if len(pts) <= 2:
        return pts
    simplified = LineString(pts).simplify(tol, preserve_topology=False)
    return np.array(simplified.coords)


def fit_row_polyline(
    vines: np.ndarray,
    axis_hint: Optional[np.ndarray] = None,
    end_margin_m: float = 0.5,
    bend_tol_m: float = 0.20,
    knot_spacing_m: float = 20.0,
    inlier_tol_m: float = 0.6,
) -> Tuple[List[Tuple[float, float]], np.ndarray]:
    """
    Fit a row axis through vine centroids. Straight rows give two points; a row
    whose vines leave a straight line by more than bend_tol_m gets knots every
    knot_spacing_m (the rules allow extra points where a row bends).
    Returns (map polyline, inlier vines sorted along the row).
    """
    vines = np.asarray(vines, dtype=float)
    centre = vines.mean(axis=0)
    X = vines - centre
    if len(vines) >= 3:
        _, _, vt = np.linalg.svd(X, full_matrices=False)
        d = vt[0]
    elif axis_hint is not None:
        d = _unit(axis_hint)
    else:
        d = _unit(X[-1] - X[0])
    nrm = np.array([-d[1], d[0]])

    s = X @ d
    t = X @ nrm
    # Drop vines far off the axis (weeds or a neighbouring row's plant)
    keep = np.ones(len(vines), dtype=bool)
    if len(vines) >= 5:
        for _ in range(2):
            coef = np.polyfit(s[keep], t[keep], 1)
            res = t - np.polyval(coef, s)
            keep = np.abs(res) <= max(inlier_tol_m, 3.0 * float(np.median(np.abs(res[keep]))))
        if keep.sum() < 2:
            keep[:] = True
    s, t, vines = s[keep], t[keep], vines[keep]
    order = np.argsort(s)
    s, t, vines = s[order], t[order], vines[order]

    s_lo, s_hi = float(s[0]) - end_margin_m, float(s[-1]) + end_margin_m
    if len(s) >= 2:
        coef = np.polyfit(s, t, 1)
    else:
        coef = np.array([0.0, float(t[0])])
    res = t - np.polyval(coef, s)

    if (s_hi - s_lo) > 2 * knot_spacing_m and len(s) >= 8 and float(np.percentile(np.abs(res), 90)) > bend_tol_m:
        n_knots = int(np.ceil((s_hi - s_lo) / knot_spacing_m)) + 1
        knots = np.linspace(s_lo, s_hi, n_knots)
        kt = []
        for k in knots:
            w = np.abs(s - k) <= knot_spacing_m
            if w.sum() >= 3:
                c_loc = np.polyfit(s[w], t[w], 1)
                kt.append(float(np.polyval(c_loc, k)))
            else:
                kt.append(float(np.polyval(coef, k)))
        st = np.column_stack([knots, kt])
        st = _dp_simplify(st, 0.05)
    else:
        st = np.array([[s_lo, np.polyval(coef, s_lo)], [s_hi, np.polyval(coef, s_hi)]])

    pts = centre + np.outer(st[:, 0], d) + np.outer(st[:, 1], nrm)
    return [(float(x), float(y)) for x, y in pts], vines


def _make_row(vines: np.ndarray, block_id: str, seg_ids: List[int], axis_hint, end_margin_m) -> PhysicalRow:
    coords, inliers = fit_row_polyline(vines, axis_hint=axis_hint, end_margin_m=end_margin_m)
    line = LineString(coords)
    vine_s = np.array([line.project(Point(p)) for p in inliers])
    order = np.argsort(vine_s)
    return PhysicalRow(
        vineyard_id=block_id,
        coords=coords,
        vines=inliers[order],
        vine_s=vine_s[order],
        segment_ids=list(seg_ids),
    )


def build_physical_rows(
    segments: List[TileSegment],
    chains: List[List[int]],
    passages=None,
    end_margin_m: float = 0.5,
    min_vines: int = 2,
) -> List[PhysicalRow]:
    """Turn chains of segments into refitted physical rows."""
    rows: List[PhysicalRow] = []
    for chain in chains:
        vines = np.vstack([segments[i].vines for i in chain if len(segments[i].vines)])
        if len(vines) < min_vines:
            continue
        # Block of a physical row: length-weighted majority of its tile segments
        votes = Counter()
        hint_dirs, hint_w = [], []
        for i in chain:
            seg_len = float(np.hypot(*(np.subtract(segments[i].p1, segments[i].p0))))
            votes[segments[i].block_id] += seg_len + 1e-3
            hint_dirs.append(_unit(np.subtract(segments[i].p1, segments[i].p0)))
            hint_w.append(seg_len + 1e-3)
        block_id = votes.most_common(1)[0][0]
        axis = _mean_axis(hint_dirs, hint_w)

        rows.append(_make_row(vines, block_id, chain, axis, end_margin_m))
    return rows


def merge_collinear_rows(
    rows: List[PhysicalRow],
    lateral_tol_m: float = 0.4,
    max_gap_m: float = 30.0,
    max_angle_deg: float = 3.0,
    passages=None,
    end_margin_m: float = 0.5,
) -> List[PhysicalRow]:
    """
    Second pass on refitted rows: rows lying on one line (the shorter row's vines
    within lateral_tol_m of the longer row's axis) are one physical row. This
    absorbs duplicate segments and links that the tile-edge pass missed.
    """
    from shapely.strtree import STRtree

    rows = list(rows)
    cos_tol = np.cos(np.radians(max_angle_deg))
    cos_short = np.cos(np.radians(12.0))
    prep_pass = prep(passages) if passages is not None else None
    changed = True
    while changed:
        changed = False
        lines = [r.line for r in rows]
        tree = STRtree(lines)
        dirs = [_unit(np.subtract(r.coords[-1], r.coords[0])) for r in rows]
        dsu = _DSU(len(rows))
        for i, li in enumerate(lines):
            for j in tree.query(li.buffer(max_gap_m)):
                j = int(j)
                if j <= i:
                    continue
                # A short row's own direction is noisy; its vines' lateral
                # distance to the longer axis (below) is the real test
                tol = cos_tol if min(rows[i].length_m, rows[j].length_m) >= 15.0 else cos_short
                if abs(float(np.dot(dirs[i], dirs[j]))) < tol:
                    continue
                long_k, short_k = (i, j) if len(rows[i].vines) >= len(rows[j].vines) else (j, i)
                ll = lines[long_k]
                c = np.asarray(rows[long_k].vines).mean(axis=0)
                lat = float(np.mean([_point_line_distance(p, c, dirs[long_k]) for p in rows[short_k].vines]))
                if lat > lateral_tol_m:
                    continue
                # Along-row gap between the two vine sets
                u = dirs[long_k]
                a_l = rows[long_k].vines @ u
                a_s = rows[short_k].vines @ u
                gap = max(float(a_s.min() - a_l.max()), float(a_l.min() - a_s.max()))
                if gap > max_gap_m:
                    continue
                if prep_pass is not None and gap > 2.0:
                    if a_s.mean() > a_l.mean():
                        bridge = LineString([rows[long_k].vines[np.argmax(a_l)], rows[short_k].vines[np.argmin(a_s)]])
                    else:
                        bridge = LineString([rows[long_k].vines[np.argmin(a_l)], rows[short_k].vines[np.argmax(a_s)]])
                    if prep_pass.intersects(bridge) and bridge.intersection(passages).length > 2.0:
                        continue
                if dsu.union(i, j):
                    changed = True
        if changed:
            groups: Dict[int, List[int]] = defaultdict(list)
            for k in range(len(rows)):
                groups[dsu.find(k)].append(k)
            merged = []
            for members in groups.values():
                if len(members) == 1:
                    merged.append(rows[members[0]])
                    continue
                votes = Counter()
                for k in members:
                    votes[rows[k].vineyard_id] += rows[k].length_m
                vines = np.vstack([rows[k].vines for k in members])
                seg_ids = [s for k in members for s in rows[k].segment_ids]
                axis = _mean_axis([dirs[k] for k in members], [rows[k].length_m for k in members])
                merged.append(_make_row(vines, votes.most_common(1)[0][0], seg_ids, axis, end_margin_m))
            rows = merged
    return rows


def reattach_canopies(
    rows: List[PhysicalRow],
    centroids: np.ndarray,
    lateral_tol_m: float = 0.5,
    end_slack_m: float = 1.5,
    end_margin_m: float = 0.5,
) -> List[PhysicalRow]:
    """
    Per-tile clustering hands over only the canopies it put into rows, so a
    physical row can miss plants and show false gaps. Re-attach every detected
    canopy to the row axis it stands on and refit.
    """
    from scipy.spatial import cKDTree

    centroids = np.asarray(centroids, dtype=float).reshape(-1, 2)
    if len(centroids) == 0 or not rows:
        return rows
    tree = cKDTree(centroids)
    best_row = np.full(len(centroids), -1)
    best_d = np.full(len(centroids), np.inf)
    for k, r in enumerate(rows):
        line = r.line
        cand = tree.query_ball_point(np.asarray(line.interpolate(0.5, normalized=True).coords[0]),
                                     0.5 * line.length + end_slack_m + lateral_tol_m)
        for ci in cand:
            p = Point(centroids[ci])
            s = line.project(p)
            if s <= 0.0 or s >= line.length:
                # beyond an end: allow a short extension along the axis only
                end = Point(line.coords[0] if s <= 0.0 else line.coords[-1])
                if p.distance(end) > end_slack_m:
                    continue
            d = line.distance(p)
            if d <= lateral_tol_m and d < best_d[ci]:
                best_d[ci] = d
                best_row[ci] = k
    out = []
    for k, r in enumerate(rows):
        v = centroids[best_row == k]
        if len(v) < 2:
            out.append(r)
            continue
        axis = _unit(np.subtract(r.coords[-1], r.coords[0]))
        nr = _make_row(v, r.vineyard_id, r.segment_ids, axis, end_margin_m)
        out.append(nr)
    return out


def suppress_parallel_duplicates(
    rows: List[PhysicalRow],
    max_lateral_m: float = 1.3,
    min_overlap_frac: float = 0.5,
    max_angle_deg: float = 5.0,
) -> List[PhysicalRow]:
    """
    Rows are at least ~2 m apart, so two parallel rows closer than max_lateral_m
    that overlap along most of the weaker one are one physical row seen twice
    (weeds or canopy edges beside the row). Keep the row with more vines per metre.
    """
    from shapely.strtree import STRtree

    lines = [r.line for r in rows]
    tree = STRtree(lines)
    dirs = [_unit(np.subtract(r.coords[-1], r.coords[0])) for r in rows]
    density = [len(r.vines) / max(r.length_m, 0.5) for r in rows]
    dropped = set()
    order = sorted(range(len(rows)), key=lambda k: -density[k])
    for i in order:
        if i in dropped:
            continue
        for j in tree.query(lines[i].buffer(max_lateral_m)):
            j = int(j)
            if j == i or j in dropped or density[j] > density[i]:
                continue
            if abs(float(np.dot(dirs[i], dirs[j]))) < np.cos(np.radians(max_angle_deg)):
                continue
            d = np.array([lines[i].distance(Point(p)) for p in rows[j].vines])
            near = d <= max_lateral_m
            if near.mean() >= min_overlap_frac and float(np.median(d[near])) >= 0.25:
                dropped.add(j)
    return [r for k, r in enumerate(rows) if k not in dropped]


def split_rows_at_passages(rows: List[PhysicalRow], passages, end_margin_m: float = 0.5, min_vines: int = 2):
    out = []
    for r in rows:
        axis = _unit(np.subtract(r.coords[-1], r.coords[0]))
        out.extend(_split_at_passages(r, passages, axis, end_margin_m, min_vines))
    return out


def drop_isolated_rows(rows: List[PhysicalRow], max_pitch_m: float = 5.0, min_overlap_m: float = 2.0) -> List[PhysicalRow]:
    """
    A vineyard needs at least three rows, so a row with no parallel neighbour
    within max_pitch_m is a false detection (tree line, hedge, weeds).
    """
    from shapely.strtree import STRtree

    lines = [r.line for r in rows]
    tree = STRtree(lines)
    dirs = [_unit(np.subtract(r.coords[-1], r.coords[0])) for r in rows]
    keep = []
    for i, li in enumerate(lines):
        ok = False
        for j in tree.query(li.buffer(max_pitch_m)):
            j = int(j)
            if j == i or abs(float(np.dot(dirs[i], dirs[j]))) < np.cos(np.radians(10.0)):
                continue
            # Overlap along the row and lateral distance within one pitch
            u = dirs[i]
            ai = rows[i].vines @ u
            aj = rows[j].vines @ u
            if min(ai.max(), aj.max()) - max(ai.min(), aj.min()) < min_overlap_m:
                continue
            c = rows[i].vines.mean(axis=0)
            lat = float(np.median([_point_line_distance(p, c, u) for p in rows[j].vines]))
            if 0.8 <= lat <= max_pitch_m:
                ok = True
                break
        if ok:
            keep.append(rows[i])
    return keep


def _split_at_passages(row: PhysicalRow, passages, axis, end_margin_m, min_vines,
                       max_crossing_m: float = 15.0) -> List[PhysicalRow]:
    """
    A road or track always separates blocks: cut a row where its axis crosses
    an authorised passage inside the row (1-15 m of passage between vines on
    both sides). Vines on the passage itself are dropped. Passage overlaps at
    a row end, or long stretches where a buffered road runs along a row, are
    left alone (the OSM buffers are not exact).
    """
    if passages is None or len(row.vines) < 2 * min_vines:
        return [row]
    line = row.line
    if not line.intersects(passages):
        return [row]
    inter = line.intersection(passages)
    pieces = [g for g in getattr(inter, "geoms", [inter]) if isinstance(g, LineString)]
    cut_intervals = []
    for pc in pieces:
        if not (1.0 <= pc.length <= max_crossing_m):
            continue
        a = line.project(Point(pc.coords[0]))
        b = line.project(Point(pc.coords[-1]))
        lo, hi = min(a, b), max(a, b)
        # Only interior crossings: vines on both sides
        if np.sum(row.vine_s < lo) >= min_vines and np.sum(row.vine_s > hi) >= min_vines:
            cut_intervals.append((lo, hi))
    if not cut_intervals:
        return [row]
    cut_intervals.sort()
    parts, start_s = [], -np.inf
    for lo, hi in cut_intervals + [(np.inf, np.inf)]:
        sel = (row.vine_s > start_s) & (row.vine_s < lo)
        if sel.sum() >= min_vines:
            parts.append(_make_row(row.vines[sel], row.vineyard_id, row.segment_ids, axis, end_margin_m))
        start_s = hi
    return parts or [row]


# ---------------------------------------------------------------------------
# 3. Blocks: frame, numbering
# ---------------------------------------------------------------------------

@dataclass
class BlockFrame:
    origin: np.ndarray
    u: np.ndarray  # along rows
    n: np.ndarray  # across rows, pointing east (or north when rows run east-west)

    def to_st(self, pts) -> np.ndarray:
        X = np.asarray(pts, dtype=float) - self.origin
        return np.column_stack([X @ self.u, X @ self.n])

    def to_map(self, st) -> np.ndarray:
        st = np.asarray(st, dtype=float)
        return self.origin + np.outer(st[:, 0], self.u) + np.outer(st[:, 1], self.n)


def block_frame(rows: List[PhysicalRow]) -> BlockFrame:
    dirs = [_unit(np.subtract(r.coords[-1], r.coords[0])) for r in rows]
    u = _mean_axis(dirs, [r.length_m for r in rows])
    n = np.array([-u[1], u[0]])
    if n[0] < -1e-6 or (abs(n[0]) <= 1e-6 and n[1] < 0):
        n = -n
    origin = np.mean(np.vstack([r.vines for r in rows]), axis=0)
    return BlockFrame(origin=origin, u=u, n=n)


def _row_st(row: PhysicalRow, frame: BlockFrame) -> np.ndarray:
    st = frame.to_st(row.coords)
    return st[np.argsort(st[:, 0])]


def number_rows(rows: List[PhysicalRow]) -> Dict[str, BlockFrame]:
    """Assign row_id = <vineyard_id>-R<nn>, numbered across each block."""
    by_block: Dict[str, List[PhysicalRow]] = defaultdict(list)
    for r in rows:
        by_block[r.vineyard_id].append(r)
    frames = {}
    for vid, b_rows in by_block.items():
        frame = block_frame(b_rows)
        frames[vid] = frame
        keyed = []
        for r in b_rows:
            st = _row_st(r, frame)
            keyed.append((float(np.mean(st[:, 1])), float(np.mean(st[:, 0])), r))
        keyed.sort(key=lambda x: (round(x[0], 1), x[1]))
        width = 2 if len(keyed) < 100 else 3
        for idx, (_, _, r) in enumerate(keyed, start=1):
            r.row_id = f"{vid}-R{idx:0{width}d}"
    return frames


# ---------------------------------------------------------------------------
# 4. Whole-map inter-rows
# ---------------------------------------------------------------------------

def _subtract_interval(intervals: List[Tuple[float, float]], a: float, b: float) -> List[Tuple[float, float]]:
    out = []
    for x, y in intervals:
        if b <= x or a >= y:
            out.append((x, y))
            continue
        if a > x:
            out.append((x, a))
        if b < y:
            out.append((b, y))
    return out


def build_interrows(
    rows: List[PhysicalRow],
    frames: Dict[str, BlockFrame],
    margin_m: float = 0.30,
    min_overlap_m: float = 3.0,
    max_pitch_factor: float = 1.6,
) -> List[PhysicalInterrow]:
    """
    One polygon per pair of neighbouring rows in a block, over the stretch where
    both rows exist ("if one row is shorter, end at the shorter one"). Long sides
    sit margin_m off each row axis (canopy edge). A row facing two shorter rows
    in line gets one inter-row per neighbour.
    """
    by_block: Dict[str, List[PhysicalRow]] = defaultdict(list)
    for r in rows:
        by_block[r.vineyard_id].append(r)

    out: List[PhysicalInterrow] = []
    for vid, b_rows in by_block.items():
        if len(b_rows) < 2:
            continue
        frame = frames[vid]
        sts = [_row_st(r, frame) for r in b_rows]

        def t_at(k: int, s):
            return np.interp(s, sts[k][:, 0], sts[k][:, 1])

        # Row pitch of the block from nearest overlapping neighbours
        pitches = []
        for a in range(len(b_rows)):
            best = None
            for b in range(len(b_rows)):
                if a == b:
                    continue
                lo = max(sts[a][0, 0], sts[b][0, 0])
                hi = min(sts[a][-1, 0], sts[b][-1, 0])
                if hi - lo < min_overlap_m:
                    continue
                dt = float(t_at(b, 0.5 * (lo + hi)) - t_at(a, 0.5 * (lo + hi)))
                if dt > 0.8 and (best is None or dt < best):
                    best = dt
            if best is not None:
                pitches.append(best)
        if not pitches:
            continue
        pitch = float(np.median(pitches))

        for a in range(len(b_rows)):
            cands = []
            for b in range(len(b_rows)):
                if a == b:
                    continue
                lo = max(sts[a][0, 0], sts[b][0, 0])
                hi = min(sts[a][-1, 0], sts[b][-1, 0])
                if hi - lo < min_overlap_m:
                    continue
                dt = float(t_at(b, 0.5 * (lo + hi)) - t_at(a, 0.5 * (lo + hi)))
                if 0.5 * pitch <= dt <= max_pitch_factor * pitch:
                    cands.append((dt, b, lo, hi))
            cands.sort()
            free = [(sts[a][0, 0], sts[a][-1, 0])]
            for dt, b, lo, hi in cands:
                for x, y in list(free):
                    s0, s1 = max(x, lo), min(y, hi)
                    if s1 - s0 < min_overlap_m:
                        continue
                    m = min(margin_m, 0.25 * dt)
                    knots = [s0, s1] + [
                        float(v) for k in (a, b) for v in sts[k][:, 0] if s0 < v < s1
                    ]
                    ss = np.array(sorted(set(knots)))
                    low = np.column_stack([ss, t_at(a, ss) + m])
                    high = np.column_stack([ss[::-1], t_at(b, ss[::-1]) - m])
                    poly = Polygon(frame.to_map(np.vstack([low, high])))
                    if not poly.is_valid:
                        poly = make_valid(poly)
                        if not isinstance(poly, Polygon):
                            polys = [g for g in getattr(poly, "geoms", []) if isinstance(g, Polygon)]
                            if not polys:
                                continue
                            poly = max(polys, key=lambda g: g.area)
                    if poly.area >= 1.0:
                        out.append(PhysicalInterrow(
                            vineyard_id=vid,
                            polygon=poly,
                            row_ids=(b_rows[a].row_id, b_rows[b].row_id),
                        ))
                    free = _subtract_interval(free, s0, s1)

    # Stable ids per block
    counters: Dict[str, int] = defaultdict(int)
    out.sort(key=lambda ir: (ir.vineyard_id, ir.row_ids))
    for ir in out:
        counters[ir.vineyard_id] += 1
        ir.interrow_id = f"{ir.vineyard_id}-I{counters[ir.vineyard_id]:03d}"
    return out


# ---------------------------------------------------------------------------
# 5. Cut back to tiles
# ---------------------------------------------------------------------------

def _tiles_touching(geom, tile_names_known: Optional[set] = None) -> List[Tuple[int, int]]:
    from src.spatial.grid import map_to_tile_indices
    minx, miny, maxx, maxy = geom.bounds
    r0, c0 = map_to_tile_indices(minx, maxy)
    r1, c1 = map_to_tile_indices(maxx, miny)
    return [(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]


def _tile_name(r: int, c: int) -> str:
    return f"siret3_r{r:03d}_c{c:03d}.tif"


def _to_px(r: int, c: int, coords) -> List[Tuple[float, float]]:
    out = []
    for e, nn in coords:
        px, py = map_to_pixel(r, c, e, nn)
        out.append((round(min(max(px, 0.0), TILE_PIXELS), 1), round(min(max(py, 0.0), TILE_PIXELS), 1)))
    return out


def cut_rows_to_tiles(
    rows: List[PhysicalRow],
    valid_tiles: set,
    min_piece_m: float = 1.0,
) -> Dict[str, List[TilePiece]]:
    """
    Cut each physical row at tile edges. A piece is kept only if at least one
    vine of that row lies on the tile. row_structure is judged per tile: a gap
    of 5 m or more inside this tile makes the piece 'disrupted'.
    """
    out: Dict[str, List[TilePiece]] = defaultdict(list)
    for idx, row in enumerate(rows):
        line = row.line
        gaps = row.gaps(GAP_DISRUPTED_M)
        for r, c in _tiles_touching(line):
            name = _tile_name(r, c)
            if name not in valid_tiles:
                continue
            tb = box(*tile_bounds(r, c))
            inter = line.intersection(tb)
            if inter.is_empty:
                continue
            pieces = list(inter.geoms) if isinstance(inter, MultiLineString) else [inter]
            for piece in pieces:
                if not isinstance(piece, LineString) or piece.length < min_piece_m:
                    continue
                s_a = line.project(Point(piece.coords[0]))
                s_b = line.project(Point(piece.coords[-1]))
                s_lo, s_hi = min(s_a, s_b), max(s_a, s_b)
                n_vines = int(np.sum((row.vine_s >= s_lo - 0.05) & (row.vine_s <= s_hi + 0.05)))
                if n_vines == 0:
                    continue
                disrupted = any(min(g1, s_hi) - max(g0, s_lo) >= GAP_DISRUPTED_M for g0, g1 in gaps)
                pts = _to_px(r, c, piece.coords)
                dedup = [pts[0]] + [p for k, p in enumerate(pts[1:], 1) if p != pts[k - 1]]
                if len(dedup) < 2:
                    continue
                out[name].append(TilePiece(
                    tile_name=name,
                    points=dedup,
                    owner=idx,
                    row_structure="disrupted" if disrupted else "regular",
                ))
    return out


def cut_polygons_to_tiles(
    polygons: List[Polygon],
    valid_tiles: set,
    min_area_m2: float = 0.25,
) -> Dict[str, List[TilePiece]]:
    """Cut map-space polygons at tile edges into per-tile pixel polygons."""
    out: Dict[str, List[TilePiece]] = defaultdict(list)
    for idx, poly in enumerate(polygons):
        for r, c in _tiles_touching(poly):
            name = _tile_name(r, c)
            if name not in valid_tiles:
                continue
            inter = poly.intersection(box(*tile_bounds(r, c)))
            if inter.is_empty:
                continue
            geoms = list(inter.geoms) if hasattr(inter, "geoms") else [inter]
            for g in geoms:
                if not isinstance(g, Polygon) or g.area < min_area_m2:
                    continue
                g = g.simplify(0.01, preserve_topology=True)
                pts = _to_px(r, c, list(g.exterior.coords)[:-1])
                dedup = [pts[0]] + [p for k, p in enumerate(pts[1:], 1) if p != pts[k - 1]]
                if len(dedup) >= 3 and dedup[0] == dedup[-1]:
                    dedup.pop()
                if len(dedup) < 3:
                    continue
                pg = Polygon(dedup)
                if not pg.is_valid or pg.area < min_area_m2 / (GSD * GSD):
                    continue
                out[name].append(TilePiece(tile_name=name, points=dedup, owner=idx))
    return out


# ---------------------------------------------------------------------------
# 6. Canopy -> block via its row
# ---------------------------------------------------------------------------

class RowIndex:
    """Nearest physical row lookup for map points (densified KD-tree)."""

    def __init__(self, rows: List[PhysicalRow], step_m: float = 0.5):
        from scipy.spatial import cKDTree
        pts, owner = [], []
        for idx, r in enumerate(rows):
            line = r.line
            n = max(2, int(np.ceil(line.length / step_m)) + 1)
            for d in np.linspace(0.0, line.length, n):
                p = line.interpolate(d)
                pts.append((p.x, p.y))
                owner.append(idx)
        self.owner = np.array(owner)
        self.tree = cKDTree(np.array(pts)) if pts else None

    def nearest(self, xy: np.ndarray, max_dist_m: float) -> np.ndarray:
        """Row index per point, -1 when no row is within max_dist_m."""
        if self.tree is None or len(xy) == 0:
            return np.full(len(xy), -1)
        d, i = self.tree.query(np.asarray(xy), k=1)
        res = self.owner[i]
        res[d > max_dist_m] = -1
        return res


def block_polygons(rows: List[PhysicalRow], interrows: List[PhysicalInterrow], half_width_m: float = 1.0):
    """Outline of each block: its inter-rows plus a buffer around its row axes."""
    parts: Dict[str, list] = defaultdict(list)
    for r in rows:
        parts[r.vineyard_id].append(r.line.buffer(half_width_m, cap_style=2))
    for ir in interrows:
        parts[ir.vineyard_id].append(ir.polygon)
    return {vid: unary_union(g).simplify(0.2) for vid, g in parts.items()}


# ---------------------------------------------------------------------------
# 7. Blocks from rows: clearings split rows, connected plantings form blocks
# ---------------------------------------------------------------------------

def _side_neighbours(rows: List[PhysicalRow], k: int, pt: Point, tree, lines, dirs, max_pitch_m: float):
    """Nearest parallel row on each side of row k at point pt: {+1: idx, -1: idx}."""
    best: Dict[int, Tuple[float, int]] = {}
    u = dirs[k]
    for j in tree.query(pt.buffer(max_pitch_m)):
        j = int(j)
        if j == k or abs(float(np.dot(u, dirs[j]))) < np.cos(np.radians(10.0)):
            continue
        q = lines[j].interpolate(lines[j].project(pt))
        w = np.array([q.x - pt.x, q.y - pt.y])
        lat = abs(float(u[0] * w[1] - u[1] * w[0]))
        if not (1.0 <= lat <= max_pitch_m):
            continue
        side = 1 if (u[0] * w[1] - u[1] * w[0]) > 0 else -1
        if side not in best or lat < best[side][0]:
            best[side] = (lat, j)
    return {side: j for side, (_, j) in best.items()}


def split_at_clearings(
    rows: List[PhysicalRow],
    min_gap_m: float = 6.0,
    neighbour_gap_m: float = 4.0,
    align_m: float = 8.0,
    max_pitch_m: float = 4.5,
    end_margin_m: float = 0.5,
    min_vines: int = 2,
) -> Tuple[List[PhysicalRow], int]:
    """
    A track, headland or tree line across a block shows as a gap at the same
    place in neighbouring rows. Cut a row at a gap when every neighbouring row
    (one on each side, where present) also has a gap there or ends there.
    Scattered missing vines do not line up, so ordinary gaps stay inside the row.
    Returns (rows, number of cuts).
    """
    from shapely.strtree import STRtree

    lines = [r.line for r in rows]
    tree = STRtree(lines)
    dirs = [_unit(np.subtract(r.coords[-1], r.coords[0])) for r in rows]
    gaps_all = [r.gaps(neighbour_gap_m) for r in rows]

    def open_at(j: int, pt: Point) -> bool:
        s = lines[j].project(pt)
        vs = rows[j].vine_s
        if s < vs[0] - align_m / 2 or s > vs[-1] + align_m / 2:
            return True  # neighbour row ends here
        return any(g0 - align_m / 2 <= s <= g1 + align_m / 2 for g0, g1 in gaps_all[j])

    out: List[PhysicalRow] = []
    n_cuts = 0
    for k, r in enumerate(rows):
        cuts = []
        for idx in range(len(r.vine_s) - 1):
            g0, g1 = r.vine_s[idx], r.vine_s[idx + 1]
            if g1 - g0 < min_gap_m:
                continue
            pt = lines[k].interpolate(0.5 * (g0 + g1))
            nb = _side_neighbours(rows, k, pt, tree, lines, dirs, max_pitch_m)
            if nb and all(open_at(j, pt) for j in nb.values()):
                cuts.append(idx + 1)
        if not cuts:
            out.append(r)
            continue
        n_cuts += len(cuts)
        bounds = [0] + cuts + [len(r.vines)]
        axis = dirs[k]
        for a, b in zip(bounds[:-1], bounds[1:]):
            if b - a >= min_vines:
                out.append(_make_row(r.vines[a:b], r.vineyard_id, r.segment_ids, axis, end_margin_m))
    return out, n_cuts


def regroup_blocks(
    rows: List[PhysicalRow],
    passages=None,
    max_pitch_m: float = 5.5,
    min_overlap_m: float = 2.0,
    min_block_rows: int = 3,
) -> Dict[str, str]:
    """
    A block is a connected planting: rows are joined when they are parallel
    neighbours at most max_pitch_m apart with no authorised passage between them
    (a road or track always separates blocks). Each block keeps the file1 name
    most of its rows carry; a second block claiming a name gets a new id.
    Sets row.vineyard_id in place (empty for dropped noise rows) and returns
    {new_id: original file1 id}.
    """
    from shapely.strtree import STRtree

    n = len(rows)
    lines = [r.line for r in rows]
    tree = STRtree(lines)
    dirs = [_unit(np.subtract(r.coords[-1], r.coords[0])) for r in rows]
    prep_pass = prep(passages) if passages is not None else None

    # Land enclosed by passages (the holes of the passage polygons) is a hard
    # boundary: rows in two different enclosed parcels are never one block.
    cells = []
    if passages is not None:
        for g in getattr(passages, "geoms", [passages]):
            cells.extend(Polygon(h) for h in g.interiors if Polygon(h).area > 100.0)
    cell_of = []
    for li in lines:
        best, best_len = -1, 0.0
        for c_idx, cell in enumerate(cells):
            if cell.intersects(li):
                ln = cell.intersection(li).length
                if ln > best_len:
                    best, best_len = c_idx, ln
        cell_of.append(best if best_len > 0.5 * li.length else -1)

    dsu = _DSU(n)
    near_pairs = []
    for i in range(n):
        for j in tree.query(lines[i].buffer(max_pitch_m)):
            j = int(j)
            if j <= i or abs(float(np.dot(dirs[i], dirs[j]))) < np.cos(np.radians(10.0)):
                continue
            if cell_of[i] != cell_of[j]:
                continue
            u = dirs[i]
            ai, aj = rows[i].vines @ u, rows[j].vines @ u
            lo, hi = max(ai.min(), aj.min()), min(ai.max(), aj.max())
            if hi - lo < min_overlap_m:
                continue
            # Sample the strip between the rows at a few places along the overlap
            joined = False
            for f in np.linspace(0.1, 0.9, 5):
                s_mid = lo + f * (hi - lo)
                c_i = rows[i].vines.mean(axis=0)
                p_i = c_i + (s_mid - float(c_i @ u)) * u
                q = lines[j].interpolate(lines[j].project(Point(p_i)))
                p_i = lines[i].interpolate(lines[i].project(q))
                link = LineString([(p_i.x, p_i.y), (q.x, q.y)])
                if link.length > max_pitch_m or link.length < 0.8:
                    continue
                if prep_pass is not None and prep_pass.intersects(link) and link.intersection(passages).length > 1.0:
                    continue
                joined = True
                break
            if joined:
                dsu.union(i, j)
                near_pairs.append((i, j))

    comps: Dict[int, List[int]] = defaultdict(list)
    for k in range(n):
        comps[dsu.find(k)].append(k)

    # Tiny groups (fewer than three rows cannot be a vineyard block) join the
    # nearest real block within max_pitch_m; otherwise they are noise and dropped
    big = {root for root, m in comps.items() if len(m) >= min_block_rows}
    dropped_rows = set()
    for root, members in list(comps.items()):
        if root in big:
            continue
        best = None
        geom = unary_union([lines[k] for k in members])
        for k in tree.query(geom.buffer(max_pitch_m)):
            k = int(k)
            rk = dsu.find(k)
            if rk in big:
                d = geom.distance(lines[k])
                if best is None or d < best[0]:
                    best = (d, rk)
        if best is not None:
            comps[best[1]].extend(members)
        else:
            dropped_rows.update(members)
        del comps[root]

    # Name blocks after the file1 label carried by most of their row length
    named = []
    for root, members in comps.items():
        votes = Counter()
        for k in members:
            votes[rows[k].vineyard_id] += rows[k].length_m
        total = sum(rows[k].length_m for k in members)
        named.append((total, votes.most_common(1)[0][0], members))
    named.sort(key=lambda x: -x[0])

    used = set()
    taken_numbers = set()
    for _, label, _ in named:
        if label[1:].isdigit():
            taken_numbers.add(int(label[1:]))
    next_no = max(taken_numbers | {0}) + 1
    origin: Dict[str, str] = {}
    for _, label, members in named:
        new_id = label
        if label in used:
            new_id = f"V{next_no:02d}"
            next_no += 1
        used.add(new_id)
        origin[new_id] = label
        for k in members:
            rows[k].vineyard_id = new_id
    for k in dropped_rows:
        rows[k].vineyard_id = ""
    return origin
