"""
Generate Marcaj CVAT for Images 1.1 annotations.xml from tile imagery.
Performs model inference to extract canopy coordinates, derives row centerlines
and inter-row polygons, and produces the final XML. Zero image files generated.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List

# Ensure repository root is on sys.path so script can be invoked from anywhere
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.pipeline import VineyardPipeline
from src.export.cvat_writer import CVATWriter


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run inference on tiles and generate Marcaj CVAT 1.1 XML."
    )
    parser.add_argument(
        "--source",
        type=str,
        default="assets/05_examples/siret3_examples_cvat/images",
        help="Path to a single .tif/.jpg file or a directory containing tiles",
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
        default="annotations.xml",
        help="Output XML file path (default: annotations.xml)",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=None,
        help="Confidence threshold (default: 0.28 for YOLO, 0.05 for RF-DETR)",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=2048,
        help="Image size for inference (default: 2048 native resolution)",
    )
    parser.add_argument(
        "--vineyard-id",
        type=str,
        default="V01",
        help="Block ID prefix (default: V01)",
    )
    parser.add_argument(
        "--canopies-only",
        action="store_true",
        default=False,
        help="Only export canopies (exclude rows and interrows)",
    )
    parser.add_argument(
        "--margin-px",
        type=float,
        default=12.0,
        help="Row canopy margin in pixels (default: 12.0 px = 0.30 m)",
    )
    parser.add_argument(
        "--save-json",
        type=str,
        default="",
        help="Optional path to dump raw extracted coordinates as JSON",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    source_path = Path(args.source)
    if not source_path.exists():
        raise FileNotFoundError(f"Source path not found: {source_path}")

    # Gather image files
    if source_path.is_file():
        tile_files = [source_path]
    else:
        tile_files = sorted(
            [f for f in source_path.iterdir() if f.suffix.lower() in [".tif", ".tiff", ".jpg", ".jpeg", ".png"]]
        )

    if not tile_files:
        print(f"No image files found in {source_path}")
        return

    is_rfdetr = str(args.weights).endswith(".pth") or "rfdetr" in str(args.weights).lower()
    conf = args.conf if args.conf is not None else (0.05 if is_rfdetr else 0.28)

    print("=" * 60)
    print("Marcaj CVAT 1.1 XML Generator")
    print(f"Model Weights: {args.weights}")
    print(f"Architecture:  {'RF-DETR-Seg' if is_rfdetr else 'YOLO-Seg'}")
    print(f"Source:        {args.source} ({len(tile_files)} tiles)")
    print(f"Confidence:    {conf} | ImgSz: {args.imgsz}")
    print(f"Canopies Only: {args.canopies_only} | Margin: {args.margin_px} px")
    print(f"Output XML:    {args.output}")
    print("=" * 60)

    # Initialize pipeline
    pipeline = VineyardPipeline(model_weights_path=args.weights)
    writer = CVATWriter(task_name="Vineyard AI Field Challenge", canopies_only=args.canopies_only)

    raw_coordinates_dump = {}

    tile_paths = [str(f) for f in tile_files]
    tile_annotations, targets = pipeline.process_batch(
        tile_paths=tile_paths,
        confidence=conf,
        imgsz=args.imgsz,
        extract_rows=not args.canopies_only,
        extract_interrows=not args.canopies_only,
        margin_px=args.margin_px,
        verbose=True,
    )

    for tile_ann in tile_annotations:
        writer.add_tile(tile_ann)
        if args.save_json:
            raw_coordinates_dump[tile_ann.image_name] = {
                "canopies": [
                    {"points": c.points, "vineyard_id": c.vineyard_id}
                    for c in tile_ann.canopies
                ]
            }

    # Write final CVAT 1.1 XML
    out_xml_path = Path(args.output)
    out_xml_path.parent.mkdir(parents=True, exist_ok=True)
    writer.write(str(out_xml_path))
    print("=" * 60)
    print(f"Successfully generated: {out_xml_path.resolve()}")

    # Optional JSON dump
    if args.save_json:
        out_json_path = Path(args.save_json)
        out_json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_json_path, "w", encoding="utf-8") as f:
            json.dump(raw_coordinates_dump, f, indent=2)
        print(f"Raw coordinates dumped to: {out_json_path.resolve()}")


if __name__ == "__main__":
    main()

