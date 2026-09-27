"""
Global row stitching module for Vineyard AI Field Challenge (EPSG:32635).
Solves cross-tile physical row continuity by:
- Grouping collinear row segments (matching perpendicular offset < 0.4m)
- Sorting physical rows across each block to assign persistent IDs (e.g. V01-R01, V01-R02)
- Ensuring segments of the same physical row across tile boundaries receive identical IDs.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import List, Dict, Tuple, Any, Optional, Set
import numpy as np

from src.spatial.grid import (
    parse_tile_indices,
    tile_upper_left,
    TILE_SIZE_M,
    GRID_ORIGIN_X,
    GRID_ORIGIN_Y,
)


@dataclass
class LocalRowSegment:
    tile_name: str
    local_points: List[Tuple[float, float]]  # (px, py)
    global_points: List[Tuple[float, float]] # (Easting, Northing)
    block_id: str
    row_structure: str = "regular"  # evaluated per-tile
    assigned_row_id: str = ""


class DSU:
    """Disjoint Set Union (Union-Find) with path compression and rank optimization."""
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, i: int) -> int:
        if self.parent[i] == i:
            return i
        self.parent[i] = self.find(self.parent[i])
        return self.parent[i]

    def union(self, i: int, j: int) -> bool:
        root_i = self.find(i)
        root_j = self.find(j)
        if root_i != root_j:
            if self.rank[root_i] < self.rank[root_j]:
                self.parent[root_i] = root_j
            elif self.rank[root_i] > self.rank[root_j]:
                self.parent[root_j] = root_i
            else:
                self.parent[root_j] = root_i
                self.rank[root_i] += 1
            return True
        return False


class GlobalRowStitcher:
    """Stitches row segments across tiles within each block."""

    COLLINEAR_OFFSET_TOLERANCE_M = 0.80  # 0.8m collinear tolerance across block
    BOUNDARY_OFFSET_TOLERANCE_M = 1.40   # 1.40m normal boundary tolerance (strictly below 2.0m inter-row half-pitch)

    def __init__(
        self,
        offset_tolerance_m: float = 0.80,
        boundary_tolerance_m: float = 1.40,
    ):
        self.offset_tolerance_m = offset_tolerance_m
        self.boundary_tolerance_m = boundary_tolerance_m

    def stitch_block_rows(
        self,
        block_id: str,
        segments: List[LocalRowSegment],
    ) -> List[LocalRowSegment]:
        """
        Takes all row segments belonging to a single block across all tiles,
        determines the block's row orientation, performs robust cross-tile
        boundary intersection matching, groups collinear lines along unified
        infinite line parameter c = -E*sin(theta) + N*cos(theta), assigns
        persistent sequential row IDs (V01-R01, V01-R02...), and unifies
        segments on the same tile belonging to the same physical row (Rule 3).
        """
        if not segments:
            return []
        if len(segments) == 1:
            segments[0].assigned_row_id = f"{block_id}-R01"
            return segments

        n_segs = len(segments)

        # 1. Centroid of all points in the block to avoid UTM huge-coordinate leverage
        all_pts = []
        for seg in segments:
            all_pts.extend(seg.global_points)
        all_pts_arr = np.array(all_pts)
        centroid = np.mean(all_pts_arr, axis=0)  # (E_center, N_center)

        # 2. Determine dominant block azimuth using length-weighted circular statistics
        angles_deg = []
        weights = []
        for seg in segments:
            p1 = np.array(seg.global_points[0])
            p2 = np.array(seg.global_points[-1])
            diff = p2 - p1
            length = np.linalg.norm(diff)
            if length > 0.5:
                ang = np.degrees(np.arctan2(diff[1], diff[0])) % 180.0
                angles_deg.append(ang)
                weights.append(length)

        if angles_deg:
            # Find coarse modal peak to reject potential cross-line outliers
            hist, bin_edges = np.histogram(angles_deg, bins=36, range=(0, 180), weights=weights)
            peak_bin = np.argmax(hist)
            mode_angle = 0.5 * (bin_edges[peak_bin] + bin_edges[peak_bin + 1])

            # Inliers within 25 degrees of mode (accounting for 180 deg periodicity)
            inlier_angles = []
            inlier_weights = []
            for ang, w in zip(angles_deg, weights):
                ang_dist = min(abs(ang - mode_angle), 180.0 - abs(ang - mode_angle))
                if ang_dist <= 25.0:
                    inlier_angles.append(ang)
                    inlier_weights.append(w)

            if inlier_angles:
                # Circular weighted mean on inliers (modulo 180 -> double angle method)
                rad2 = np.radians(2.0 * np.array(inlier_angles))
                w_arr = np.array(inlier_weights)
                s = np.sum(w_arr * np.sin(rad2))
                c = np.sum(w_arr * np.cos(rad2))
                mean_2rad = np.arctan2(s, c)
                dominant_ang_deg = (np.degrees(mean_2rad) / 2.0) % 180.0
            else:
                dominant_ang_deg = mode_angle
        else:
            dominant_ang_deg = 50.0  # default vineyard orientation in Sireț3

        dominant_rad = np.radians(dominant_ang_deg)
        # Unified block normal vector across rows and primary vector along rows
        normal_vec = np.array([-np.sin(dominant_rad), np.cos(dominant_rad)])
        prim_vec = np.array([np.cos(dominant_rad), np.sin(dominant_rad)])

        # 3. Calculate infinite line parameter c = (P_mid - centroid) . normal
        # and span [s_min, s_max] along prim_vec for each segment
        seg_c = []
        seg_spans = []
        seg_lengths = []
        seg_dirs = []
        for seg in segments:
            pts = np.array(seg.global_points)
            diff = pts[-1] - pts[0]
            length = max(0.1, float(np.linalg.norm(diff)))
            seg_lengths.append(length)
            seg_dirs.append(diff / length)
            mid = np.mean(pts, axis=0) - centroid
            c_val = float(np.dot(mid, normal_vec))
            seg_c.append(c_val)
            s_projs = [float(np.dot(p - centroid, prim_vec)) for p in pts]
            seg_spans.append((min(s_projs), max(s_projs)))

        # 4. Adjacent tile boundary matching (Cross-Tile Continuity)
        dsu = DSU(n_segs)
        tile_indices: Dict[str, Optional[Tuple[int, int]]] = {}
        for seg in segments:
            if seg.tile_name not in tile_indices:
                try:
                    tile_indices[seg.tile_name] = parse_tile_indices(seg.tile_name)
                except Exception:
                    tile_indices[seg.tile_name] = None

        # Check candidate boundary crossings between segments on adjacent tiles
        boundary_candidates: Dict[Tuple[str, str], List[Tuple[float, int, int]]] = defaultdict(list)
        for i in range(n_segs):
            t_i = segments[i].tile_name
            idx_i = tile_indices.get(t_i)
            if idx_i is None:
                continue
            p_i1 = np.array(segments[i].global_points[0])
            p_i2 = np.array(segments[i].global_points[-1])
            
            for j in range(i + 1, n_segs):
                t_j = segments[j].tile_name
                if t_i == t_j:
                    continue
                idx_j = tile_indices.get(t_j)
                if idx_j is None:
                    continue

                r_i, c_i = idx_i
                r_j, c_j = idx_j
                is_ew = (r_i == r_j and abs(c_i - c_j) == 1)
                is_ns = (c_i == c_j and abs(r_i - r_j) == 1)
                if not (is_ew or is_ns):
                    continue

                # Segments crossing a boundary must have compatible orientation (within ~32 degrees, cos >= 0.85)
                cos_sim = abs(float(np.dot(seg_dirs[i], seg_dirs[j])))
                if cos_sim < 0.85:
                    continue

                # Local pair direction and normal
                v_pair = seg_dirs[i] + (seg_dirs[j] if np.dot(seg_dirs[i], seg_dirs[j]) > 0 else -seg_dirs[j])
                v_pair = v_pair / np.linalg.norm(v_pair)
                n_pair = np.array([-v_pair[1], v_pair[0]])

                p_j1 = np.array(segments[j].global_points[0])
                p_j2 = np.array(segments[j].global_points[-1])

                matched = False
                match_dist = float("inf")

                if is_ew:
                    west_c = min(c_i, c_j)
                    x_bnd = GRID_ORIGIN_X + (west_c + 1) * TILE_SIZE_M
                    y_top = GRID_ORIGIN_Y - r_i * TILE_SIZE_M
                    y_bot = GRID_ORIGIN_Y - (r_i + 1) * TILE_SIZE_M

                    d_i1 = abs(p_i1[0] - x_bnd)
                    d_i2 = abs(p_i2[0] - x_bnd)
                    pt_i = p_i1 if d_i1 <= d_i2 else p_i2
                    d_i = min(d_i1, d_i2)

                    d_j1 = abs(p_j1[0] - x_bnd)
                    d_j2 = abs(p_j2[0] - x_bnd)
                    pt_j = p_j1 if d_j1 <= d_j2 else p_j2
                    d_j = min(d_j1, d_j2)

                    # Endpoints within 8.0m of boundary edge
                    if d_i <= 8.0 and d_j <= 8.0:
                        if (y_bot - 4.0 <= pt_i[1] <= y_top + 4.0) and (y_bot - 4.0 <= pt_j[1] <= y_top + 4.0):
                            nd_block = abs(float(np.dot(pt_j - pt_i, normal_vec)))
                            nd_pair = abs(float(np.dot(pt_j - pt_i, n_pair)))
                            norm_dist = min(nd_block, nd_pair)
                            along_dist = abs(float(np.dot(pt_j - pt_i, v_pair)))
                            if norm_dist <= self.boundary_tolerance_m and along_dist <= 18.0:
                                matched = True
                                match_dist = norm_dist

                elif is_ns:
                    north_r = min(r_i, r_j)
                    y_bnd = GRID_ORIGIN_Y - (north_r + 1) * TILE_SIZE_M
                    x_left = GRID_ORIGIN_X + c_i * TILE_SIZE_M
                    x_right = GRID_ORIGIN_X + (c_i + 1) * TILE_SIZE_M

                    d_i1 = abs(p_i1[1] - y_bnd)
                    d_i2 = abs(p_i2[1] - y_bnd)
                    pt_i = p_i1 if d_i1 <= d_i2 else p_i2
                    d_i = min(d_i1, d_i2)

                    d_j1 = abs(p_j1[1] - y_bnd)
                    d_j2 = abs(p_j2[1] - y_bnd)
                    pt_j = p_j1 if d_j1 <= d_j2 else p_j2
                    d_j = min(d_j1, d_j2)

                    if d_i <= 8.0 and d_j <= 8.0:
                        if (x_left - 4.0 <= pt_i[0] <= x_right + 4.0) and (x_left - 4.0 <= pt_j[0] <= x_right + 4.0):
                            nd_block = abs(float(np.dot(pt_j - pt_i, normal_vec)))
                            nd_pair = abs(float(np.dot(pt_j - pt_i, n_pair)))
                            norm_dist = min(nd_block, nd_pair)
                            along_dist = abs(float(np.dot(pt_j - pt_i, v_pair)))
                            if norm_dist <= self.boundary_tolerance_m and along_dist <= 18.0:
                                matched = True
                                match_dist = norm_dist

                # Direct endpoint distance fallback if both endpoints are close to the boundary edge
                min_end_dist = min(
                    np.linalg.norm(p_i1 - p_j1),
                    np.linalg.norm(p_i1 - p_j2),
                    np.linalg.norm(p_i2 - p_j1),
                    np.linalg.norm(p_i2 - p_j2),
                )
                if not matched and min_end_dist <= self.boundary_tolerance_m:
                    if (is_ew and d_i <= 4.0 and d_j <= 4.0) or (is_ns and d_i <= 4.0 and d_j <= 4.0):
                        matched = True
                        match_dist = min_end_dist

                if matched:
                    bnd_key = tuple(sorted([t_i, t_j]))
                    boundary_candidates[bnd_key].append((match_dist, i, j))

        # Greedy 1-to-1 matching per adjacent boundary pair (single matched_indices set prevents 1-to-many bugs)
        for bnd_key, cands in boundary_candidates.items():
            cands.sort(key=lambda x: x[0])
            matched_indices: Set[int] = set()
            for dist, i, j in cands:
                if i not in matched_indices and j not in matched_indices:
                    dsu.union(i, j)
                    matched_indices.add(i)
                    matched_indices.add(j)

        # 5. Collinear clustering across the block for groups
        groups: Dict[int, List[int]] = defaultdict(list)
        for i in range(n_segs):
            groups[dsu.find(i)].append(i)

        class Cluster:
            def __init__(self, grp_indices: List[int]):
                self.seg_indices = list(grp_indices)
                weights = [seg_lengths[idx] for idx in grp_indices]
                w_sum = sum(weights)
                self.total_length = w_sum
                self.c_val = sum(seg_c[idx] * seg_lengths[idx] for idx in grp_indices) / (w_sum if w_sum > 0 else 1.0)
                self.spans = [seg_spans[idx] for idx in grp_indices]

            def can_merge(self, other: "Cluster", tol: float) -> bool:
                if abs(self.c_val - other.c_val) > tol:
                    return False
                for s1_min, s1_max in self.spans:
                    for s2_min, s2_max in other.spans:
                        ov = max(0.0, min(s1_max, s2_max) - max(s1_min, s2_min))
                        if ov > 2.0:  # overlapping along row direction indicates parallel distinct rows
                            return False
                return True

            def merge(self, other: "Cluster") -> None:
                w1 = self.total_length
                w2 = other.total_length
                self.c_val = (self.c_val * w1 + other.c_val * w2) / (w1 + w2 if (w1 + w2) > 0 else 1.0)
                self.total_length = w1 + w2
                self.seg_indices.extend(other.seg_indices)
                self.spans.extend(other.spans)

        clusters = [Cluster(grp) for grp in groups.values()]

        # Greedily merge closest compatible clusters (smallest |Delta c|)
        while True:
            best_pair = None
            best_diff = float("inf")
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    if clusters[i].can_merge(clusters[j], self.offset_tolerance_m):
                        diff = abs(clusters[i].c_val - clusters[j].c_val)
                        if diff < best_diff:
                            best_diff = diff
                            best_pair = (i, j)
            if best_pair is None:
                break
            i, j = best_pair
            clusters[i].merge(clusters[j])
            clusters.pop(j)

        # 6. Sort clusters by their mean line parameter c across the block
        clusters.sort(key=lambda cl: cl.c_val)

        # 7. Number rows sequentially across the block: V01-R01, V01-R02...
        for row_idx, cl in enumerate(clusters, start=1):
            row_id = f"{block_id}-R{row_idx:02d}"
            for s_idx in cl.seg_indices:
                segments[s_idx].assigned_row_id = row_id

        # 8. Unify segments on the same tile belonging to the same physical row (Rule 3)
        final_segments: List[LocalRowSegment] = []
        for cl in clusters:
            tile_segs: Dict[str, List[LocalRowSegment]] = defaultdict(list)
            for seg_idx in cl.seg_indices:
                s = segments[seg_idx]
                tile_segs[s.tile_name].append(s)

            for tname, s_list in tile_segs.items():
                if len(s_list) == 1:
                    final_segments.append(s_list[0])
                else:
                    all_local = []
                    all_global = []
                    has_disrupt = any(s.row_structure == "disrupted" for s in s_list)
                    for s in s_list:
                        all_local.extend(s.local_points)
                        all_global.extend(s.global_points)

                    # Project in global UTM coordinates where prim_vec is defined
                    s_projs = [float(np.dot(np.array(p) - centroid, prim_vec)) for p in all_global]
                    min_idx = int(np.argmin(s_projs))
                    max_idx = int(np.argmax(s_projs))

                    # Check if gap between segments is >= 5.0m in UTM coordinates
                    sorted_global = [all_global[i] for i in np.argsort(s_projs)]
                    dists = [
                        np.linalg.norm(np.array(sorted_global[i + 1]) - np.array(sorted_global[i]))
                        for i in range(len(sorted_global) - 1)
                    ]
                    if any(d >= 5.0 for d in dists):
                        has_disrupt = True

                    merged_seg = LocalRowSegment(
                        tile_name=tname,
                        local_points=[all_local[min_idx], all_local[max_idx]],
                        global_points=[all_global[min_idx], all_global[max_idx]],
                        block_id=block_id,
                        row_structure="disrupted" if has_disrupt else "regular",
                        assigned_row_id=s_list[0].assigned_row_id,
                    )
                    final_segments.append(merged_seg)

        return final_segments
