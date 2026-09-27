"""
Generate Marcaj CVAT 1.1 XML and the whole-map deliverables from file1.txt.

Reads vineyard_id/file_name pairings from file1.txt, runs YOLO26L inference on
all unique vineyard tiles (cached), extracts per-tile row segments, then rebuilds
the vineyard as a whole in EPSG:32635 (src/spatial/unify.py): segments are linked
across tile edges into physical rows, refitted from all their vines, numbered per
block, and inter-rows are derived between neighbouring rows. Rows and inter-rows
are cut back to tiles so every piece of a row carries one row_id and the pieces
meet at the tile edge.

Outputs: master + per-part CVAT XML (+ Marcaj ZIPs), whole-map GeoJSON layers
(blocks, rows, inter-rows, canopies, inspection targets), measurements.csv and
route.geojson.
"""

import argparse
import csv
import json
import sys
import time
from collections import defaultdict, Counter
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Set
import cv2
import numpy as np
from PIL import Image
from shapely.geometry import LineString, Polygon, mapping
from shapely.ops import unary_union

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
    GSD,
    parse_tile_indices,
    pixel_to_map,
    tile_upper_left,
    TILE_SIZE_M,
)
from src.spatial.row_extractor import extract_rows_from_canopies, partition_canopies_by_orientation
from src.spatial.interrow import classify_interrow_cover
from src.spatial.block_cluster import load_passages_geometry
from src.spatial.unify import (
    TileSegment,
    RowIndex,
    block_polygons,
    build_interrows,
    build_physical_rows,
    cut_polygons_to_tiles,
    cut_rows_to_tiles,
    drop_isolated_rows,
    link_segments,
    merge_collinear_rows,
    reattach_canopies,
    regroup_blocks,
    split_at_clearings,
    split_rows_at_passages,
    suppress_parallel_duplicates,
    number_rows,
)
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
    parser.add_argument("--canopy-cache", type=str, default="exports/cache/canopies.json",
                        help="JSON cache of per-tile canopy polygons ('' disables)")
    parser.add_argument("--reuse-cache", action="store_true", default=False,
                        help="Skip inference and read canopies from --canopy-cache")
    parser.add_argument("--unified-dir", type=str, default="exports/unified",
                        help="Directory for whole-map GeoJSON layers (EPSG:32635)")
    parser.add_argument("--measurements", type=str, default="measurements.csv")
    parser.add_argument("--route", type=str, default="route.geojson")
    parser.add_argument("--skip-route", action="store_true", default=False)
    parser.add_argument("--passages", type=str, default="assets/02_route/passages.geojson")
    parser.add_argument("--forbidden", type=str, default="assets/02_route/forbidden.geojson")
    parser.add_argument("--link-lateral-m", type=float, default=0.6,
                        help="Max lateral offset when linking row segments across a tile edge (m)")
    parser.add_argument("--link-gap-m", type=float, default=30.0,
                        help="Max along-row gap bridged when linking row segments (m)")
    parser.add_argument("--row-end-margin-m", type=float, default=0.5,
                        help="Row axis runs this far past the first and last vine (m)")
    parser.add_argument("--split-clearings", action="store_true", default=False,
                        help="Also cut rows where a gap lines up with gaps in the neighbouring rows "
                             "(tracks missing from passages.geojson). Over-splits sparse blocks.")
    parser.add_argument("--min-row-m", type=float, default=1.5,
                        help="Drop physical rows shorter than this (m)")
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




# ---------------------------------------------------------------------------
# Stage 1: canopy inference (cached)
# ---------------------------------------------------------------------------

def run_canopy_inference(args, tiles_to_process, all_disk_tiles) -> Dict[str, List[List[Tuple[float, float]]]]:
    """YOLO canopy polygons per tile, deduplicated. Cached to JSON so the
    whole-map post-processing can be re-run without the model."""
    cache_path = Path(args.canopy_cache) if args.canopy_cache else None
    if cache_path and args.reuse_cache and cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if all(t in cached for t in tiles_to_process):
            print(f"Loaded canopy cache: {cache_path} ({len(cached)} tiles)")
            return {t: [[tuple(p) for p in poly] for poly in cached[t]] for t in tiles_to_process}
        print("Canopy cache is missing tiles; running inference.")

    pipeline = VineyardPipeline(model_weights_path=args.weights)
    if args.device:
        pipeline.device = args.device

    tile_polys: Dict[str, List[List[Tuple[float, float]]]] = {}
    t_start = time.time()
    for idx, tname in enumerate(tiles_to_process, start=1):
        results = pipeline.model.predict(
            str(all_disk_tiles[tname]),
            conf=args.conf,
            imgsz=args.imgsz,
            max_det=1500,
            device=pipeline.device,
            verbose=False,
        )[0]

        raw_candidates: List[Tuple[float, List[Tuple[float, float]]]] = []
        if results.masks is not None:
            confs = (
                results.boxes.conf.cpu().numpy()
                if results.boxes is not None and results.boxes.conf is not None
                else [1.0] * len(results.masks.xy)
            )
            for mask, conf in zip(results.masks.xy, confs):
                for poly_coords in separate_canopy_polygon(
                    mask,
                    min_dist_px=40.0,
                    min_area_px=args.min_area_px,
                    max_area_px=args.max_area_px,
                    simplify_tol=1.0,
                ):
                    raw_candidates.append((float(conf), poly_coords))

        tile_polys[tname] = nms_canopy_polygons(
            raw_candidates,
            iou_thresh=0.25,
            iomin_thresh=0.35,
            min_dist_px=25.0,
            min_area_px=args.min_area_px,
            max_area_px=args.max_area_px,
        )

        if idx % 10 == 0 or idx == len(tiles_to_process):
            elapsed = time.time() - t_start
            print(f"[{idx:3d}/{len(tiles_to_process):3d}] {tname:22s} | canopies {len(tile_polys[tname]):4d} | {elapsed:6.1f}s")

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({t: [[list(p) for p in poly] for poly in polys] for t, polys in tile_polys.items()}))
        print(f"Canopy cache saved: {cache_path}")
    return tile_polys


def load_rgb(path: Path) -> Optional[np.ndarray]:
    try:
        return np.array(Image.open(path).convert("RGB"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Stage 2: per-tile row segments
# ---------------------------------------------------------------------------

def extract_tile_segments(
    tname: str,
    canopy_polys: List[List[Tuple[float, float]]],
    candidates: List[str],
    im_rgb: Optional[np.ndarray],
    block_centroids,
    shared_tile_directions,
) -> Tuple[List[TileSegment], List[str]]:
    """
    Row segments seen on one tile (map coordinates) and a first-guess block id
    for every canopy. The block guess is refined later from the whole-map rows.
    """
    r, c = parse_tile_indices(tname)
    canopy_cents = [
        (float(Polygon(p).centroid.x), float(Polygon(p).centroid.y)) for p in canopy_polys
    ]
    segments: List[TileSegment] = []
    canopy_vid: Dict[int, str] = {}

    for sub_cents, sub_indices, _ in partition_canopies_by_orientation(canopy_cents, min_angle_diff=25.0):
        if len(sub_cents) < 2:
            continue
        _, _, meta = extract_rows_from_canopies(
            canopy_centroids=sub_cents,
            vineyard_id=candidates[0],
            tile_width=2048,
            tile_height=2048,
            min_vines_per_row=2,
            return_metadata=True,
            image_rgb=im_rgb,
            headland_margin_px=60.0,
        )
        if not (meta and meta.get("rows_data")):
            continue

        # Group rows into connected plantings (spacing <= 160 px / 4 m), one block vote each
        rows_data = sorted(meta["rows_data"], key=lambda rd: rd["c_val"])
        plantings = [[rows_data[0]]]
        for prev, cur in zip(rows_data[:-1], rows_data[1:]):
            if cur["c_val"] - prev["c_val"] <= 160.0:
                plantings[-1].append(cur)
            else:
                plantings.append([cur])

        for pl in plantings:
            if len(candidates) == 1:
                vid = candidates[0]
            else:
                votes = [
                    assign_canopy_block(r, c, px, py, tname, candidates, block_centroids, shared_tile_directions)
                    for rd in pl for px, py in rd["cluster"]
                ]
                vid = Counter(votes).most_common(1)[0][0] if votes else candidates[0]
            for rd in pl:
                rd["vineyard_id"] = vid
                p0, p1 = rd["points"][0], rd["points"][-1]
                segments.append(TileSegment(
                    tile_name=tname,
                    block_id=vid,
                    p0=pixel_to_map(r, c, *p0),
                    p1=pixel_to_map(r, c, *p1),
                    vines=np.array([pixel_to_map(r, c, px, py) for px, py in rd["cluster"]]),
                ))

        normal_dir, prim_dir = meta["normal_dir"], meta["primary_dir"]
        for orig_idx in sub_indices:
            pt = np.array(canopy_cents[orig_idx])
            best = None
            for rd in meta["rows_data"]:
                dn = abs(float(np.dot(pt, normal_dir)) - rd["c_val"])
                da = float(np.dot(pt, prim_dir))
                if dn < 35.0 and rd["s_min"] - 70.0 <= da <= rd["s_max"] + 70.0 and (best is None or dn < best[0]):
                    best = (dn, rd["vineyard_id"])
            if best is not None:
                canopy_vid[orig_idx] = best[1]

    vids = [
        canopy_vid.get(i) or assign_canopy_block(r, c, cx, cy, tname, candidates, block_centroids, shared_tile_directions)
        for i, (cx, cy) in enumerate(canopy_cents)
    ]
    return segments, vids


# ---------------------------------------------------------------------------
# Outputs: GeoJSON layers, measurements, route
# ---------------------------------------------------------------------------

def _fc(name: str, features: List[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "name": name,
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32635"}},
        "features": features,
    }


def _geom(g) -> dict:
    return mapping(g)


def write_geojson(path: Path, name: str, features: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_fc(name, features)))
    print(f"  Saved {path} ({len(features)} features)")


def main():
    args = parse_args()
    file1_path = Path(args.file1)
    tiles_dir = Path(args.tiles_dir)
    out_xml_path = Path(args.output)
    unified_dir = Path(args.unified_dir)

    print("=" * 70)
    print("Marcaj CVAT 1.1 XML Generator (whole-map unification)")
    print(f"Mapping File:     {file1_path.resolve()}")
    print(f"Tiles Directory:  {tiles_dir.resolve()}")
    print(f"Model Weights:    {args.weights}")
    print(f"Output XML:       {out_xml_path.resolve()}")
    print(f"Unified layers:   {unified_dir.resolve()}")
    print("=" * 70)
    t_all = time.time()

    tile_to_blocks, block_to_tiles = load_file1_mapping(str(file1_path))
    unique_tiles = sorted(tile_to_blocks.keys())
    print(f"Identified {len(unique_tiles)} unique vineyard tiles across {len(block_to_tiles)} blocks.")

    all_disk_tiles, tile_part_map = find_all_challenge_tiles(str(tiles_dir))
    print(f"Found {len(all_disk_tiles)} total .tif tiles across challenge directories.")
    missing = [t for t in unique_tiles if t not in all_disk_tiles]
    if missing:
        raise FileNotFoundError(f"{len(missing)} tiles from {file1_path.name} were not found on disk: {missing[:5]}")

    block_centroids, shared_tile_directions = compute_block_reference_geometry(block_to_tiles)
    tiles_to_process = unique_tiles[:args.limit] if args.limit is not None else unique_tiles

    # 1. Canopies per tile
    t0 = time.time()
    tile_polys = run_canopy_inference(args, tiles_to_process, all_disk_tiles)
    t_infer = time.time() - t0

    # 2. Per-tile row segments + first-guess canopy blocks
    print("Extracting per-tile row segments...")
    segments: List[TileSegment] = []
    canopy_guess: Dict[str, List[str]] = {}
    images: Dict[str, Optional[np.ndarray]] = {}
    for tname in tiles_to_process:
        im = load_rgb(all_disk_tiles[tname])
        images[tname] = im
        segs, vids = extract_tile_segments(
            tname, tile_polys[tname], tile_to_blocks[tname], im, block_centroids, shared_tile_directions
        )
        segments.extend(segs)
        canopy_guess[tname] = vids
    print(f"  {len(segments)} tile segments on {len(tiles_to_process)} tiles")

    # 3. Whole-map rows
    print("Linking segments across tile edges into physical rows...")
    passages = load_passages_geometry(args.passages)
    chains = link_segments(segments, passages=passages, lateral_tol_m=args.link_lateral_m, max_gap_m=args.link_gap_m)
    rows = build_physical_rows(segments, chains, end_margin_m=args.row_end_margin_m)
    n_chained = len(rows)
    rows = merge_collinear_rows(rows, passages=passages, end_margin_m=args.row_end_margin_m)
    n_merged = len(rows)
    rows = split_rows_at_passages(rows, passages, end_margin_m=args.row_end_margin_m)
    rows = [r for r in rows if r.length_m >= args.min_row_m]
    rows = suppress_parallel_duplicates(rows)
    rows = drop_isolated_rows(rows)
    all_cents = []
    for tname in tiles_to_process:
        r_, c_ = parse_tile_indices(tname)
        for p in tile_polys[tname]:
            cp = Polygon(p).centroid
            all_cents.append(pixel_to_map(r_, c_, cp.x, cp.y))
    rows = reattach_canopies(rows, np.array(all_cents), end_margin_m=args.row_end_margin_m)
    n_clear = 0
    if args.split_clearings:
        rows, n_clear = split_at_clearings(rows, end_margin_m=args.row_end_margin_m)
        rows = [r for r in rows if r.length_m >= args.min_row_m]
    block_origin = regroup_blocks(rows, passages=passages)
    n_noise = sum(1 for r in rows if not r.vineyard_id)
    rows = [r for r in rows if r.vineyard_id]
    renamed = {k: v for k, v in block_origin.items() if k != v}
    print(f"  {n_clear} row cuts at clearings; {n_noise} isolated 1-2 row groups dropped; "
          f"{len(block_origin)} blocks from connected rows"
          + (f" (split from file1 blocks: {renamed})" if renamed else ""))
    print(f"  rows: {n_chained} from chains -> {n_merged} after collinear merge -> {len(rows)} after road split and noise filter")
    frames = number_rows(rows)
    multi = sum(1 for ch in chains if len({segments[i].tile_name for i in ch}) > 1)
    print(f"  {len(chains)} chains ({multi} cross a tile edge) -> {len(rows)} physical rows in {len(frames)} blocks")

    # 4. Whole-map inter-rows
    interrows = build_interrows(rows, frames, margin_m=args.margin_px * GSD)
    print(f"  {len(interrows)} whole-map inter-row polygons")

    # 5. Canopies: block from the row they stand in
    row_index = RowIndex(rows)
    tile_canopies_map: Dict[str, List[VineyardCanopy]] = defaultdict(list)
    canopy_records = []  # (tile, map polygon, vid, row index)
    for tname in tiles_to_process:
        r, c = parse_tile_indices(tname)
        polys = tile_polys[tname]
        if not polys:
            continue
        cents = []
        for p in polys:
            cp = Polygon(p).centroid
            cents.append(pixel_to_map(r, c, cp.x, cp.y))
        cents = np.array(cents)
        in_row = row_index.nearest(cents, max_dist_m=1.0)
        near = row_index.nearest(cents, max_dist_m=10.0)
        for k, poly in enumerate(polys):
            ridx = int(in_row[k])
            if ridx >= 0:
                vid = rows[ridx].vineyard_id
            elif near[k] >= 0:
                vid = rows[int(near[k])].vineyard_id
            else:
                vid = canopy_guess[tname][k]
            tile_canopies_map[tname].append(VineyardCanopy(points=poly, vineyard_id=vid))
            canopy_records.append((tname, Polygon([pixel_to_map(r, c, x, y) for x, y in poly]), vid, ridx))

    # 6. Cut back to tiles
    valid_tiles = set(all_disk_tiles.keys())
    row_pieces = cut_rows_to_tiles(rows, valid_tiles)
    ir_pieces = cut_polygons_to_tiles([ir.polygon for ir in interrows], valid_tiles)

    tile_final_rows: Dict[str, List[VineRow]] = defaultdict(list)
    for tname, pieces in row_pieces.items():
        for pc in pieces:
            row = rows[pc.owner]
            tile_final_rows[tname].append(VineRow(
                points=pc.points, vineyard_id=row.vineyard_id, row_id=row.row_id, row_structure=pc.row_structure,
            ))

    tile_final_interrows: Dict[str, List[InterRowArea]] = defaultdict(list)
    cover_votes: Dict[int, Counter] = defaultdict(Counter)
    for tname, pieces in ir_pieces.items():
        im = images.get(tname)
        if im is None and tname in all_disk_tiles:
            im = load_rgb(all_disk_tiles[tname])
        for pc in pieces:
            cover = classify_interrow_cover(pc.points, im)
            ir = interrows[pc.owner]
            cover_votes[pc.owner][cover] += Polygon(pc.points).area
            tile_final_interrows[tname].append(InterRowArea(points=pc.points, vineyard_id=ir.vineyard_id, interrow_cover=cover))
    for k, ir in enumerate(interrows):
        if cover_votes[k]:
            ir.interrow_cover = cover_votes[k].most_common(1)[0][0]

    n_row_pieces = sum(len(v) for v in tile_final_rows.values())
    n_ir_pieces = sum(len(v) for v in tile_final_interrows.values())
    n_canopies = sum(len(v) for v in tile_canopies_map.values())

    # 7. CVAT XML (master + per part + zips)
    print(f"Assembling CVAT XML ({n_canopies} canopies, {n_row_pieces} row pieces, {n_ir_pieces} inter-row pieces)...")
    writer = CVATWriter(task_name="Vineyard AI Field Challenge", canopies_only=False)
    if args.vineyard_only:
        output_tile_names = sorted(set(tiles_to_process) | set(tile_final_rows) | set(tile_final_interrows))
    else:
        output_tile_names = sorted(all_disk_tiles.keys())

    per_part_writers: Dict[str, CVATWriter] = defaultdict(
        lambda: CVATWriter(task_name="Vineyard AI Field Challenge", canopies_only=False)
    )
    for tname in output_tile_names:
        kwargs = dict(
            canopies=list(tile_canopies_map.get(tname, [])),
            rows=list(tile_final_rows.get(tname, [])),
            interrows=list(tile_final_interrows.get(tname, [])),
        )
        writer.add_tile(TileAnnotations(image_name=tname, width=2048, height=2048, **kwargs))
        per_part_writers[tile_part_map.get(tname, "default")].add_tile(
            TileAnnotations(image_name=tname, width=2048, height=2048, **kwargs)
        )

    out_xml_path.parent.mkdir(parents=True, exist_ok=True)
    writer.write(str(out_xml_path))
    print(f"Master XML saved to: {out_xml_path.resolve()} ({out_xml_path.stat().st_size / (1024*1024):.2f} MB)")

    if args.output_parts_dir:
        parts_dir = Path(args.output_parts_dir)
        parts_dir.mkdir(parents=True, exist_ok=True)
        for part_name, p_writer in sorted(per_part_writers.items()):
            part_xml = parts_dir / f"annotations_{part_name}.xml"
            p_writer.write(str(part_xml))
            print(f"  Saved {part_xml.name} ({len(p_writer.tiles)} tiles)")

    if args.create_zips:
        import zipfile
        zips_dir = Path(args.output_parts_dir).parent / "zips" if args.output_parts_dir else Path("exports/zips")
        zips_dir.mkdir(parents=True, exist_ok=True)
        print(f"\nPackaging upload ZIPs for Marcaj in {zips_dir.resolve()}...")
        for part_name, p_writer in sorted(per_part_writers.items()):
            zip_path = zips_dir / f"{part_name}.zip"
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("annotations.xml", p_writer.to_xml_string())
                for t in p_writer.tiles:
                    src_img = all_disk_tiles[t.image_name]
                    zf.write(src_img, arcname=f"images/{src_img.name}")
            print(f"  Created {zip_path.name} ({zip_path.stat().st_size / (1024 * 1024):.1f} MB, {len(p_writer.tiles)} tiles)")

    # 8. Whole-map layers for the web app and the route
    print(f"\nWriting whole-map layers to {unified_dir}...")
    tiles_of_row: Dict[int, List[str]] = defaultdict(list)
    for tname, pieces in row_pieces.items():
        for pc in pieces:
            tiles_of_row[pc.owner].append(tname)

    row_canopy_n: Dict[int, int] = Counter()
    row_canopy_a: Dict[int, float] = defaultdict(float)
    for _, g, _, ridx in canopy_records:
        if ridx >= 0:
            row_canopy_n[ridx] += 1
            row_canopy_a[ridx] += g.area
    row_ir_area: Dict[str, float] = defaultdict(float)
    for ir in interrows:
        for rid in ir.row_ids:
            row_ir_area[rid] += 0.5 * ir.polygon.area

    targets = []
    row_features = []
    for k, row in enumerate(rows):
        gaps = row.gaps()
        line = row.line
        for g0, g1 in gaps:
            p = line.interpolate(0.5 * (g0 + g1))
            targets.append({
                "target_id": f"T{len(targets) + 1:04d}",
                "type": "row_gap",
                "vineyard_id": row.vineyard_id,
                "row_id": row.row_id,
                "gap_m": round(g1 - g0, 2),
                "x": round(p.x, 2),
                "y": round(p.y, 2),
            })
        all_gaps = np.diff(row.vine_s) if len(row.vine_s) > 1 else np.array([0.0])
        row_features.append({
            "type": "Feature",
            "properties": {
                "row_id": row.row_id,
                "vineyard_id": row.vineyard_id,
                "length_m": round(row.length_m, 2),
                "row_structure": "disrupted" if gaps else "regular",
                "gap_count": len(gaps),
                "max_gap_m": round(float(all_gaps.max()), 2),
                "vine_count": len(row.vines),
                "canopy_count": row_canopy_n.get(k, 0),
                "canopy_area_m2": round(row_canopy_a.get(k, 0.0), 2),
                "tile_count": len(set(tiles_of_row.get(k, []))),
                "tiles": sorted(set(tiles_of_row.get(k, []))),
            },
            "geometry": _geom(LineString([(round(x, 3), round(y, 3)) for x, y in row.coords])),
        })
    write_geojson(unified_dir / "rows.geojson", "siret3_rows", row_features)

    write_geojson(unified_dir / "interrows.geojson", "siret3_interrows", [
        {
            "type": "Feature",
            "properties": {
                "interrow_id": ir.interrow_id,
                "vineyard_id": ir.vineyard_id,
                "between_rows": list(ir.row_ids),
                "interrow_cover": ir.interrow_cover,
                "area_m2": round(ir.polygon.area, 2),
            },
            "geometry": _geom(ir.polygon.simplify(0.005)),
        }
        for ir in interrows
    ])

    canopy_by_block = defaultdict(list)
    for tname, g, vid, _ in canopy_records:
        canopy_by_block[vid].append(g)
    write_geojson(unified_dir / "canopies.geojson", "siret3_canopies", [
        {
            "type": "Feature",
            "properties": {"vineyard_id": vid, "tile": tname, "area_m2": round(g.area, 3)},
            "geometry": _geom(g),
        }
        for tname, g, vid, _ in canopy_records
    ])

    block_outline = block_polygons(rows, interrows)
    rows_by_block = defaultdict(list)
    for row in rows:
        rows_by_block[row.vineyard_id].append(row)
    ir_by_block = defaultdict(list)
    for ir in interrows:
        ir_by_block[ir.vineyard_id].append(ir)

    block_stats = {}
    for vid in sorted(set(rows_by_block) | set(canopy_by_block)):
        b_rows = rows_by_block.get(vid, [])
        canopy_union = unary_union(canopy_by_block.get(vid, [])) if canopy_by_block.get(vid) else None
        block_stats[vid] = {
            "vineyard_id": vid,
            "row_count": len(b_rows),
            "total_row_length_m": round(sum(r.length_m for r in b_rows), 2),
            "disrupted_rows": sum(1 for r in b_rows if r.gaps()),
            "gap_count": sum(len(r.gaps()) for r in b_rows),
            "canopy_count": len(canopy_by_block.get(vid, [])),
            "canopy_area_m2": round(canopy_union.area, 2) if canopy_union is not None else 0.0,
            "interrow_count": len(ir_by_block.get(vid, [])),
            "interrow_area_m2": round(sum(ir.polygon.area for ir in ir_by_block.get(vid, [])), 2),
            "block_area_m2": round(block_outline[vid].area, 2) if vid in block_outline else 0.0,
        }
    write_geojson(unified_dir / "blocks.geojson", "siret3_blocks", [
        {"type": "Feature", "properties": block_stats[vid], "geometry": _geom(block_outline[vid])}
        for vid in sorted(block_outline)
    ])

    write_geojson(unified_dir / "targets.geojson", "siret3_inspection_targets", [
        {"type": "Feature", "properties": t, "geometry": {"type": "Point", "coordinates": [t["x"], t["y"]]}}
        for t in targets
    ])

    # measurements.csv: one line per row, one per block, one total
    csv_path = Path(args.measurements)
    fields = [
        "level", "vineyard_id", "row_id", "row_count", "row_length_m", "row_structure", "gap_count",
        "canopy_count", "canopy_area_m2", "canopy_area_ha", "interrow_area_m2", "interrow_area_ha",
        "block_area_m2", "block_area_ha", "tile_count",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for feat in sorted(row_features, key=lambda x: x["properties"]["row_id"]):
            p = feat["properties"]
            ira = row_ir_area.get(p["row_id"], 0.0)
            w.writerow({
                "level": "row", "vineyard_id": p["vineyard_id"], "row_id": p["row_id"], "row_count": 1,
                "row_length_m": p["length_m"], "row_structure": p["row_structure"], "gap_count": p["gap_count"],
                "canopy_count": p["canopy_count"], "canopy_area_m2": p["canopy_area_m2"],
                "canopy_area_ha": round(p["canopy_area_m2"] / 1e4, 4),
                "interrow_area_m2": round(ira, 2), "interrow_area_ha": round(ira / 1e4, 4),
                "tile_count": p["tile_count"],
            })
        for vid, b in sorted(block_stats.items()):
            w.writerow({
                "level": "block", "vineyard_id": vid, "row_id": "", "row_count": b["row_count"],
                "row_length_m": b["total_row_length_m"], "row_structure": "", "gap_count": b["gap_count"],
                "canopy_count": b["canopy_count"], "canopy_area_m2": b["canopy_area_m2"],
                "canopy_area_ha": round(b["canopy_area_m2"] / 1e4, 4),
                "interrow_area_m2": b["interrow_area_m2"], "interrow_area_ha": round(b["interrow_area_m2"] / 1e4, 4),
                "block_area_m2": b["block_area_m2"], "block_area_ha": round(b["block_area_m2"] / 1e4, 4),
            })
        tot = {k: sum(b[k] for b in block_stats.values()) for k in
               ("row_count", "total_row_length_m", "gap_count", "canopy_count", "canopy_area_m2", "interrow_area_m2", "block_area_m2")}
        w.writerow({
            "level": "total", "vineyard_id": f"{len(block_stats)} blocks", "row_id": "", "row_count": tot["row_count"],
            "row_length_m": round(tot["total_row_length_m"], 2), "row_structure": "", "gap_count": tot["gap_count"],
            "canopy_count": tot["canopy_count"], "canopy_area_m2": round(tot["canopy_area_m2"], 2),
            "canopy_area_ha": round(tot["canopy_area_m2"] / 1e4, 4),
            "interrow_area_m2": round(tot["interrow_area_m2"], 2), "interrow_area_ha": round(tot["interrow_area_m2"] / 1e4, 4),
            "block_area_m2": round(tot["block_area_m2"], 2), "block_area_ha": round(tot["block_area_m2"] / 1e4, 4),
        })
    print(f"  Saved {csv_path}")

    # 9. Walking route over passages + whole-map inter-rows
    if not args.skip_route:
        from src.routing.solver import RouteSolver
        print(f"\nSolving walking route over {len(targets)} inspection targets...")
        t_r = time.time()
        solver = RouteSolver(passages_geojson=args.passages, forbidden_geojson=args.forbidden)
        solver.add_interrow_corridors([ir.polygon for ir in interrows])
        route_coords, length_m, visited = solver.solve_route([(t["x"], t["y"]) for t in targets])
        solver.export_geojson(route_coords, length_m, visited, len(targets), output_path=args.route)
        print(f"  Saved {args.route}: {length_m} m, {visited}/{len(targets)} targets within 2 m ({time.time() - t_r:.1f}s)")

    print("\nRunning validation on generated annotations...")
    validation_passed = validate_annotations(str(out_xml_path))

    print("\n" + "=" * 70)
    print("Execution Summary:")
    print(f"Vineyard tiles processed: {len(tiles_to_process)} (inference {t_infer:.1f}s)")
    print(f"Tiles in XML:             {len(writer.tiles)}")
    print(f"Blocks:                   {len(block_stats)}")
    print(f"Physical rows:            {len(rows)} ({n_row_pieces} per-tile pieces, {multi} chains cross tile edges)")
    print(f"Total row length:         {sum(r.length_m for r in rows):.1f} m")
    print(f"Inter-rows:               {len(interrows)} whole-map ({n_ir_pieces} per-tile pieces)")
    print(f"Canopies:                 {n_canopies}")
    print(f"Inspection targets:       {len(targets)}")
    print(f"Total time:               {time.time() - t_all:.1f}s")
    print(f"Validation Status:        {'PASSED' if validation_passed else 'WARNING: check logs'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
