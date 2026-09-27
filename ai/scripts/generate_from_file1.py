"""
Generate Marcaj CVAT 1.1 XML from file1.txt mapping.

Reads vineyard_id/file_name pairings from file1.txt, runs YOLO26L inference
on all unique vineyard tiles, assigns block IDs to canopies, extracts straight vine
rows, stitches collinear rows across tile boundaries with sequential IDs (e.g. V01-R01),
derives clean quadrilateral inter-row corridors, and outputs fully compliant CVAT 1.1 XML.
Also supports exporting empty frames for non-vineyard challenge tiles and per-part XMLs for Marcaj.
"""

import argparse
import sys
import time
from collections import defaultdict, Counter
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Set
import cv2
import numpy as np
from PIL import Image
from shapely.geometry import Polygon

# Ensure repository root is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.pipeline import VineyardPipeline, separate_canopy_polygon, nms_canopy_polygons
from src.export.cvat_writer import (
    CVATWriter,
    TileAnnotations,
    VineyardCanopy,
    VineRow,
    InterRowArea,
)
from src.spatial.grid import (
    parse_tile_indices,
    pixel_to_map,
    tile_upper_left,
    TILE_SIZE_M,
)
from src.spatial.row_extractor import extract_rows_from_canopies, partition_canopies_by_orientation
from src.spatial.row_stitcher import GlobalRowStitcher, LocalRowSegment
from src.spatial.interrow import derive_interrow_quadrilaterals
from scripts.validate_annotations import validate_annotations


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate Marcaj CVAT 1.1 XML from file1.txt tile-to-block mapping."
    )
    parser.add_argument(
        "--file1",
        type=str,
        default="file1.txt",
        help="Path to file1.txt mapping file (default: file1.txt)",
    )
    parser.add_argument(
        "--tiles-dir",
        type=str,
        default="assets/01_tiles",
        help="Root directory containing challenge tiles (default: assets/01_tiles)",
    )
    parser.add_argument(
        "--weights",
        type=str,
        default="weights/best.pt",
        help="Path to trained model weights (default: weights/best.pt)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="annotations_challenge.xml",
        help="Path to output master CVAT XML file (default: annotations_challenge.xml)",
    )
    parser.add_argument(
        "--output-parts-dir",
        type=str,
        default="",
        help="Optional directory to write per-part XMLs (e.g. annotations_part1of5.xml)",
    )
    parser.add_argument(
        "--include-empty",
        action="store_true",
        default=True,
        help="Include empty <image> records for non-vineyard challenge tiles (default: True)",
    )
    parser.add_argument(
        "--vineyard-only",
        action="store_true",
        default=False,
        help="Only include the 142 vineyard tiles in the output XML (exclude empty tiles)",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.28,
        help="Confidence threshold for YOLO segmentation (default: 0.28)",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=2048,
        help="Inference image resolution (default: 2048)",
    )
    parser.add_argument(
        "--margin-px",
        type=float,
        default=12.0,
        help="Canopy margin in pixels for interrow corridors (default: 12.0 px = 0.30 m)",
    )
    parser.add_argument(
        "--min-area-px",
        type=float,
        default=300.0,
        help="Minimum canopy area threshold in pixels (default: 300.0 px² = 0.19 m²)",
    )
    parser.add_argument(
        "--max-area-px",
        type=float,
        default=15000.0,
        help="Maximum canopy area threshold before whole-row rejection (default: 15000.0 px²)",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="",
        help="Torch device ('mps', 'cuda', 'cpu', default: auto)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of tiles to process (for debugging/testing)",
    )
    parser.add_argument(
        "--create-zips",
        action="store_true",
        default=False,
        help="Package ready-to-upload Marcaj ZIP files in exports/zips/",
    )
    return parser.parse_args()


def load_file1_mapping(file1_path: str) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """
    Parse file1.txt into:
    - tile_to_blocks: tile_name -> list of vineyard_ids
    - block_to_tiles: vineyard_id -> list of tile_names
    """
    path = Path(file1_path)
    if not path.exists():
        raise FileNotFoundError(f"Mapping file not found: {path.resolve()}")

    tile_to_blocks = defaultdict(list)
    block_to_tiles = defaultdict(list)

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("/")
            if len(parts) != 2:
                continue
            vid, tname = parts[0].strip(), parts[1].strip()
            if vid not in tile_to_blocks[tname]:
                tile_to_blocks[tname].append(vid)
            if tname not in block_to_tiles[vid]:
                block_to_tiles[vid].append(tname)

    return dict(tile_to_blocks), dict(block_to_tiles)


def find_all_challenge_tiles(tiles_dir: str) -> Tuple[Dict[str, Path], Dict[str, str]]:
    """
    Scan tiles directory recursively.
    Returns:
    - tile_paths: tile_name -> Path
    - tile_part_map: tile_name -> part folder name (e.g. siret3_challenge_tiles_part1of5)
    """
    tiles_path = Path(tiles_dir)
    tile_paths = {}
    tile_part_map = {}

    for tif in tiles_path.glob("**/*.tif"):
        tile_paths[tif.name] = tif
        # Identify part directory name if applicable
        for parent in tif.parents:
            if "part" in parent.name.lower():
                tile_part_map[tif.name] = parent.name
                break
        if tif.name not in tile_part_map:
            tile_part_map[tif.name] = "default"

    return tile_paths, tile_part_map


def compute_block_reference_geometry(
    block_to_tiles: Dict[str, List[str]]
) -> Tuple[Dict[str, np.ndarray], Dict[Tuple[str, str], np.ndarray]]:
    """
    Computes:
    1. block_centroids: block_id -> np.array([East_mean, North_mean])
    2. shared_tile_directions: (tile_name, block_id) -> unit vector pointing towards block body
    """
    def tile_center(tname: str) -> np.ndarray:
        r, c = parse_tile_indices(tname)
        x_ul, y_ul = tile_upper_left(r, c)
        return np.array([x_ul + TILE_SIZE_M / 2.0, y_ul - TILE_SIZE_M / 2.0])

    block_centroids = {}
    for vid, t_list in block_to_tiles.items():
        centers = [tile_center(t) for t in t_list]
        block_centroids[vid] = np.mean(centers, axis=0)

    shared_tile_directions = {}
    for vid, t_list in block_to_tiles.items():
        for tname in t_list:
            c_t = tile_center(tname)
            other_tiles = [t for t in t_list if t != tname]
            if other_tiles:
                c_others = np.mean([tile_center(to) for to in other_tiles], axis=0)
                diff = c_others - c_t
                norm = np.linalg.norm(diff)
                vec = diff / (norm if norm > 1e-4 else 1.0)
            else:
                diff = block_centroids[vid] - c_t
                norm = np.linalg.norm(diff)
                vec = diff / (norm if norm > 1e-4 else 1.0)
            shared_tile_directions[(tname, vid)] = vec

    return block_centroids, shared_tile_directions


def assign_canopy_block(
    r: int,
    c: int,
    px: float,
    py: float,
    tile_name: str,
    candidate_blocks: List[str],
    block_centroids: Dict[str, np.ndarray],
    shared_tile_directions: Dict[Tuple[str, str], np.ndarray],
) -> str:
    """
    Assign a canopy at (px, py) on tile (r, c) to one of the candidate blocks.
    Uses directional projection vector from tile center towards each block's body.
    """
    if len(candidate_blocks) == 1:
        return candidate_blocks[0]

    # Convert pixel coordinates to map coordinates
    east, north = pixel_to_map(r, c, px, py)
    p_map = np.array([east, north])

    # Tile center in map coordinates
    x_ul, y_ul = tile_upper_left(r, c)
    c_t = np.array([x_ul + TILE_SIZE_M / 2.0, y_ul - TILE_SIZE_M / 2.0])
    p_offset = p_map - c_t

    best_block = candidate_blocks[0]
    best_score = -1e9

    for vid in candidate_blocks:
        vec = shared_tile_directions.get((tile_name, vid), np.zeros(2))
        if np.linalg.norm(vec) > 1e-3:
            score = float(np.dot(p_offset, vec))
        else:
            # Fallback to negative Euclidean distance to block centroid
            score = -float(np.linalg.norm(p_map - block_centroids[vid]))

        if score > best_score:
            best_score = score
            best_block = vid

    return best_block


def main():
    args = parse_args()

    # Resolve paths
    file1_path = Path(args.file1)
    tiles_dir = Path(args.tiles_dir)
    out_xml_path = Path(args.output)

    print("=" * 70)
    print("Marcaj CVAT 1.1 XML Generator from file1.txt")
    print(f"Mapping File:     {file1_path.resolve()}")
    print(f"Tiles Directory:  {tiles_dir.resolve()}")
    print(f"Model Weights:    {args.weights}")
    print(f"Output XML:       {out_xml_path.resolve()}")
    print(f"Confidence:       {args.conf} | ImgSz: {args.imgsz}")
    print(f"Canopy Margin:    {args.margin_px} px ({args.margin_px * 0.025:.2f} m)")
    print(f"Include Empty:    {not args.vineyard_only}")
    print("=" * 70)

    # 1. Load file1.txt mapping
    tile_to_blocks, block_to_tiles = load_file1_mapping(str(file1_path))
    unique_tiles = sorted(tile_to_blocks.keys())
    print(f"Loaded {len(file1_path.read_text().splitlines())} lines from {file1_path.name}")
    print(f"Identified {len(unique_tiles)} unique vineyard tiles across {len(block_to_tiles)} blocks.")

    # 2. Locate all tiles on disk
    all_disk_tiles, tile_part_map = find_all_challenge_tiles(str(tiles_dir))
    print(f"Found {len(all_disk_tiles)} total .tif tiles across challenge directories.")

    # Verify that all 142 tiles in file1.txt exist on disk
    missing = [t for t in unique_tiles if t not in all_disk_tiles]
    if missing:
        raise FileNotFoundError(
            f"Error: {len(missing)} tiles from {file1_path.name} were not found on disk: {missing[:5]}"
        )

    # 3. Compute block reference geometry
    block_centroids, shared_tile_directions = compute_block_reference_geometry(block_to_tiles)

    # Determine subset of tiles to process if limit specified
    tiles_to_process = unique_tiles[:args.limit] if args.limit is not None else unique_tiles
    print(f"Processing {len(tiles_to_process)} vineyard tiles with YOLO26L...")

    # 4. Initialize Pipeline and Load Model
    pipeline = VineyardPipeline(model_weights_path=args.weights)
    if args.device:
        pipeline.device = args.device

    # Intermediate storage per tile:
    # tile_canopies: tile_name -> List[VineyardCanopy]
    # tile_rows: tile_name -> List[VineRow]
    # tile_interrows: tile_name -> List[InterRowArea]
    # block_row_segments: block_id -> List[LocalRowSegment]
    tile_canopies_map: Dict[str, List[VineyardCanopy]] = defaultdict(list)
    tile_block_row_data: Dict[str, Dict[str, Any]] = defaultdict(dict)
    block_row_segments: Dict[str, List[LocalRowSegment]] = defaultdict(list)

    total_canopies_detected = 0
    t_start = time.time()

    # Process each vineyard tile
    for idx, tname in enumerate(tiles_to_process, start=1):
        t_path = all_disk_tiles[tname]
        r, c = parse_tile_indices(tname)
        candidates = tile_to_blocks[tname]

        # Model inference
        results = pipeline.model.predict(
            str(t_path),
            conf=args.conf,
            imgsz=args.imgsz,
            max_det=1500,
            device=pipeline.device,
            verbose=False,
        )[0]

        im_rgb = None
        try:
            im_rgb = np.array(Image.open(t_path).convert("RGB"))
        except Exception:
            im_rgb = None

        raw_candidates: List[Tuple[float, List[Tuple[float, float]]]] = []
        if results.masks is not None:
            confs = (
                results.boxes.conf.cpu().numpy()
                if results.boxes is not None and results.boxes.conf is not None
                else [1.0] * len(results.masks.xy)
            )
            for mask, conf in zip(results.masks.xy, confs):
                cleaned_polys = separate_canopy_polygon(
                    mask,
                    min_dist_px=40.0,
                    min_area_px=args.min_area_px,
                    max_area_px=args.max_area_px,
                    simplify_tol=1.0,
                )
                for poly_coords in cleaned_polys:
                    raw_candidates.append((float(conf), poly_coords))

        canopy_polys: List[List[Tuple[float, float]]] = []
        canopy_cents: List[Tuple[float, float]] = []

        deduped_polys = nms_canopy_polygons(
            raw_candidates,
            iou_thresh=0.25,
            iomin_thresh=0.35,
            min_dist_px=25.0,
            min_area_px=args.min_area_px,
            max_area_px=args.max_area_px,
        )
        for poly_coords in deduped_polys:
            canopy_polys.append(poly_coords)
            c_poly = Polygon(poly_coords)
            canopy_cents.append((float(c_poly.centroid.x), float(c_poly.centroid.y)))

        # 1. Partition canopies if tile contains distinct plantings with different orientations
        orientation_groups = partition_canopies_by_orientation(canopy_cents, min_angle_diff=25.0)
        canopy_assigned_vid: Dict[int, str] = {}

        for sub_cents, sub_indices, _ in orientation_groups:
            if len(sub_cents) < 2:
                continue

            sub_v_rows, targets, sub_meta = extract_rows_from_canopies(
                canopy_centroids=sub_cents,
                vineyard_id=candidates[0],
                tile_width=2048,
                tile_height=2048,
                min_vines_per_row=2,
                return_metadata=True,
                image_rgb=im_rgb,
                headland_margin_px=60.0,
            )

            if not (sub_meta and sub_meta.get("rows_data")):
                continue

            # Group rows into connected plantings (spacing <= 160px / 4m)
            rows_data = sorted(sub_meta["rows_data"], key=lambda r: r["c_val"])
            plantings = []
            curr_planting = [rows_data[0]]
            for p_i in range(1, len(rows_data)):
                spacing = rows_data[p_i]["c_val"] - rows_data[p_i - 1]["c_val"]
                if spacing <= 160.0:  # <= 4m
                    curr_planting.append(rows_data[p_i])
                else:
                    plantings.append(curr_planting)
                    curr_planting = [rows_data[p_i]]
            if curr_planting:
                plantings.append(curr_planting)

            for pl in plantings:
                if len(candidates) == 1:
                    assigned_pl_vid = candidates[0]
                else:
                    votes = []
                    for rdata in pl:
                        for px, py in rdata["cluster"]:
                            votes.append(
                                assign_canopy_block(
                                    r=r,
                                    c=c,
                                    px=px,
                                    py=py,
                                    tile_name=tname,
                                    candidate_blocks=candidates,
                                    block_centroids=block_centroids,
                                    shared_tile_directions=shared_tile_directions,
                                )
                            )
                    assigned_pl_vid = Counter(votes).most_common(1)[0][0] if votes else candidates[0]

                for rdata in pl:
                    rdata["vineyard_id"] = assigned_pl_vid
                    vr = rdata["vine_row"]
                    vr.vineyard_id = assigned_pl_vid

            # Organize rows and interrow metadata by block ID for this orientation group
            rows_by_vid = defaultdict(list)
            for rdata in sub_meta["rows_data"]:
                vid = rdata.get("vineyard_id", candidates[0])
                rows_by_vid[vid].append(rdata)

            for vid, rdata_list in rows_by_vid.items():
                v_rows = [rd["vine_row"] for rd in rdata_list]
                for r_idx, (rd, vr) in enumerate(zip(rdata_list, v_rows), start=1):
                    vr.row_id = f"{vid}-R{r_idx:02d}"
                    rd["row_id"] = vr.row_id

                tile_block_row_data[tname][vid] = {
                    "v_rows": v_rows,
                    "meta": {
                        "rows_data": rdata_list,
                        "normal_dir": sub_meta["normal_dir"],
                        "primary_dir": sub_meta["primary_dir"],
                        "azimuth_deg": sub_meta["azimuth_deg"],
                    },
                }

                # Register segments for global cross-tile stitching
                for vr in v_rows:
                    g_pts = [pixel_to_map(r, c, px, py) for px, py in vr.points]
                    block_row_segments[vid].append(
                        LocalRowSegment(
                            tile_name=tname,
                            local_points=vr.points,
                            global_points=g_pts,
                            block_id=vid,
                            row_structure=vr.row_structure,
                        )
                    )

            # Assign block to each canopy in this group based on closest row
            for orig_idx in sub_indices:
                cx, cy = canopy_cents[orig_idx]
                best_dist = 1e9
                best_vid = None
                for rdata in sub_meta["rows_data"]:
                    c_val = rdata["c_val"]
                    norm_dir = sub_meta["normal_dir"]
                    prim_dir = sub_meta["primary_dir"]
                    pt = np.array([cx, cy])
                    dist_norm = abs(float(np.dot(pt, norm_dir)) - c_val)
                    dist_along = float(np.dot(pt, prim_dir))
                    if dist_norm < 35.0 and rdata["s_min"] - 70.0 <= dist_along <= rdata["s_max"] + 70.0:
                        if dist_norm < best_dist:
                            best_dist = dist_norm
                            best_vid = rdata["vineyard_id"]
                if best_vid is not None:
                    canopy_assigned_vid[orig_idx] = best_vid

        # Assign block to each canopy polygon
        assigned_block_counts: Dict[str, int] = defaultdict(int)
        for i, (poly_coords, (cx, cy)) in enumerate(zip(canopy_polys, canopy_cents)):
            assigned_vid = canopy_assigned_vid.get(i)
            if assigned_vid is None:
                assigned_vid = assign_canopy_block(
                    r=r,
                    c=c,
                    px=cx,
                    py=cy,
                    tile_name=tname,
                    candidate_blocks=candidates,
                    block_centroids=block_centroids,
                    shared_tile_directions=shared_tile_directions,
                )

            tile_canopies_map[tname].append(
                VineyardCanopy(points=poly_coords, vineyard_id=assigned_vid)
            )
            assigned_block_counts[assigned_vid] += 1
            total_canopies_detected += 1

        if idx % 10 == 0 or idx == len(tiles_to_process):
            elapsed = time.time() - t_start
            rate = idx / elapsed
            remaining = (len(tiles_to_process) - idx) / (rate if rate > 0 else 1)
            print(
                f"[{idx:3d}/{len(tiles_to_process):3d}] {tname:22s} | "
                f"Canopies: {len(canopy_polys):3d} | "
                f"Blocks: {','.join(assigned_block_counts.keys()) or 'none':10s} | "
                f"Elapsed: {elapsed:5.1f}s | ETA: {remaining:5.1f}s"
            )

    print("-" * 70)
    print(f"Inference complete: {total_canopies_detected} total canopies in {time.time() - t_start:.1f}s.")

    # 5. Cross-Tile Global Row Stitching
    print("Performing global collinear row stitching across tile boundaries...")
    stitcher = GlobalRowStitcher(offset_tolerance_m=0.40)
    tile_stitched_rows: Dict[str, Dict[str, List[VineRow]]] = defaultdict(lambda: defaultdict(list))

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

    # 6. Apply Stitched Rows and Derive Quadrilateral Interrows
    print("Deriving straight quadrilateral inter-row corridors...")
    tile_final_rows: Dict[str, List[VineRow]] = defaultdict(list)
    tile_final_interrows: Dict[str, List[InterRowArea]] = defaultdict(list)

    total_rows = 0
    total_interrows = 0

    for tname in tiles_to_process:
        t_path = all_disk_tiles[tname]
        im_rgb = None
        try:
            im_rgb = np.array(Image.open(t_path).convert("RGB"))
        except Exception:
            im_rgb = None

        for vid, v_rows in tile_stitched_rows.get(tname, {}).items():
            tile_final_rows[tname].extend(v_rows)
            total_rows += len(v_rows)

            orig_meta = tile_block_row_data.get(tname, {}).get(vid, {}).get("meta", {})
            if orig_meta and len(v_rows) >= 2:
                normal_dir = orig_meta["normal_dir"]
                primary_dir = orig_meta["primary_dir"]
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
                        vineyard_id=vid,
                        image_rgb=im_rgb,
                        margin_px=args.margin_px,
                        tile_width=2048.0,
                        tile_height=2048.0,
                    )
                    tile_final_interrows[tname].extend(ir_quads)
                    total_interrows += len(ir_quads)

    # 7. Assemble CVAT 1.1 XML Writer
    print(f"Assembling CVAT XML ({total_canopies_detected} canopies, {total_rows} rows, {total_interrows} interrows)...")
    writer = CVATWriter(task_name="Vineyard AI Field Challenge", canopies_only=False)

    # Determine complete set of tiles for XML output
    if args.vineyard_only:
        output_tile_names = sorted(tiles_to_process)
    else:
        # Include all 311 challenge tiles in alphabetical order
        output_tile_names = sorted(list(all_disk_tiles.keys()))

    per_part_writers: Dict[str, CVATWriter] = defaultdict(
        lambda: CVATWriter(task_name="Vineyard AI Field Challenge", canopies_only=False)
    )

    for tname in output_tile_names:
        tile_ann = TileAnnotations(image_name=tname, width=2048, height=2048)
        if tname in tile_canopies_map:
            tile_ann.canopies = tile_canopies_map[tname]
        if tname in tile_final_rows:
            tile_ann.rows = tile_final_rows[tname]
        if tname in tile_final_interrows:
            tile_ann.interrows = tile_final_interrows[tname]

        writer.add_tile(tile_ann)

        # Add to per-part writer
        part_name = tile_part_map.get(tname, "default")
        per_part_writers[part_name].add_tile(
            TileAnnotations(
                image_name=tname,
                width=2048,
                height=2048,
                canopies=list(tile_ann.canopies),
                rows=list(tile_ann.rows),
                interrows=list(tile_ann.interrows),
            )
        )

    # Write master XML
    out_xml_path.parent.mkdir(parents=True, exist_ok=True)
    writer.write(str(out_xml_path))
    print(f"Master XML saved to: {out_xml_path.resolve()} ({out_xml_path.stat().st_size / (1024*1024):.2f} MB)")

    # Optionally write per-part XMLs
    if args.output_parts_dir:
        parts_dir = Path(args.output_parts_dir)
        parts_dir.mkdir(parents=True, exist_ok=True)
        print(f"Writing per-part XMLs into {parts_dir.resolve()}...")
        for part_name, p_writer in sorted(per_part_writers.items()):
            part_xml = parts_dir / f"annotations_{part_name}.xml"
            p_writer.write(str(part_xml))
            print(f"  Saved {part_xml.name} ({len(p_writer.tiles)} tiles)")

    # Optionally package upload ZIPs for Marcaj
    if args.create_zips:
        import zipfile
        zips_dir = Path(args.output_parts_dir or "exports") / "zips"
        zips_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nPackaging upload ZIPs for Marcaj in {zips_dir.resolve()}...")
        for part_name, p_writer in sorted(per_part_writers.items()):
            zip_path = zips_dir / f"{part_name}.zip"
            xml_content = p_writer.to_xml_string()
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                # 1. Add annotations.xml at archive root
                zf.writestr("annotations.xml", xml_content)
                # 2. Add image files under images/
                for t in p_writer.tiles:
                    src_img = all_disk_tiles[t.image_name]
                    zf.write(src_img, arcname=f"images/{src_img.name}")
            zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
            print(f"  Created {zip_path.name} ({zip_size_mb:.1f} MB, {len(p_writer.tiles)} tiles)")

    # 8. Validate Generated XML
    print("\nRunning comprehensive validation on generated annotations...")
    validation_passed = validate_annotations(str(out_xml_path))

    print("\n" + "=" * 70)
    print("Execution Summary:")
    print(f"Unique Vineyard Tiles:   {len(unique_tiles)}")
    print(f"Total Tiles in XML:      {len(writer.tiles)}")
    print(f"Total Canopies:          {total_canopies_detected}")
    print(f"Total Row Centerlines:   {total_rows}")
    print(f"Total Interrow Polygons: {total_interrows}")
    print(f"Validation Status:       {'SUCCESS (100% compliant)' if validation_passed else 'WARNING: check logs'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
