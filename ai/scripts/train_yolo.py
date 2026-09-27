"""
Ultralytics YOLO Segmentation Training Script for Vineyard Challenge.
Supports Apple Silicon GPU ('mps') or CPU/CUDA.
"""

import argparse
import os
import shutil
from pathlib import Path
import torch
from ultralytics import YOLO


def parse_args():
    parser = argparse.ArgumentParser(description="Train YOLO segmentation model for vineyards.")
    parser.add_argument("--model", type=str, default="yolo11n-seg.pt", help="Base model weights (e.g. yolo11n-seg.pt, yolo11s-seg.pt)")
    parser.add_argument("--data", type=str, default="dataset/vineyard_data.yaml", help="Path to data.yaml")
    parser.add_argument("--epochs", type=int, default=50, help="Number of training epochs")
    parser.add_argument("--imgsz", type=int, default=1024, help="Image size for training")
    parser.add_argument("--batch", type=int, default=8, help="Batch size")
    parser.add_argument("--device", type=str, default="", help="Device: 'mps', '0', 'cpu' (auto-detected if empty)")
    parser.add_argument("--workers", type=int, default=2, help="DataLoader workers")
    parser.add_argument("--project", type=str, default="models", help="Save directory")
    parser.add_argument("--name", type=str, default="vineyard_seg", help="Experiment name")
    return parser.parse_args()


def main():
    args = parse_args()

    # Auto-detect device
    if not args.device:
        if torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "0"
        else:
            device = "cpu"
    else:
        device = args.device

    print("=" * 60)
    print(f"Vineyard Segmentation Training")
    print(f"Model:   {args.model}")
    print(f"Dataset: {args.data}")
    print(f"Epochs:  {args.epochs} | ImgSz: {args.imgsz} | Batch: {args.batch}")
    print(f"Device:  {device}")
    print(f"Save:    {args.project}/{args.name}")
    print("=" * 60)

    # Load model
    model = YOLO(args.model)

    # Train
    results = model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=device,
        workers=args.workers,
        project=args.project,
        name=args.name,
        save=True,
        plots=True,
        exist_ok=True,
    )

    save_dir = Path(results.save_dir)
    best_pt = save_dir / "weights" / "best.pt"
    if best_pt.exists():
        weights_dir = Path("weights")
        weights_dir.mkdir(parents=True, exist_ok=True)
        dest = weights_dir / "best.pt"
        shutil.copy(best_pt, dest)
        print(f"\nTraining Complete!")
        print(f"Best weights copied to: {dest.resolve()}")
    else:
        print(f"\nWarning: {best_pt} not found.")


if __name__ == "__main__":
    main()

