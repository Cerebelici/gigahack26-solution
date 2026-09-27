"""
Global row stitching module for Vineyard AI Field Challenge (EPSG:32635).
Solves cross-tile physical row continuity by:
- Grouping collinear row segments (matching perpendicular offset < 0.4m)
- Sorting physical rows across each block to assign persistent IDs (e.g. V01-R01, V01-R02)
- Ensuring segments of the same physical row across tile boundaries receive identical IDs.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import List, Dict, Tuple, Any, Optional
import numpy as np


@dataclass
class LocalRowSegment:
    tile_name: str
    local_points: List[Tuple[float, float]]  # (px, py)
    global_points: List[Tuple[float, float]] # (Easting, Northing)
    block_id: str
    row_structure: str = "regular"  # evaluated per-tile
    assigned_row_id: str = ""


class GlobalRowStitcher:
    """Stitches row segments across tiles within each block."""

    COLLINEAR_OFFSET_TOLERANCE_M = 0.40  # 0.4m axis tolerance from scoring rules

    def __init__(self, offset_tolerance_m: float = 0.40):
        self.offset_tolerance_m = offset_tolerance_m

    def stitch_block_rows(
        self,
        block_id: str,
        segments: List[LocalRowSegment],
    ) -> List[LocalRowSegment]:
        """
        Takes all row segments belonging to a single block across all tiles,
        determines the block's row orientation, groups collinear lines,
        assigns persistent sequential row IDs (V01-R01, V01-R02...),
        and returns the updated segments.
        Ensures at most one polyline per physical row per tile (Rule 3).
        """
        if not segments:
            return []

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
        # Normal vector perpendicular to the row direction
        normal_vec = np.array([-np.sin(dominant_rad), np.cos(dominant_rad)])

        # 3. Calculate perpendicular distance offset for each segment: d = (P - centroid) . normal
        segment_offsets = []
        for seg in segments:
            pts = np.array(seg.global_points)
            mid = np.mean(pts, axis=0) - centroid
            offset = float(np.dot(mid, normal_vec))
            segment_offsets.append(offset)

        # 4. Sort segments by perpendicular offset
        sorted_indices = list(np.argsort(segment_offsets))
        
        # 5. Cluster collinear segments into unique physical rows
        physical_rows: List[List[int]] = []  # list of list of segment indices
        current_cluster: List[int] = [sorted_indices[0]]
        cluster_offsets: List[float] = [segment_offsets[sorted_indices[0]]]

        for idx in sorted_indices[1:]:
            offset = segment_offsets[idx]
            cluster_mean_offset = np.mean(cluster_offsets)
            
            # If offset is within tolerance of current row line, merge into same physical row
            if abs(offset - cluster_mean_offset) <= self.offset_tolerance_m:
                current_cluster.append(idx)
                cluster_offsets.append(offset)
            else:
                physical_rows.append(current_cluster)
                current_cluster = [idx]
                cluster_offsets = [offset]

        if current_cluster:
            physical_rows.append(current_cluster)

        # 6. Sort clusters by their mean offset across the block so row numbers increase monotonically
        cluster_order = np.argsort([np.mean([segment_offsets[i] for i in cluster]) for cluster in physical_rows])

        # 7. Number rows sequentially across the block: V01-R01, V01-R02...
        for row_idx, cluster_idx in enumerate(cluster_order, start=1):
            cluster = physical_rows[cluster_idx]
            row_id = f"{block_id}-R{row_idx:02d}"
            for seg_idx in cluster:
                segments[seg_idx].assigned_row_id = row_id

        # 8. Unify segments on the same tile belonging to the same physical row (Rule 3)
        final_segments: List[LocalRowSegment] = []
        prim_vec = np.array([-normal_vec[1], normal_vec[0]])
        for cluster_idx in cluster_order:
            cluster = physical_rows[cluster_idx]
            tile_segs: Dict[str, List[LocalRowSegment]] = defaultdict(list)
            for seg_idx in cluster:
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
                    s_projs = [float(np.dot(np.array(p), prim_vec)) for p in all_global]
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
