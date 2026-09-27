"""Fine-tune YOLO26n detection on the prepared waste set.

batch is how many images the model sees before one weight update.
8 fits an M4 with 16 GB. Use 4 if the run is killed for memory.

    python -m waste.train
    python -m waste.train --dry-run
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ultralytics.utils.torch_utils import select_device

from waste.settings import (
    BATCH,
    EPOCHS,
    IMAGE_SIZE,
    PATIENCE,
    RUNS,
    SEED,
    WORKERS,
    YOLO_ROOT,
)

LOG = logging.getLogger("waste.train")


def dataset_yaml(root: Path) -> Path:
    path = root / "waste.yaml"
    if not path.is_file():
        raise SystemExit(f"Missing {path}. Run: python -m waste.prepare")
    return path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Train yolo26n to detect waste.")
    parser.add_argument("--data", type=Path, default=YOLO_ROOT)
    parser.add_argument("--model", default="yolo26n.pt")
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--imgsz", type=int, default=IMAGE_SIZE)
    parser.add_argument(
        "--batch",
        type=int,
        default=BATCH,
        help="Images per weight update. 8 fits 16 GB. Use 4 if memory runs out.",
    )
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument(
        "--device",
        default="mps",
        help="Passed to Ultralytics select_device. mps on this Mac, cpu, or a CUDA index.",
    )
    parser.add_argument("--patience", type=int, default=PATIENCE)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--name", default="waste26n")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    yaml_path = dataset_yaml(args.data)
    device = select_device(args.device, verbose=False)
    LOG.info("data %s", yaml_path)
    LOG.info("device %s  batch %d  imgsz %d  epochs %d", device, args.batch, args.imgsz, args.epochs)
    if args.dry_run:
        return

    from ultralytics import YOLO

    model = YOLO(args.model)
    model.train(
        data=str(yaml_path),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        workers=args.workers,
        cache=False,
        patience=args.patience,
        close_mosaic=10,
        seed=args.seed,
        device=args.device,
        project=str(RUNS),
        name=args.name,
        exist_ok=True,
        pretrained=True,
    )
    best = RUNS / args.name / "weights" / "best.pt"
    LOG.info("weights: %s", best)


if __name__ == "__main__":
    main()
