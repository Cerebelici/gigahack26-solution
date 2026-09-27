"""Turn UAVVaste COCO labels into a YOLO detection set.

Uses the official train/val/test split shipped with the dataset.
Images are symlinked, not copied.

`convert_coco` is not used: it subtracts 1 from category_id, and UAVVaste ids
start at 0. It would also try to parse the split json that sits beside the
annotations. Box math is `ltwh2xyxy` and `xyxy2xywhn` from Ultralytics.

    python -m waste.prepare
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
from pathlib import Path

import numpy as np
from ultralytics.utils import YAML
from ultralytics.utils.ops import ltwh2xyxy, xyxy2xywhn

from waste.settings import CLASS_NAME, DATASET, YOLO_ROOT

LOG = logging.getLogger("waste.prepare")
SPLITS = ("train", "val", "test")


def yolo_row(bbox, width: int, height: int):
    """One YOLO label line, or None when the box has no area inside the image."""
    xyxy = ltwh2xyxy(np.asarray([bbox], dtype=np.float64))
    xywhn = np.asarray(xyxy2xywhn(xyxy, w=width, h=height, clip=True))[0]
    if xywhn[2] <= 0 or xywhn[3] <= 0:
        return None
    values = (0, *(float(v) for v in xywhn))
    return ("%g " * len(values) % values).rstrip()


def prepare(dataset: Path, out: Path) -> dict:
    ann_path = dataset / "annotations" / "annotations.json"
    split_path = dataset / "annotations" / "train_val_test_distribution_file.json"
    image_dir = dataset / "images"
    for path in (ann_path, split_path, image_dir):
        if not path.exists():
            raise SystemExit(f"Missing {path}")

    coco = json.loads(ann_path.read_text())
    split_file = json.loads(split_path.read_text())
    images = {im["file_name"]: im for im in coco["images"]}
    by_image = {}
    for ann in coco["annotations"]:
        by_image.setdefault(ann["image_id"], []).append(ann)

    assigned = []
    for name in SPLITS:
        if name not in split_file:
            raise SystemExit(f"Split file has no '{name}' list")
        assigned.extend(split_file[name])
    if len(assigned) != len(set(assigned)):
        raise SystemExit("Official split lists the same image twice")
    missing = set(images) - set(assigned)
    extra = set(assigned) - set(images)
    if missing or extra:
        raise SystemExit(
            f"Split does not match COCO images: missing {len(missing)}, extra {len(extra)}"
        )

    on_disk = {p.name: p for p in image_dir.iterdir() if p.is_file()}
    absent = [name for name in images if name not in on_disk]
    if absent:
        raise SystemExit(f"{len(absent)} COCO images are not in {image_dir}")

    for kind in ("images", "labels"):
        root = out / kind
        if root.exists():
            shutil.rmtree(root)

    stats = {}
    dropped = 0
    for split in SPLITS:
        img_out = out / "images" / split
        lbl_out = out / "labels" / split
        img_out.mkdir(parents=True)
        lbl_out.mkdir(parents=True)
        box_count = 0
        empty = 0
        for file_name in split_file[split]:
            im = images[file_name]
            src = on_disk[file_name]
            os.symlink(src.resolve(), img_out / file_name)
            lines = []
            for ann in by_image.get(im["id"], []):
                line = yolo_row(ann["bbox"], im["width"], im["height"])
                if line is None:
                    dropped += 1
                    continue
                lines.append(line)
            text = ("\n".join(lines) + "\n") if lines else ""
            (lbl_out / f"{src.stem}.txt").write_text(text)
            box_count += len(lines)
            empty += int(not lines)
        stats[split] = {
            "images": len(split_file[split]),
            "boxes": box_count,
            "empty": empty,
        }

    yaml_path = out / "waste.yaml"
    YAML.save(
        yaml_path,
        {
            "path": str(out.resolve()),
            "train": "images/train",
            "val": "images/val",
            "test": "images/test",
            "names": {0: CLASS_NAME},
        },
    )
    stats["yaml"] = str(yaml_path)
    stats["dropped_boxes"] = dropped
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Build the YOLO waste dataset from UAVVaste.")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--out", type=Path, default=YOLO_ROOT)
    args = parser.parse_args()
    stats = prepare(args.dataset, args.out)
    for split in SPLITS:
        row = stats[split]
        LOG.info(
            "%s  images=%d  boxes=%d  empty=%d",
            split,
            row["images"],
            row["boxes"],
            row["empty"],
        )
    LOG.info("dropped boxes: %d", stats["dropped_boxes"])
    LOG.info("yaml: %s", stats["yaml"])


if __name__ == "__main__":
    main()
