"""Detect vineyard blocks on the Sireț3 tiles and write one folder per block.

Install (once):

    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$PWD/.tools" UV_NO_MODIFY_PATH=1 sh
    .tools/uv python install 3.12
    .tools/uv venv --python 3.12 .venv
    .tools/uv pip install --python .venv/bin/python torch rasterio shapely numpy pillow scipy

Run:

    PYTHONPATH=. .venv/bin/python scripts/group_vineyard_blocks.py

Reads every siret3_r*_c*.tif under --tiles (extracted part folders or the five zips).
Writes output/vineyard_blocks/V01/block.xml and the tiles of that block, with
every pixel outside the block set to black.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from src.blocks.barriers import passage_barrier
from src.blocks.catalog import discover_tiles
from src.blocks.cluster import build_territories, order_blocks_north_west
from src.blocks.export import export_blocks, rasterize_records
from src.blocks.manual import stamp_manual_blocks
from src.blocks.mosaic import build_mosaic
from src.blocks.preview import save_preview, save_zone_map
from src.blocks.refine import refine_unmarked
from src.blocks.teacher import row_score, vine_mask
from src.blocks.train import load_model, pick_device, predict_proba, train_block_model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Group Sireț3 tiles into vineyard-block folders.")
    parser.add_argument("--tiles", type=Path, default=Path("assets/01_tiles"))
    parser.add_argument("--passages", type=Path, default=Path("assets/02_route/passages.geojson"))
    parser.add_argument("--output", type=Path, default=Path("output/vineyard_blocks"))
    parser.add_argument("--weights", type=Path, default=Path("weights/block_unet.pt"))
    parser.add_argument("--gsd", type=float, default=0.4, help="Coarse metres per pixel. Must divide 51.2.")
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--device", type=str, default="auto")
    parser.add_argument("--score-threshold", type=float, default=0.28)
    parser.add_argument("--peakiness-threshold", type=float, default=1.35)
    parser.add_argument("--prob-threshold", type=float, default=0.5)
    parser.add_argument(
        "--min-territory-m2",
        type=float,
        default=600.0,
        help="Drop plantings smaller than this.",
    )
    parser.add_argument("--fine-gsd", type=float, default=0.1, help="Only used with --refine.")
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--refine", action="store_true", help="Second pass at 10 cm. Off by default.")
    parser.add_argument("--preview-only", action="store_true", help="Write the check image and stop before training.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tiles = discover_tiles(args.tiles)
    print(f"Tiles found: {len(tiles)}")
    if not tiles:
        print("No siret3_r*_c*.tif files or zips under", args.tiles, file=sys.stderr)
        return 1
    parts = sorted({tile.path.parent.name for tile in tiles})
    print("Collections:", ", ".join(parts))

    print("Building coarse mosaic (resize + gray-world color balance)...")
    mosaic = build_mosaic(tiles, gsd=args.gsd)
    print(f"  mosaic {mosaic.rgb.shape[1]}x{mosaic.rgb.shape[0]} at {mosaic.gsd} m/px")

    print("Scoring row spacing near 2.7 m...")
    score, peakiness = row_score(mosaic.rgb, mosaic.valid, mosaic.gsd)
    teacher = vine_mask(score, peakiness, mosaic.valid, args.score_threshold, args.peakiness_threshold)
    vine_fraction = float(teacher[mosaic.valid].mean()) if mosaic.valid.any() else 0.0
    print(f"  teacher vine fraction on valid ground: {vine_fraction:.3f}")

    if args.preview_only:
        preview = args.output / "_detection_preview.png"
        save_preview(preview, mosaic.rgb, teacher, teacher.astype(np.int32))
        print("Preview:", preview.resolve())
        return 0

    device = pick_device(args.device)
    if args.skip_train and args.weights.exists():
        print("Loading", args.weights)
    else:
        print(f"Training block model on the teacher labels ({args.epochs} epochs, {device})...")
        train_block_model(
            mosaic.rgb,
            teacher.astype(np.float32),
            mosaic.valid,
            args.weights,
            epochs=args.epochs,
            chip=128 if mosaic.cells >= 128 else mosaic.cells,
            stride=64 if mosaic.cells >= 128 else max(mosaic.cells // 2, 1),
            device=device,
        )

    print("Predicting vineyard probability...")
    model, chip = load_model(args.weights, device)
    proba = predict_proba(model, mosaic.rgb, chip=chip, device=device)
    vine = (proba >= args.prob_threshold) & mosaic.valid
    print(f"  model vine fraction: {float(vine[mosaic.valid].mean()):.3f}")

    if args.refine:
        print("Rescanning unmarked ground at finer resolution...")
        extra = refine_unmarked(tiles, mosaic, vine, fine_gsd=args.fine_gsd)
        vine = vine | extra

    barrier = passage_barrier(
        args.passages,
        mosaic.rgb.shape[0],
        mosaic.rgb.shape[1],
        mosaic.origin_x,
        mosaic.origin_y,
        mosaic.gsd,
    )
    print(f"  passage barrier pixels: {int(barrier.sum())}")
    labels = build_territories(
        vine,
        barrier,
        mosaic.valid,
        mosaic.gsd,
        min_vine_m2=80.0,
        min_territory_m2=args.min_territory_m2,
    )
    labels, order = order_blocks_north_west(labels, mosaic.origin_x, mosaic.origin_y, mosaic.gsd)
    labels = stamp_manual_blocks(labels, mosaic.origin_x, mosaic.origin_y, mosaic.gsd)
    order = [int(i) for i in np.unique(labels) if i != 0]
    print(f"Blocks: {len(order)}")
    if not order:
        preview = args.output / "_detection_preview.png"
        save_preview(preview, mosaic.rgb, teacher, labels)
        print("No block passed the 5 m / area rules. Preview:", preview.resolve(), file=sys.stderr)
        return 1

    print("Writing masked tiles and XML...")
    records = export_blocks(labels, mosaic, tiles, args.output)
    smooth = rasterize_records(
        records,
        mosaic.rgb.shape[0],
        mosaic.rgb.shape[1],
        mosaic.origin_x,
        mosaic.origin_y,
        mosaic.gsd,
    )
    save_preview(args.output / "_detection_preview.png", mosaic.rgb, teacher, smooth)
    zone_map = args.output / "full_map.png"
    save_zone_map(zone_map, mosaic.rgb, smooth)
    print(f"Zone map: {zone_map.resolve()}")
    print(f"Done. {len(records)} blocks in {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
