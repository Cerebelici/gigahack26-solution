"""
Inter-row polygon derivation and ground cover classification.
Generates straight-edged quadrilateral corridors between adjacent vine rows.
Each row is bounded from both sides by straight margins of the interrow space,
conforming strictly to the challenge specification and ground truth topology.
"""

from typing import List, Tuple, Dict, Any, Optional
import cv2
import numpy as np
from shapely.geometry import box, Polygon, MultiPolygon
from shapely.validation import make_valid
from src.export.cvat_writer import InterRowArea, VineyardCanopy
from src.spatial.row_extractor import is_nodata_pixel, get_line_tile_s_bounds


def classify_interrow_cover(
    poly_coords: List[Tuple[float, float]],
    image_rgb: Optional[np.ndarray] = None,
) -> str:
    """
    Classify ground cover inside polygon based on Excess Green Index (2G - R - B):
    - bare_soil (< 25% vegetation)
    - mixed (25% - 75% vegetation)
    - vegetation (> 75% vegetation)
    - unassessable (if obscured or cannot be evaluated)
    """
    if image_rgb is None:
        return "bare_soil"

    try:
        minx = int(np.floor(min(p[0] for p in poly_coords)))
        miny = int(np.floor(min(p[1] for p in poly_coords)))
        maxx = int(np.ceil(max(p[0] for p in poly_coords)))
        maxy = int(np.ceil(max(p[1] for p in poly_coords)))

        h, w = image_rgb.shape[:2]
        minx, miny = max(0, minx), max(0, miny)
        maxx, maxy = min(w, maxx), min(h, maxy)

        if maxx <= minx or maxy <= miny:
            return "bare_soil"

        crop = image_rgb[miny:maxy, minx:maxx].astype(np.float32)
        r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]

        # Excess Green Index: 2G - R - B
        exg = 2.0 * g - r - b
        veg_mask = exg > 20.0

        # Mask only the interior of the polygon
        mask = np.zeros((maxy - miny, maxx - minx), dtype=np.uint8)
        local_pts = np.array([[p[0] - minx, p[1] - miny] for p in poly_coords], dtype=np.int32)
        cv2.fillPoly(mask, [local_pts], 1)

        inside = mask > 0
        if np.sum(inside) < 25:
            return "bare_soil"

        veg_ratio = float(np.mean(veg_mask[inside]))
        if veg_ratio < 0.25:
            return "bare_soil"
        elif veg_ratio > 0.75:
            return "vegetation"
        else:
            return "mixed"
    except Exception:
        return "bare_soil"


def get_valid_image_polygon(image_rgb: Optional[np.ndarray]) -> Optional[Polygon]:
    """
    Extract the polygon boundary of valid imagery on an edge tile.
    Returns None if tile has no significant black/nodata borders (> 98% non-black).
    """
    if image_rgb is None:
        return None
    valid_mask = ((image_rgb > 15).any(axis=2)).astype(np.uint8) * 255
    if float(valid_mask.mean()) > 250.0:  # > 98% valid pixels, no black borders
        return None
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (35, 35))
    closed = cv2.morphologyEx(valid_mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    if len(largest) < 3:
        return None
    poly = Polygon(largest.reshape(-1, 2))
    if not poly.is_valid:
        poly = make_valid(poly)
    return poly.simplify(2.0, preserve_topology=True)


def derive_interrow_quadrilaterals(
    rows_metadata: List[Dict[str, Any]],
    normal_dir: np.ndarray,
    primary_dir: np.ndarray,
    vineyard_id: str = "V01",
    image_rgb: Optional[np.ndarray] = None,
    margin_px: float = 12.0,
    tile_width: float = 2048.0,
    tile_height: float = 2048.0,
    min_area_px: float = 100.0,
) -> List[InterRowArea]:
    """
    Derive quadrilateral inter-row area polygons between adjacent pairs of rows.
    Each row is bounded on both sides by straight margins of the interrow space at distance margin_px.
    Short sides stop where the bounding rows end: if one row is shorter, end at the shorter one.
    Exterior land, roads, and black nodata borders are strictly excluded.
    """
    if len(rows_metadata) < 2:
        return []

    # Sort rows by normal projection
    sorted_rows = sorted(rows_metadata, key=lambda r: r["c_val"])
    tile_b = box(0.0, 0.0, tile_width, tile_height)

    nx, ny = float(normal_dir[0]), float(normal_dir[1])
    px, py = float(primary_dir[0]), float(primary_dir[1])

    interrows: List[InterRowArea] = []

    for i in range(len(sorted_rows) - 1):
        row_A = sorted_rows[i]
        row_B = sorted_rows[i + 1]

        c_i = row_A["c_val"]
        c_next = row_B["c_val"]
        spacing = abs(c_next - c_i)

        if spacing < 25.0:
            continue

        effective_margin = min(margin_px, 0.25 * spacing)
        c_low = min(c_i, c_next) + effective_margin
        c_high = max(c_i, c_next) - effective_margin

        if c_high <= c_low:
            continue

        # Get extent along primary_dir for row_A
        if "s_min" in row_A and "s_max" in row_A:
            s_min_A, s_max_A = float(row_A["s_min"]), float(row_A["s_max"])
        else:
            s_projs = [float(np.dot(pt, primary_dir)) for pt in row_A["points"]]
            s_min_A, s_max_A = min(s_projs), max(s_projs)

        # Get extent along primary_dir for row_B
        if "s_min" in row_B and "s_max" in row_B:
            s_min_B, s_max_B = float(row_B["s_min"]), float(row_B["s_max"])
        else:
            s_projs = [float(np.dot(pt, primary_dir)) for pt in row_B["points"]]
            s_min_B, s_max_B = min(s_projs), max(s_projs)

        # Short sides stop where the rows end: end at the shorter row
        s_start = max(s_min_A, s_min_B)
        s_end = min(s_max_A, s_max_B)

        # Tile boundary clamping for both c_low and c_high margins
        b_low = get_line_tile_s_bounds(c_low, normal_dir, primary_dir, tile_width, tile_height)
        b_high = get_line_tile_s_bounds(c_high, normal_dir, primary_dir, tile_width, tile_height)
        if b_low is None or b_high is None:
            continue
        s_tile_min = max(b_low[0], b_high[0])
        s_tile_max = min(b_low[1], b_high[1])

        s_start = max(s_start, s_tile_min)
        s_end = min(s_end, s_tile_max)

        # Ensure corridor short sides do not cross into black/nodata borders
        if image_rgb is not None:
            def is_slice_valid(s_val: float) -> bool:
                for c in np.linspace(c_low, c_high, 5):
                    pt = c * np.array([nx, ny]) + s_val * np.array([px, py])
                    if is_nodata_pixel(image_rgb, pt[0], pt[1]):
                        return False
                return True

            step = 2.0
            while s_start + step <= s_end and not is_slice_valid(s_start):
                s_start += step
            while s_end - step >= s_start and not is_slice_valid(s_end):
                s_end -= step

        # Final clamp to tile bounds
        s_start = max(s_start, s_tile_min)
        s_end = min(s_end, s_tile_max)

        if s_end - s_start < 25.0:
            continue

        # Build clean quadrilateral strip between c_low and c_high from s_start to s_end
        p1 = c_low * np.array([nx, ny]) + s_start * np.array([px, py])
        p2 = c_low * np.array([nx, ny]) + s_end * np.array([px, py])
        p3 = c_high * np.array([nx, ny]) + s_end * np.array([px, py])
        p4 = c_high * np.array([nx, ny]) + s_start * np.array([px, py])

        # Clamp all four corner points strictly to tile bounding box [0, tile_width] x [0, tile_height]
        raw_pts = [
            (
                round(float(np.clip(p[0], 0.0, tile_width)), 1),
                round(float(np.clip(p[1], 0.0, tile_height)), 1),
            )
            for p in [p1, p2, p3, p4]
        ]

        # Eliminate duplicate consecutive vertices if any
        dedup = [raw_pts[0]]
        for pt in raw_pts[1:]:
            if pt != dedup[-1]:
                dedup.append(pt)
        if len(dedup) >= 3 and dedup[0] == dedup[-1]:
            dedup.pop()

        if len(dedup) != 4:
            continue

        p_final = Polygon(dedup)
        if not p_final.is_valid:
            p_final = make_valid(p_final)
            if hasattr(p_final, "geoms"):
                p_final = max(p_final.geoms, key=lambda g: g.area, default=None)
            if p_final is None or not p_final.is_valid:
                continue
            coords = [(round(float(x), 1), round(float(y), 1)) for x, y in p_final.exterior.coords[:-1]]
            dedup = [coords[0]]
            for pt in coords[1:]:
                if pt != dedup[-1]:
                    dedup.append(pt)
            if len(dedup) >= 3 and dedup[0] == dedup[-1]:
                dedup.pop()

        if len(dedup) != 4 or p_final.area < min_area_px:
            continue

        cover = classify_interrow_cover(dedup, image_rgb)
        interrows.append(
            InterRowArea(
                points=dedup,
                vineyard_id=vineyard_id,
                interrow_cover=cover,
            )
        )

    return interrows


def derive_interrows(
    row_polylines: List[List[Tuple[float, float]]],
    canopies: List[VineyardCanopy],
    vineyard_id: str = "V01",
    image_rgb: Optional[np.ndarray] = None,
) -> List[InterRowArea]:
    """
    Backwards-compatible interface for interrow derivation from row polylines.
    """
    if len(row_polylines) < 2:
        return []

    # Estimate normal and c_val from provided polylines
    rows_meta = []
    angles = []
    for r_idx, pts in enumerate(row_polylines):
        if len(pts) >= 2:
            p1, p2 = np.array(pts[0]), np.array(pts[-1])
            diff = p2 - p1
            ang = np.degrees(np.arctan2(diff[1], diff[0])) % 180.0
            angles.append(ang)

    if not angles:
        return []

    mean_ang = float(np.median(angles))
    rad = np.radians(mean_ang)
    normal_dir = np.array([-np.sin(rad), np.cos(rad)])
    primary_dir = np.array([np.cos(rad), np.sin(rad)])

    for r_idx, pts in enumerate(row_polylines):
        pts_arr = np.array(pts)
        c_val = float(np.mean(np.dot(pts_arr, normal_dir)))
        rows_meta.append({
            "c_val": c_val,
            "row_id": f"{vineyard_id}-R{r_idx+1:02d}",
            "row_structure": "regular",
            "points": pts,
            "cluster": pts_arr,
        })

    return derive_interrow_quadrilaterals(
        rows_metadata=rows_meta,
        normal_dir=normal_dir,
        primary_dir=primary_dir,
        vineyard_id=vineyard_id,
        image_rgb=image_rgb,
    )

