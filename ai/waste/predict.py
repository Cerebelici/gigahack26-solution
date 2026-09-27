"""Run the waste detector.

UAVVaste photos are predicted whole, the same way they were trained.
Sireț3 tiles are 2048 px at 2.5 cm/px, so they are cut into 640 px windows.
Ultralytics has no sliced predict. Overlapping windows are merged with
torchvision.ops.nms.

    python -m waste.predict --weights waste/runs/waste26n/weights/best.pt --source path/to/tiles
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import List, Sequence, Tuple

import numpy as np
import torch
from torchvision.ops import nms
from ultralytics.data.utils import IMG_FORMATS
from ultralytics.utils.torch_utils import select_device

from waste.settings import CONF, IMAGE_SIZE, NMS_IOU, STRIDE, WINDOW

LOG = logging.getLogger("waste.predict")
Found = Tuple[float, float, float, float, float]


def window_origins(length: int, size: int, stride: int) -> List[int]:
    """Origins along one axis. The last window sits on the far edge."""
    if length <= size:
        return [0]
    starts = list(range(0, length - size + 1, stride))
    last = length - size
    if starts[-1] != last:
        starts.append(last)
    return starts


def list_images(source: Path) -> List[Path]:
    if source.is_file():
        return [source]
    files = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix[1:].lower() in IMG_FORMATS
    )
    if not files:
        raise SystemExit(f"No images in {source}")
    return files


def read_rgb(path: Path) -> np.ndarray:
    """HxWx3 uint8. GeoTIFF goes through rasterio so YCbCr JPEG tiles stay RGB."""
    if path.suffix.lower() in {".tif", ".tiff"}:
        try:
            import rasterio
        except ImportError as exc:
            raise SystemExit(
                "GeoTIFF tiles need rasterio. Install it with: pip install rasterio"
            ) from exc
        with rasterio.open(path) as src:
            data = src.read()
        if data.shape[0] < 3:
            raise SystemExit(f"{path.name} has {data.shape[0]} bands, expected 3")
        rgb = np.transpose(data[:3], (1, 2, 0))
        if rgb.dtype != np.uint8:
            rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        return rgb

    import cv2

    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise SystemExit(f"Could not read {path}")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def shift_boxes(result, origin_x: int, origin_y: int) -> List[Found]:
    if result.boxes is None or len(result.boxes) == 0:
        return []
    xyxy = result.boxes.xyxy.cpu()
    xyxy = xyxy + torch.tensor([origin_x, origin_y, origin_x, origin_y])
    conf = result.boxes.conf.cpu()
    return [
        (float(x1), float(y1), float(x2), float(y2), float(score))
        for (x1, y1, x2, y2), score in zip(xyxy.tolist(), conf.tolist())
    ]


def merge_windows(found: Sequence[Found], iou: float) -> List[Found]:
    if not found:
        return []
    boxes = torch.tensor([box[:4] for box in found], dtype=torch.float32)
    scores = torch.tensor([box[4] for box in found], dtype=torch.float32)
    keep = nms(boxes, scores, iou)
    return [found[i] for i in keep.tolist()]


def predict_windows(model, image: np.ndarray, conf: float, device: str, batch: int):
    height, width = image.shape[:2]
    crops = []
    origins = []
    for y in window_origins(height, WINDOW, STRIDE):
        for x in window_origins(width, WINDOW, STRIDE):
            crop = image[y : y + WINDOW, x : x + WINDOW]
            if int(crop.max()) < 8:
                continue
            crops.append(crop)
            origins.append((x, y))
    if not crops:
        return []
    results = model.predict(
        crops,
        imgsz=IMAGE_SIZE,
        conf=conf,
        iou=NMS_IOU,
        device=device,
        batch=batch,
        verbose=False,
    )
    found: List[Found] = []
    for result, (x, y) in zip(results, origins):
        found.extend(shift_boxes(result, x, y))
    return found


def save_preview(image: np.ndarray, kept: Sequence[Found], dest: Path) -> None:
    """Write a JPEG with the merged boxes drawn on the tile."""
    import cv2

    bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    for x1, y1, x2, y2, score in kept:
        p1 = (int(round(x1)), int(round(y1)))
        p2 = (int(round(x2)), int(round(y2)))
        cv2.rectangle(bgr, p1, p2, (0, 255, 0), 2)
        cv2.putText(
            bgr,
            f"{score:.2f}",
            (p1[0], max(12, p1[1] - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            1,
            cv2.LINE_AA,
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), bgr)


def detect_tile(model, path: Path, conf: float, iou: float, device: str, batch: int) -> dict:
    """Waste boxes for one GeoTIFF. The file on disk is not modified."""
    image = read_rgb(path)
    height, width = image.shape[:2]
    found = predict_windows(model, image, conf, device, batch)
    kept = merge_windows(found, iou)
    return to_record(path, width, height, kept)


def to_record(path: Path, width: int, height: int, kept: Sequence[Found]) -> dict:
    return {
        "image": path.name,
        "width": width,
        "height": height,
        "boxes": [
            {
                "label": "waste",
                "xtl": round(x1, 2),
                "ytl": round(y1, 2),
                "xbr": round(x2, 2),
                "ybr": round(y2, 2),
                "conf": round(score, 4),
            }
            for x1, y1, x2, y2, score in kept
        ],
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Predict waste boxes.")
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("waste/predictions"))
    parser.add_argument("--conf", type=float, default=CONF)
    parser.add_argument("--iou", type=float, default=NMS_IOU)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="mps")
    parser.add_argument(
        "--layout",
        choices=("auto", "windows", "resize"),
        default="auto",
        help="windows cuts 2048 px tiles. resize scores a whole UAVVaste photo.",
    )
    args = parser.parse_args()
    if not args.weights.is_file():
        raise SystemExit(f"Missing weights: {args.weights}")

    from ultralytics import YOLO

    device = str(select_device(args.device, verbose=False))
    model = YOLO(str(args.weights))
    args.out.mkdir(parents=True, exist_ok=True)
    records = []
    for path in list_images(args.source):
        layout = args.layout
        if layout == "auto":
            layout = "windows" if path.suffix.lower() in {".tif", ".tiff"} else "resize"
        if layout == "resize" and path.suffix.lower() not in {".tif", ".tiff"}:
            results = model.predict(
                str(path),
                imgsz=IMAGE_SIZE,
                conf=args.conf,
                iou=args.iou,
                device=device,
                verbose=False,
            )
            image_h, image_w = results[0].orig_shape
            kept = shift_boxes(results[0], 0, 0)
            image = read_rgb(path)
        else:
            image = read_rgb(path)
            image_h, image_w = image.shape[:2]
            if layout == "windows":
                found = predict_windows(model, image, args.conf, device, args.batch)
                kept = merge_windows(found, args.iou)
            else:
                results = model.predict(
                    image,
                    imgsz=IMAGE_SIZE,
                    conf=args.conf,
                    iou=args.iou,
                    device=device,
                    verbose=False,
                )
                kept = shift_boxes(results[0], 0, 0)
        record = to_record(path, image_w, image_h, kept)
        records.append(record)
        if image is not None:
            save_preview(image, kept, args.out / "images" / f"{path.stem}.jpg")
        LOG.info("%s  boxes=%d  layout=%s", path.name, len(record["boxes"]), layout)

    out_path = args.out / "predictions.json"
    out_path.write_text(json.dumps(records, indent=2) + "\n")
    LOG.info("wrote %s", out_path)
    LOG.info("images: %s", args.out / "images")


if __name__ == "__main__":
    main()
