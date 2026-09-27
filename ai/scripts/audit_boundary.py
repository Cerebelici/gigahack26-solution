"""
Automated Boundary Crossing Audit across challenge tiles in CVAT XML.
Verifies that all collinear row segments crossing shared tile boundaries
(East-West or North-South) have identical persistent row IDs (0 off-by-1 mismatches).
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict
import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.spatial.grid import (
    parse_tile_indices,
    pixel_to_map,
    TILE_SIZE_M,
    GRID_ORIGIN_X,
    GRID_ORIGIN_Y,
)


def audit_boundary_crossings(
    xml_path: str = "annotations_challenge.xml",
    boundary_tolerance_m: float = 1.40,
    along_tolerance_m: float = 18.0,
    edge_window_m: float = 8.0,
    cos_sim_threshold: float = 0.85,
) -> int:
    xml_file = Path(xml_path)
    if not xml_file.exists():
        raise FileNotFoundError(f"Annotations XML file not found: {xml_file}")

    print("=" * 70)
    print(f"Auditing Cross-Tile Boundary Continuity: {xml_file.name}")
    print(f"Settings: norm_tol={boundary_tolerance_m}m, along_tol={along_tolerance_m}m, window={edge_window_m}m")
    print("=" * 70)

    tree = ET.parse(xml_file)
    root = tree.getroot()

    tile_rows = defaultdict(list)
    total_rows = 0

    for img in root.findall("image"):
        tname = img.get("name")
        try:
            r, c = parse_tile_indices(tname)
        except Exception:
            continue
        for poly in img.findall("polyline"):
            if poly.get("label") != "row":
                continue
            rid = ""
            vid = ""
            for a in poly.findall("attribute"):
                if a.get("name") == "row_id":
                    rid = a.text
                elif a.get("name") == "vineyard_id":
                    vid = a.text
            b_id = vid or (rid.split("-")[0] if "-" in rid else "")
            if not b_id:
                continue

            pts_str = poly.get("points")
            local_pts = [tuple(map(float, pt.split(","))) for pt in pts_str.split(";") if "," in pt]
            if len(local_pts) < 2:
                continue
            global_pts = [pixel_to_map(r, c, px, py) for px, py in local_pts]
            p1 = np.array(global_pts[0])
            p2 = np.array(global_pts[-1])
            diff = p2 - p1
            length = float(np.linalg.norm(diff))
            if length < 0.1:
                continue
            direction = diff / length
            tile_rows[(r, c)].append({
                "tile": tname,
                "row_id": rid,
                "block_id": b_id,
                "p1": p1,
                "p2": p2,
                "dir": direction,
                "length": length,
            })
            total_rows += 1

    print(f"Total tiles with rows: {len(tile_rows)}, Total rows loaded: {total_rows}")

    # Compute dominant block normal vectors using length-weighted circular statistics
    block_dirs = {}
    block_segs = defaultdict(list)
    for segs in tile_rows.values():
        for s in segs:
            block_segs[s["block_id"]].append(s)

    for b_id, segs in block_segs.items():
        angles = []
        weights = []
        for s in segs:
            if s["length"] > 0.5:
                ang = np.degrees(np.arctan2(s["dir"][1], s["dir"][0])) % 180.0
                angles.append(ang)
                weights.append(s["length"])
        if angles:
            hist, bin_edges = np.histogram(angles, bins=36, range=(0, 180), weights=weights)
            peak_bin = np.argmax(hist)
            mode_angle = 0.5 * (bin_edges[peak_bin] + bin_edges[peak_bin + 1])
            inlier_angles = []
            inlier_weights = []
            for ang, w in zip(angles, weights):
                ang_dist = min(abs(ang - mode_angle), 180.0 - abs(ang - mode_angle))
                if ang_dist <= 25.0:
                    inlier_angles.append(ang)
                    inlier_weights.append(w)
            if inlier_angles:
                rad2 = np.radians(2.0 * np.array(inlier_angles))
                w_arr = np.array(inlier_weights)
                mean_2rad = np.arctan2(np.sum(w_arr * np.sin(rad2)), np.sum(w_arr * np.cos(rad2)))
                dominant_ang_deg = (np.degrees(mean_2rad) / 2.0) % 180.0
            else:
                dominant_ang_deg = mode_angle
        else:
            dominant_ang_deg = 50.0
        m_rad = np.radians(dominant_ang_deg)
        block_dirs[b_id] = np.array([-np.sin(m_rad), np.cos(m_rad)])

    # Audit all adjacent tile pairs
    adjacent_pairs = []
    for (r, c) in list(tile_rows.keys()):
        if (r, c + 1) in tile_rows:
            adjacent_pairs.append(((r, c), (r, c + 1), "EW"))
        if (r + 1, c) in tile_rows:
            adjacent_pairs.append(((r, c), (r + 1, c), "NS"))

    total_matches = 0
    total_mismatches = 0
    mismatch_details = []

    for idx_a, idx_b, orient in adjacent_pairs:
        segs_a = tile_rows[idx_a]
        segs_b = tile_rows[idx_b]
        if orient == "EW":
            x_bnd = GRID_ORIGIN_X + (idx_a[1] + 1) * TILE_SIZE_M
            y_top = GRID_ORIGIN_Y - idx_a[0] * TILE_SIZE_M
            y_bot = GRID_ORIGIN_Y - (idx_a[0] + 1) * TILE_SIZE_M
        else:
            y_bnd = GRID_ORIGIN_Y - (idx_a[0] + 1) * TILE_SIZE_M
            x_left = GRID_ORIGIN_X + idx_a[1] * TILE_SIZE_M
            x_right = GRID_ORIGIN_X + (idx_a[1] + 1) * TILE_SIZE_M

        bnd_cands = []
        for i, sa in enumerate(segs_a):
            b_id = sa["block_id"]
            if b_id not in block_dirs:
                continue
            normal = block_dirs[b_id]

            if orient == "EW":
                d_a1 = abs(sa["p1"][0] - x_bnd)
                d_a2 = abs(sa["p2"][0] - x_bnd)
                pt_a = sa["p1"] if d_a1 < d_a2 else sa["p2"]
                d_a = min(d_a1, d_a2)
            else:
                d_a1 = abs(sa["p1"][1] - y_bnd)
                d_a2 = abs(sa["p2"][1] - y_bnd)
                pt_a = sa["p1"] if d_a1 < d_a2 else sa["p2"]
                d_a = min(d_a1, d_a2)

            if d_a > edge_window_m:
                continue

            for j, sb in enumerate(segs_b):
                if sb["block_id"] != b_id:
                    continue
                cos_sim = abs(float(np.dot(sa["dir"], sb["dir"])))
                if cos_sim < cos_sim_threshold:
                    continue

                v_pair = sa["dir"] + (sb["dir"] if np.dot(sa["dir"], sb["dir"]) > 0 else -sb["dir"])
                v_pair = v_pair / np.linalg.norm(v_pair)
                n_pair = np.array([-v_pair[1], v_pair[0]])

                if orient == "EW":
                    d_b1 = abs(sb["p1"][0] - x_bnd)
                    d_b2 = abs(sb["p2"][0] - x_bnd)
                    pt_b = sb["p1"] if d_b1 < d_b2 else sb["p2"]
                    d_b = min(d_b1, d_b2)
                    if d_b > edge_window_m:
                        continue
                    if not (y_bot - 4.0 <= pt_a[1] <= y_top + 4.0 and y_bot - 4.0 <= pt_b[1] <= y_top + 4.0):
                        continue
                else:
                    d_b1 = abs(sb["p1"][1] - y_bnd)
                    d_b2 = abs(sb["p2"][1] - y_bnd)
                    pt_b = sb["p1"] if d_b1 < d_b2 else sb["p2"]
                    d_b = min(d_b1, d_b2)
                    if d_b > edge_window_m:
                        continue
                    if not (x_left - 4.0 <= pt_a[0] <= x_right + 4.0 and x_left - 4.0 <= pt_b[0] <= x_right + 4.0):
                        continue

                nd_block = abs(float(np.dot(pt_b - pt_a, normal)))
                nd_pair = abs(float(np.dot(pt_b - pt_a, n_pair)))
                norm_dist = min(nd_block, nd_pair)
                along_dist = abs(float(np.dot(pt_b - pt_a, v_pair)))

                if norm_dist <= boundary_tolerance_m and along_dist <= along_tolerance_m:
                    bnd_cands.append((norm_dist, i, j, sa, sb, along_dist))

        # Greedy 1-to-1 matching per adjacent boundary pair
        bnd_cands.sort(key=lambda x: x[0])
        matched_a = set()
        matched_b = set()
        for norm_dist, i, j, sa, sb, along_dist in bnd_cands:
            if i not in matched_a and j not in matched_b:
                matched_a.add(i)
                matched_b.add(j)
                if sa["row_id"] == sb["row_id"]:
                    total_matches += 1
                else:
                    total_mismatches += 1
                    mismatch_details.append((sa, sb, norm_dist, along_dist))

    total_crossings = total_matches + total_mismatches
    print("\n--- Cross-Tile Boundary Continuity Audit Results ---")
    print(f"Total Evaluated Boundary Crossings: {total_crossings}")
    print(f"Matching Row IDs:                   {total_matches} ({(total_matches/total_crossings*100) if total_crossings else 100:.2f}%)")
    print(f"Mismatching Row IDs:                {total_mismatches}")

    if total_mismatches > 0:
        print("\n[FAIL] Found Mismatching Boundary Crossings:")
        for sa, sb, ndist, adist in mismatch_details[:20]:
            print(f"  {sa['tile']} ({sa['row_id']}) vs {sb['tile']} ({sb['row_id']}) | norm_dist: {ndist:.2f}m | along: {adist:.2f}m")
        return total_mismatches
    else:
        print("\n[SUCCESS] 100% of adjacent boundary crossings have matching row IDs with 0 mismatches!")
        return 0


if __name__ == "__main__":
    xml_path = sys.argv[1] if len(sys.argv) > 1 else "annotations_challenge.xml"
    sys.exit(audit_boundary_crossings(xml_path))
