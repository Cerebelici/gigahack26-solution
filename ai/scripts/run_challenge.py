"""
Master End-to-End Pipeline for Vineyard AI Field Challenge (Deeptech GigaHack 2026).
Executes the full pipeline from raw GeoTIFF tiles to:
1. annotations.xml (Marcaj CVAT for images 1.1 format)
2. measurements.csv (exact agronomic lengths, canopy/interrow areas in m^2 and ha)
3. route.geojson (valid TSP walking route visiting gaps >= 5m and waste)
4. Optional Marcaj upload ZIP packaging (<= 90 MB per ZIP)
"""

import argparse
import sys
import time
import zipfile
from pathlib import Path
from typing import List

# Ensure repository root is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.pipeline import VineyardPipeline
from src.export.cvat_writer import CVATWriter
from src.metrics.measurements import MeasurementsCalculator
from src.routing.solver import RouteSolver
from src.spatial.grid import pixel_to_map, parse_tile_indices
from shapely.geometry import Polygon


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run end-to-end Vineyard AI pipeline for challenge submission."
    )
    parser.add_argument(
        "--tiles-dir",
        type=str,
        default="assets/05_examples/siret3_examples_cvat/images",
        help="Path to directory containing input GeoTIFF tiles",
    )
    parser.add_argument(
        "--weights",
        type=str,
        default="weights/best.pt",
        help="Path to trained YOLO26 model weights (default: weights/best.pt)",
    )
    parser.add_argument(
        "--output-xml",
        type=str,
        default="annotations.xml",
        help="Output CVAT XML path (default: annotations.xml)",
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default="measurements.csv",
        help="Output measurements CSV path (default: measurements.csv)",
    )
    parser.add_argument(
        "--output-route",
        type=str,
        default="route.geojson",
        help="Output route GeoJSON path (default: route.geojson)",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.28,
        help="Confidence threshold for YOLO26 canopy segmentation (default: 0.28)",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=1024,
        help="Inference image resolution (default: 1024)",
    )
    parser.add_argument(
        "--package-zip",
        action="store_true",
        help="Also package into Marcaj upload ZIP (annotations.xml + images/)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    t_start = time.time()

    tiles_dir = Path(args.tiles_dir)
    if not tiles_dir.exists():
        raise FileNotFoundError(f"Tiles directory does not exist: {tiles_dir}")

    # Gather tile files
    tile_files = sorted(
        [f for f in tiles_dir.iterdir() if f.suffix.lower() in [".tif", ".tiff", ".jpg", ".jpeg", ".png"]]
    )
    if not tile_files:
        print(f"No tile images found in {tiles_dir}")
        return

    print("=" * 70)
    print(" Vineyard AI Field Challenge — End-to-End Execution Pipeline")
    print(f" Input Tiles:      {len(tile_files)} files from {tiles_dir}")
    print(f" YOLO26 Weights:   {args.weights}")
    print(f" Device / Arch:    Apple Silicon MPS / YOLO26-Seg")
    print("=" * 70)

    # 1. Pipeline Inference & Spatial Post-Processing
    print("\n[Step 1/4] Running YOLO26 segmentation and global spatial post-processing...")
    pipeline = VineyardPipeline(model_weights_path=args.weights)
    tile_paths = [str(f) for f in tile_files]
    tile_annotations, targets = pipeline.process_batch(
        tile_paths=tile_paths,
        confidence=args.conf,
        imgsz=args.imgsz,
        verbose=True,
    )

    # 2. Export CVAT 1.1 annotations.xml
    print(f"\n[Step 2/4] Generating Marcaj CVAT 1.1 XML -> {args.output_xml}...")
    writer = CVATWriter(task_name="Vineyard AI Field Challenge — Sireț3")
    for tile_ann in tile_annotations:
        writer.add_tile(tile_ann)
    out_xml = Path(args.output_xml)
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    writer.write(str(out_xml))
    print(f"  ✓ Saved annotations.xml: {out_xml.resolve()}")

    # 3. Compute Agronomic Measurements & Export CSV
    print(f"\n[Step 3/4] Computing physical measurements -> {args.output_csv}...")
    calc = MeasurementsCalculator(gsd=0.025)
    row_metrics, stats = calc.compute_metrics(tile_annotations)
    out_csv = Path(args.output_csv)
    calc.export_csv(row_metrics, stats, output_csv_path=str(out_csv))
    print(f"  ✓ Saved measurements.csv: {out_csv.resolve()}")
    print(f"    • Vineyard Blocks:    {stats['block_count']}")
    print(f"    • Physical Rows:      {stats['row_count']}")
    print(f"    • Total Row Length:   {stats['total_row_length_m']} m ({stats['total_row_length_km']} km)")
    print(f"    • Total Canopies:     {stats['total_canopy_count']} plants")
    print(f"    • Canopy Area:        {stats['total_canopy_area_m2']} m² ({stats['total_canopy_area_ha']} ha)")
    print(f"    • Inter-Row Area:     {stats['total_interrow_area_m2']} m² ({stats['total_interrow_area_ha']} ha)")

    # 4. Solve Optimal Walking Route & Export GeoJSON
    print(f"\n[Step 4/4] Solving walking route visiting {len(targets)} targets -> {args.output_route}...")
    solver = RouteSolver(
        passages_geojson="assets/02_route/passages.geojson",
        forbidden_geojson="assets/02_route/forbidden.geojson",
    )

    # Collect global interrow polygons to add corridors
    global_interrows = []
    for tile_ann in tile_annotations:
        try:
            r, c = parse_tile_indices(tile_ann.image_name)
            for ir in tile_ann.interrows:
                if len(ir.points) >= 3:
                    g_pts = [pixel_to_map(r, c, px, py) for px, py in ir.points]
                    global_interrows.append(Polygon(g_pts))
        except Exception:
            pass

    if global_interrows:
        solver.add_interrow_corridors(global_interrows)

    route_coords, length_m, visited = solver.solve_route(targets)
    out_route = Path(args.output_route)
    solver.export_geojson(
        route_coords=route_coords,
        total_length_m=length_m,
        visited_count=visited,
        total_target_count=len(targets),
        output_path=str(out_route),
    )
    print(f"  ✓ Saved route.geojson: {out_route.resolve()}")
    print(f"    • Route Length:       {length_m} m")
    print(f"    • Targets Visited:    {visited}/{len(targets)} ({100.0 * visited / max(1, len(targets)):.1f}%)")
    print(f"    • Start Point:        {route_coords[0]}")
    print(f"    • End Point:          {route_coords[-1]}")

    # Optional Marcaj ZIP packaging
    if args.package_zip:
        zip_path = Path("upload_submission.zip")
        print(f"\nPackaging into Marcaj upload ZIP -> {zip_path}...")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(out_xml, arcname="annotations.xml")
            for tf in tile_files:
                zf.write(tf, arcname=f"images/{tf.name}")
        print(f"  ✓ Submission ZIP created: {zip_path.resolve()} ({zip_path.stat().st_size / 1024 / 1024:.2f} MB)")

    total_time = time.time() - t_start
    print("\n" + "=" * 70)
    print(f" Execution Finished in {total_time:.2f} seconds ({total_time / len(tile_files):.2f} s/tile)")
    print(" All required submission deliverables successfully produced.")
    print("=" * 70)


if __name__ == "__main__":
    main()
