"""
Local fine-tuning script for YOLO segmentation on Apple Silicon MPS / CUDA.
Leverages unified dataset with aerial domain adaptation augmentations.
"""

import argparse
from pathlib import Path
import torch
from ultralytics import YOLO


def parse_args():
    parser = argparse.ArgumentParser(description="Fine-tune YOLO segmentation locally.")
    parser.add_argument(
        "--data",
        type=str,
        default="dataset_unified/dataset.yaml",
        help="Path to dataset.yaml",
    )
    parser.add_argument(
        "--weights",
        type=str,
        default="yolo26l-seg.pt",
        help="Base model checkpoint to fine-tune from (e.g. yolo26l-seg.pt, yolo26n-seg.pt)",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=20,
        help="Number of training epochs (default: 20)",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="Image size for training (default: 640)",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=4,
        help="Batch size (default: 4)",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="vineyard_yolo26l_unified",
        help="Run name",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")

    print("=" * 60)
    print("Local YOLO Segmentation Fine-Tuning")
    print(f"Device:       {device}")
    print(f"Base Weights: {args.weights}")
    print(f"Dataset:      {args.data}")
    print(f"Epochs:       {args.epochs} | ImgSz: {args.imgsz} | Batch: {args.batch}")
    print("=" * 60)

    model = YOLO(args.weights)

    # Domain adaptation hyper-parameters for aerial UAV orthomosaics:
    # - HSV jitter to bridge solar angle / shadows
    # - Scale jitter and affine flips
    # - Mosaic augmentation
    results = model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=device,
        name=args.name,
        hsv_h=0.025,
        hsv_s=0.7,
        hsv_v=0.5,
        degrees=15.0,
        scale=0.5,
        fliplr=0.5,
        flipud=0.5,
        mosaic=1.0,
        close_mosaic=5,
        workers=4,
        save=True,
    )

    save_dir = getattr(model.trainer, "save_dir", Path(f"runs/segment/{args.name}"))
    best_pt = Path(save_dir) / "weights" / "best.pt"
    if best_pt.exists():
        target_pt = Path("weights/best.pt")
        target_pt.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(best_pt, target_pt)

        # Also save architecture-specific best checkpoint
        if "yolo26l" in str(args.weights).lower() or "yolo26l" in str(args.name).lower():
            backup_pt = Path("weights/yolo26l_unified_best.pt")
        else:
            backup_pt = Path(f"weights/{args.name}_best.pt")
        shutil.copy2(best_pt, backup_pt)

        print("=" * 60)
        print(f"Trained model saved to {target_pt.resolve()} and {backup_pt.resolve()}")
        print("=" * 60)


if __name__ == "__main__":
    main()
