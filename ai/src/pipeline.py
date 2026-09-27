import torch
from collections import defaultdict, Counter
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import cv2
import numpy as np
from PIL import Image
from scipy.ndimage import maximum_filter
from shapely.geometry import Polygon, MultiPolygon
from shapely.validation import make_valid

from src.export.cvat_writer import (
    CVATWriter,
    TileAnnotations,
    VineRow,
    InterRowArea,
    VineyardCanopy,
    WasteBox,
)
from src.spatial.grid import parse_tile_indices, pixel_to_map, START_POINT
from src.spatial.row_extractor import extract_rows_from_canopies, partition_canopies_by_orientation
from src.spatial.interrow import derive_interrows, derive_interrow_quadrilaterals
from src.spatial.block_cluster import GlobalBlockClusterer
from src.spatial.row_stitcher import GlobalRowStitcher, LocalRowSegment


def extract_polygons(geom) -> List[Polygon]:
    """Recursively extract all Polygon instances from Polygon, MultiPolygon, or GeometryCollection."""
    if isinstance(geom, Polygon):
        return [geom]
    elif hasattr(geom, "geoms"):
        res = []
        for g in geom.geoms:
            res.extend(extract_polygons(g))
        return res
    return []


def sanitize_and_format_polygon(
    poly: Polygon,
    min_area_px: float = 300.0,
    max_area_px: float = 15000.0,
    simplify_tol: float = 1.0,
) -> List[List[Tuple[float, float]]]:
    """
    Decimate with Douglas-Peucker, round to 1 decimal place, remove duplicate
    consecutive points, and strictly re-verify that the resulting geometry is:
    1. A valid simple closed polygon with 0 self-intersections.
    2. Strictly within [min_area_px, max_area_px] AFTER rounding.
    """
    if not poly.is_valid:
        poly = make_valid(poly)

    valid_coords_list = []
    for p in extract_polygons(poly):
        p_simp = p.simplify(simplify_tol, preserve_topology=True)
        if not p_simp.is_valid:
            p_simp = make_valid(p_simp)

        for sub_p in extract_polygons(p_simp):
            if sub_p.is_empty:
                continue
            # Extract exterior coordinates (dropping repeated endpoint)
            raw_coords = list(sub_p.exterior.coords)[:-1]
            if len(raw_coords) < 3:
                continue

            # Round coordinates to 1 decimal place as required by CVAT format
            rounded = [(round(float(x), 1), round(float(y), 1)) for x, y in raw_coords]

            # Eliminate consecutive duplicate vertices produced by rounding
            deduped = [rounded[0]]
            for pt in rounded[1:]:
                if pt != deduped[-1]:
                    deduped.append(pt)
            if len(deduped) > 1 and deduped[0] == deduped[-1]:
                deduped.pop()

            if len(deduped) < 3:
                continue

            # Re-verify topology and area of the actual rounded coordinates
            final_poly = Polygon(deduped)
            if not final_poly.is_valid:
                final_poly = make_valid(final_poly)

            for cand_poly in extract_polygons(final_poly):
                if (
                    cand_poly.is_valid
                    and not cand_poly.is_empty
                    and cand_poly.exterior.is_simple
                    and min_area_px <= cand_poly.area <= max_area_px
                ):
                    c_pts = [(round(float(x), 1), round(float(y), 1)) for x, y in cand_poly.exterior.coords[:-1]]
                    # Final deduplication
                    clean_c = [c_pts[0]]
                    for pt in c_pts[1:]:
                        if pt != clean_c[-1]:
                            clean_c.append(pt)
                    if len(clean_c) > 1 and clean_c[0] == clean_c[-1]:
                        clean_c.pop()
                    if len(clean_c) >= 3:
                        poly_eval = Polygon(clean_c)
                        if (
                            poly_eval.is_valid
                            and poly_eval.exterior.is_simple
                            and min_area_px <= poly_eval.area <= max_area_px
                        ):
                            valid_coords_list.append(clean_c)

    return valid_coords_list


def separate_canopy_polygon(
    pts_np: np.ndarray,
    min_dist_px: float = 40.0,
    min_area_px: float = 300.0,
    max_area_px: float = 15000.0,
    simplify_tol: float = 1.0,
) -> List[List[Tuple[float, float]]]:
    """
    Mentor Concepts Implementation:
    1. Morphological opening (3x3 ellipse) to sever flimsy single-pixel necks.
    2. Euclidean distance transform & marker-controlled watershed for elongated/touching canopies.
    3. Minimum area filtering (>= 300 px² / ~0.2 m²) and maximum area threshold (<= 15,000 px² / avoiding whole-row mergers).
    4. Topological sanitization (make_valid + GeometryCollection extraction) and
       Douglas-Peucker simplification (tol=1.0 px -> median 14 vertices matching GT).
    5. Post-rounding geometric re-validation ensuring 100% valid simple closed polygons.
    """
    if len(pts_np) < 3:
        return []

    min_x, min_y = pts_np.min(axis=0)
    max_x, max_y = pts_np.max(axis=0)
    w = max_x - min_x
    h = max_y - min_y
    diag = np.sqrt(w * w + h * h)
    aspect_ratio = max(w, h) / max(min(w, h), 1e-3)

    # If small or compact, sanitize directly without watershed
    if diag < 75 and aspect_ratio < 1.8:
        poly = Polygon(pts_np)
        return sanitize_and_format_polygon(
            poly, min_area_px=min_area_px, max_area_px=max_area_px, simplify_tol=simplify_tol
        )

    # Elongated / compound canopies: Morphological Opening & Distance-Transform Watershed
    pad = 4
    pw = int(np.ceil(w)) + 2 * pad
    ph = int(np.ceil(h)) + 2 * pad
    patch = np.zeros((ph, pw), dtype=np.uint8)
    local_pts = (pts_np - [min_x, min_y] + [pad, pad]).astype(np.int32)
    cv2.fillPoly(patch, [local_pts], 255)

    # 1. Morphological Opening (sever single-pixel weed bridges)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    opened = cv2.morphologyEx(patch, cv2.MORPH_OPEN, kernel)

    # 2. Euclidean Distance Transform
    dist = cv2.distanceTransform(opened, cv2.DIST_L2, 5)

    footprint_size = int(min_dist_px)
    if footprint_size % 2 == 0:
        footprint_size += 1
    local_max = (dist == maximum_filter(dist, size=footprint_size)) & (dist > 5.0)
    peak_y, peak_x = np.where(local_max)

    # Single peak: extract contour from opened mask
    if len(peak_x) <= 1:
        contours, _ = cv2.findContours(opened, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid_polys = []
        for cnt in contours:
            if len(cnt) >= 3:
                cnt_pts = cnt.reshape(-1, 2) + [min_x - pad, min_y - pad]
                valid_polys.extend(
                    sanitize_and_format_polygon(
                        Polygon(cnt_pts),
                        min_area_px=min_area_px,
                        max_area_px=max_area_px,
                        simplify_tol=simplify_tol,
                    )
                )
        return valid_polys

    # Multiple peaks: Marker-controlled watershed
    markers = np.zeros_like(opened, dtype=np.int32)
    for m_id, (px, py) in enumerate(zip(peak_x, peak_y), start=1):
        cv2.circle(markers, (px, py), 2, m_id, -1)

    color_patch = cv2.cvtColor(opened, cv2.COLOR_GRAY2BGR)
    cv2.watershed(color_patch, markers)

    valid_polys = []
    for m_id in range(1, len(peak_x) + 1):
        sub_mask = ((markers == m_id) & (opened > 0)).astype(np.uint8) * 255
        if sub_mask.sum() == 0:
            continue
        contours, _ = cv2.findContours(sub_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            if len(cnt) >= 3:
                cnt_pts = cnt.reshape(-1, 2) + [min_x - pad, min_y - pad]
                valid_polys.extend(
                    sanitize_and_format_polygon(
                        Polygon(cnt_pts),
                        min_area_px=min_area_px,
                        max_area_px=max_area_px,
                        simplify_tol=simplify_tol,
                    )
                )
    return valid_polys


def nms_canopy_polygons(
    candidates: Any,
    iou_thresh: float = 0.25,
    iomin_thresh: float = 0.35,
    min_dist_px: float = 25.0,
    min_area_px: float = 300.0,
    max_area_px: float = 15000.0,
) -> List[List[Tuple[float, float]]]:
    """
    Polygon Non-Maximum Suppression (IoU & IoMin deduplication) on extracted canopies.
    Removes duplicate overlapping canopy polygon predictions on the same vine,
    ensuring each physical vine has exactly one canopy polygon.

    Parameters:
        candidates: List of (score, poly_coords) tuples or List of poly_coords
        iou_thresh: Maximum allowed Intersection-over-Union between distinct plants (default: 0.25)
        iomin_thresh: Maximum allowed Intersection-over-Min-Area (containment) (default: 0.35)
        min_dist_px: Centroid distance threshold below which overlapping polygons are deduplicated (default: 25.0 px)
        min_area_px: Minimum canopy polygon area (default: 300.0 px²)
        max_area_px: Maximum canopy polygon area (default: 15000.0 px²)

    Returns:
        Deduplicated list of simple polygon coordinates List[List[Tuple[float, float]]]
    """
    if not candidates:
        return []

    # Standardize input format
    valid_cands = []
    for item in candidates:
        if isinstance(item, tuple) and len(item) == 2:
            score = float(item[0])
            coords_raw = item[1]
        elif isinstance(item, (list, tuple, np.ndarray, Polygon)):
            score = 1.0
            coords_raw = item
        else:
            continue

        if isinstance(coords_raw, Polygon):
            coords = list(coords_raw.exterior.coords)[:-1]
        elif isinstance(coords_raw, (list, tuple, np.ndarray)):
            coords = [tuple(map(float, pt)) for pt in coords_raw]
        else:
            continue

        if len(coords) < 3:
            continue

        p = Polygon(coords)
        if not p.is_valid:
            p = make_valid(p)
            for sub_p in extract_polygons(p):
                if sub_p.is_valid and min_area_px <= sub_p.area <= max_area_px:
                    c = (float(sub_p.centroid.x), float(sub_p.centroid.y))
                    b = sub_p.bounds
                    c_pts = [(round(float(x), 1), round(float(y), 1)) for x, y in sub_p.exterior.coords[:-1]]
                    valid_cands.append((score, c_pts, sub_p, c, b))
        elif min_area_px <= p.area <= max_area_px:
            c = (float(p.centroid.x), float(p.centroid.y))
            b = p.bounds
            valid_cands.append((score, coords, p, c, b))

    if not valid_cands:
        return []

    # Sort descending by confidence score (prefer higher score; tie-break with area)
    valid_cands.sort(key=lambda x: (x[0], x[2].area), reverse=True)

    kept: List[Tuple[float, List[Tuple[float, float]], Polygon, Tuple[float, float], Tuple[float, float, float, float]]] = []

    for score, coords, p, c, b in valid_cands:
        is_dup = False
        p_area = p.area
        for k_score, k_coords, k_p, k_c, k_b in kept:
            # Fast AABB pre-filter
            if b[2] < k_b[0] or k_b[2] < b[0] or b[3] < k_b[1] or k_b[3] < b[1]:
                continue

            dx = c[0] - k_c[0]
            dy = c[1] - k_c[1]
            dist = (dx * dx + dy * dy) ** 0.5

            try:
                inter_geom = p.intersection(k_p)
                inter_area = float(inter_geom.area)
            except Exception:
                inter_area = 0.0

            if inter_area > 0.0:
                k_area = k_p.area
                union = p_area + k_area - inter_area
                iou = inter_area / union if union > 0.0 else 0.0
                iomin = inter_area / min(p_area, k_area)

                if (
                    iou >= iou_thresh
                    or iomin >= iomin_thresh
                    or (dist < min_dist_px and inter_area > 0.08 * min(p_area, k_area))
                ):
                    is_dup = True
                    break

        if not is_dup:
            kept.append((score, coords, p, c, b))

    return [k[1] for k in kept]


class VineyardPipeline:
    def __init__(self, model_weights_path: Optional[str] = None):
        self.model_weights = model_weights_path
        self.model = None
        self.model_type = "yolo"
        self.device = self._select_device()
        if model_weights_path and Path(model_weights_path).exists():
            p = str(model_weights_path)
            if p.endswith(".pth") or "rfdetr" in p.lower():
                from rfdetr import RFDETRSegLarge
                self.model_type = "rfdetr"
                self.model = RFDETRSegLarge.from_checkpoint(p)
            else:
                from ultralytics import YOLO
                self.model_type = "yolo"
                self.model = YOLO(p)

    @staticmethod
    def _select_device() -> str:
        if torch.backends.mps.is_available():
            return "mps"
        elif torch.cuda.is_available():
            return "cuda"
        return "cpu"

    @staticmethod
    def sanitize_polygon(
        raw_points: np.ndarray, min_area_px: float = 300.0, max_area_px: float = 15000.0
    ) -> List[List[Tuple[float, float]]]:
        """Wrapper around separate_canopy_polygon for backward compatibility."""
        return separate_canopy_polygon(raw_points, min_area_px=min_area_px, max_area_px=max_area_px)

    def process_batch(
        self,
        tile_paths: List[str],
        confidence: float = 0.28,
        imgsz: int = 2048,
        min_plant_dist_px: float = 40.0,
        min_area_px: float = 300.0,
        max_area_px: float = 15000.0,
        extract_rows: bool = True,
        extract_interrows: bool = True,
        margin_px: float = 12.0,
        passages_geojson: str = "assets/02_route/passages.geojson",
        verbose: bool = True,
    ) -> Tuple[List[TileAnnotations], List[Tuple[float, float]]]:
        """
        Complete Vineyard Pipeline:
        1. High-resolution AI inference per tile (YOLO26-Seg native 2048x2048)
        2. Morphological opening & distance-transform watershed separation
        3. Clean polygon sanitization & Douglas-Peucker decimation (median 12-14 vertices)
        4. Global block clustering (EPSG:32635) via 2.5m buffer & passage cuts
        5. Straight-line row extraction & gap disruption assessment (regular/disrupted)
        6. Clean quadrilateral inter-row area derivation bounded by row margins
        """
        tile_results = []
        tile_canopy_centroids: Dict[str, List[Tuple[float, float]]] = {}
        tile_parsed_indices: Dict[str, Optional[Tuple[int, int]]] = {}

        # -------------------------------------------------------------
        # Phase 1: Model inference & polygon separation
        # -------------------------------------------------------------
        for idx, tile_path in enumerate(tile_paths, start=1):
            tile_name = Path(tile_path).name
            try:
                r, c = parse_tile_indices(tile_name)
                tile_parsed_indices[tile_name] = (r, c)
            except Exception:
                tile_parsed_indices[tile_name] = None

            canopy_polys: List[List[Tuple[float, float]]] = []
            canopy_cents: List[Tuple[float, float]] = []
            raw_candidates: List[Tuple[float, List[Tuple[float, float]]]] = []

            if self.model is not None:
                if self.model_type == "rfdetr":
                    dets = self.model.predict(tile_path, threshold=confidence)
                    if dets.mask is not None:
                        for m in dets.mask:
                            contours, _ = cv2.findContours(
                                m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                            )
                            for cnt in contours:
                                pts = cnt.reshape(-1, 2)
                                cleaned_polys = separate_canopy_polygon(
                                    pts,
                                    min_dist_px=min_plant_dist_px,
                                    min_area_px=min_area_px,
                                    max_area_px=max_area_px,
                                    simplify_tol=1.0,
                                )
                                for poly_coords in cleaned_polys:
                                    raw_candidates.append((1.0, poly_coords))
                else:
                    results = self.model.predict(
                        tile_path,
                        conf=confidence,
                        imgsz=imgsz,
                        max_det=1500,
                        device=self.device,
                        verbose=False,
                    )[0]

                    if results.masks is not None:
                        confs = (
                            results.boxes.conf.cpu().numpy()
                            if results.boxes is not None and results.boxes.conf is not None
                            else [1.0] * len(results.masks.xy)
                        )
                        for mask, conf in zip(results.masks.xy, confs):
                            cleaned_polys = separate_canopy_polygon(
                                mask,
                                min_dist_px=min_plant_dist_px,
                                min_area_px=min_area_px,
                                max_area_px=max_area_px,
                                simplify_tol=1.0,
                            )
                            for poly_coords in cleaned_polys:
                                raw_candidates.append((float(conf), poly_coords))

                deduped_polys = nms_canopy_polygons(
                    raw_candidates,
                    iou_thresh=0.25,
                    iomin_thresh=0.35,
                    min_dist_px=25.0,
                    min_area_px=min_area_px,
                    max_area_px=max_area_px,
                )
                for poly_coords in deduped_polys:
                    canopy_polys.append(poly_coords)
                    c_poly = Polygon(poly_coords)
                    canopy_cents.append((float(c_poly.centroid.x), float(c_poly.centroid.y)))

            tile_canopy_centroids[tile_name] = canopy_cents
            tile_results.append({
                "tile_name": tile_name,
                "tile_path": tile_path,
                "canopy_polys": canopy_polys,
                "canopy_cents": canopy_cents,
            })

            if verbose:
                print(f"[{idx}/{len(tile_paths)}] Processed {tile_name}: {len(canopy_polys)} valid canopies")

        # -------------------------------------------------------------
        # Phase 2: Global Block Clustering (EPSG:32635)
        # -------------------------------------------------------------
        clusterer = GlobalBlockClusterer(passages_geojson=passages_geojson)
        has_georef = any(idx is not None for idx in tile_parsed_indices.values())

        if has_georef:
            clusterer.cluster_blocks(tile_canopy_centroids, buffer_distance_m=2.5)

        # -------------------------------------------------------------
        # Phase 3: Assembly of TileAnnotations (Canopies, Rows, Interrows)
        # -------------------------------------------------------------
        final_annotations: List[TileAnnotations] = []
        all_targets: List[Tuple[float, float]] = []

        # Intermediate row storage: tile_name -> block_id -> (v_rows, meta)
        tile_block_rows: Dict[str, Dict[str, Tuple[List[VineRow], Dict[str, Any]]]] = defaultdict(dict)
        block_row_segments: Dict[str, List[LocalRowSegment]] = defaultdict(list)

        for t_data in tile_results:
            tile_name = t_data["tile_name"]
            coords = tile_parsed_indices.get(tile_name)
            tile_ann = TileAnnotations(image_name=tile_name, width=2048, height=2048)

            # Assign block IDs to canopies and group centroids per block
            block_canopy_map: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
            for pts, cent in zip(t_data["canopy_polys"], t_data["canopy_cents"]):
                if coords is not None:
                    r, c = coords
                    east, north = pixel_to_map(r, c, cent[0], cent[1])
                    v_id = clusterer.get_block_id_for_point(east, north)
                else:
                    v_id = "V01"
                tile_ann.canopies.append(VineyardCanopy(points=pts, vineyard_id=v_id))
                block_canopy_map[v_id].append(cent)

            # Extract straight row lines per orientation group on the tile
            if extract_rows and len(t_data["canopy_cents"]) >= 2:
                im_rgb_tile = None
                if Path(t_data["tile_path"]).exists():
                    try:
                        im_rgb_tile = np.array(Image.open(t_data["tile_path"]).convert("RGB"))
                    except Exception:
                        im_rgb_tile = None

                orientation_groups = partition_canopies_by_orientation(t_data["canopy_cents"], min_angle_diff=25.0)

                for sub_cents, sub_indices, _ in orientation_groups:
                    if len(sub_cents) < 2:
                        continue

                    sub_v_rows, targets, meta = extract_rows_from_canopies(
                        canopy_centroids=sub_cents,
                        vineyard_id="V01",
                        tile_width=2048,
                        tile_height=2048,
                        min_vines_per_row=2,
                        return_metadata=True,
                        image_rgb=im_rgb_tile,
                    )
                    all_targets.extend(targets)

                    if meta and meta.get("rows_data"):
                        rows_by_block = defaultdict(list)
                        for rdata in meta["rows_data"]:
                            if coords is not None:
                                r, c = coords
                                b_votes = [clusterer.get_block_id_for_point(*pixel_to_map(r, c, px, py)) for px, py in rdata["cluster"]]
                                assigned_b = Counter(b_votes).most_common(1)[0][0] if b_votes else "V01"
                            else:
                                assigned_b = "V01"
                            rdata["vineyard_id"] = assigned_b
                            vr = rdata["vine_row"]
                            vr.vineyard_id = assigned_b
                            rows_by_block[assigned_b].append(rdata)

                        for b_id, rdata_list in rows_by_block.items():
                            v_rows = [rd["vine_row"] for rd in rdata_list]
                            for r_idx, (rd, vr) in enumerate(zip(rdata_list, v_rows), start=1):
                                vr.row_id = f"{b_id}-R{r_idx:02d}"
                                rd["row_id"] = vr.row_id
                            tile_block_rows[tile_name][b_id] = (
                                v_rows,
                                {
                                    "rows_data": rdata_list,
                                    "normal_dir": meta["normal_dir"],
                                    "primary_dir": meta["primary_dir"],
                                    "azimuth_deg": meta["azimuth_deg"],
                                },
                            )
                            if coords is not None:
                                r, c = coords
                                for vr in v_rows:
                                    g_pts = [pixel_to_map(r, c, px, py) for px, py in vr.points]
                                    block_row_segments[b_id].append(
                                        LocalRowSegment(
                                            tile_name=tile_name,
                                            local_points=vr.points,
                                            global_points=g_pts,
                                            block_id=b_id,
                                            row_structure=vr.row_structure,
                                        )
                                    )

            final_annotations.append(tile_ann)

        # Cross-tile row stitching if georeferenced and multiple tiles
        tile_stitched_rows: Dict[str, Dict[str, List[VineRow]]] = defaultdict(lambda: defaultdict(list))
        if has_georef and len(tile_paths) > 1 and extract_rows:
            stitcher = GlobalRowStitcher()
            for b_id, segs in block_row_segments.items():
                if segs:
                    updated_segs = stitcher.stitch_block_rows(b_id, segs)
                    for s in updated_segs:
                        vr = VineRow(
                            points=s.local_points,
                            vineyard_id=s.block_id,
                            row_id=s.assigned_row_id,
                            row_structure=s.row_structure,
                        )
                        tile_stitched_rows[s.tile_name][s.block_id].append(vr)

        # Add rows and derive quadrilateral inter-row areas
        for idx, tile_ann in enumerate(final_annotations):
            t_name = tile_ann.image_name
            t_path = tile_results[idx]["tile_path"]

            # Load image for ground cover classification if needed
            im_rgb = None
            if extract_interrows and Path(t_path).exists():
                try:
                    im_rgb = np.array(Image.open(t_path).convert("RGB"))
                except Exception:
                    im_rgb = None

            block_rows_source = tile_stitched_rows.get(t_name) if (has_georef and len(tile_paths) > 1 and extract_rows) else None

            if block_rows_source:
                for b_id, v_rows in block_rows_source.items():
                    tile_ann.rows.extend(v_rows)

                    meta = tile_block_rows.get(t_name, {}).get(b_id, ([], None))[1]
                    if extract_interrows and meta and len(v_rows) >= 2:
                        normal_dir = meta["normal_dir"]
                        primary_dir = meta["primary_dir"]
                        rows_metadata = []
                        for vr in v_rows:
                            if len(vr.points) >= 2:
                                c_val = float(np.mean([np.dot(np.array(pt), normal_dir) for pt in vr.points]))
                                s_projs = [float(np.dot(np.array(pt), primary_dir)) for pt in vr.points]
                                rows_metadata.append({
                                    "c_val": c_val,
                                    "s_min": min(s_projs),
                                    "s_max": max(s_projs),
                                    "points": vr.points,
                                    "row_id": vr.row_id,
                                    "row_structure": vr.row_structure,
                                    "vine_row": vr,
                                })

                        if len(rows_metadata) >= 2:
                            ir_quads = derive_interrow_quadrilaterals(
                                rows_metadata=rows_metadata,
                                normal_dir=normal_dir,
                                primary_dir=primary_dir,
                                vineyard_id=b_id,
                                image_rgb=im_rgb,
                                margin_px=margin_px,
                                tile_width=2048.0,
                                tile_height=2048.0,
                            )
                            tile_ann.interrows.extend(ir_quads)
            else:
                for b_id, (v_rows, meta) in tile_block_rows.get(t_name, {}).items():
                    tile_ann.rows.extend(v_rows)

                    if extract_interrows and meta and len(meta.get("rows_data", [])) >= 2:
                        ir_quads = derive_interrow_quadrilaterals(
                            rows_metadata=meta["rows_data"],
                            normal_dir=meta["normal_dir"],
                            primary_dir=meta["primary_dir"],
                            vineyard_id=b_id,
                            image_rgb=im_rgb,
                            margin_px=margin_px,
                            tile_width=2048.0,
                            tile_height=2048.0,
                        )
                        tile_ann.interrows.extend(ir_quads)

        return final_annotations, all_targets

    def process_tile(
        self,
        tile_path: str,
        vineyard_id: str = "V01",
        confidence: float = 0.28,
        imgsz: int = 2048,
        min_area_px: float = 300.0,
        max_area_px: float = 15000.0,
        extract_rows: bool = True,
        extract_interrows: bool = True,
        margin_px: float = 12.0,
    ) -> Tuple[TileAnnotations, List[Tuple[float, float]]]:
        """Process a single tile via the batch pipeline for consistent IDs."""
        anns, targets = self.process_batch(
            [tile_path],
            confidence=confidence,
            imgsz=imgsz,
            min_area_px=min_area_px,
            max_area_px=max_area_px,
            extract_rows=extract_rows,
            extract_interrows=extract_interrows,
            margin_px=margin_px,
            verbose=False,
        )
        return anns[0], targets

