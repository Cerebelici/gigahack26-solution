"""
Dataset preparation script for Google Colab training.
Processes the newly included vineyard dataset (EU ICAERUS vine segmentation)
and packages it into lightweight, ready-to-upload ZIP archives:
  1. dataset_yolo.zip  (~28 MB) -> For YOLO26 / YOLO11 segmentation
  2. dataset_coco.zip  (~28 MB) -> For RF-DETR-Seg (Large/Medium)
"""

import argparse
import glob
import json
import os
import shutil
import zipfile
from pathlib import Path
from PIL import Image


def convert_yolo_to_coco(images_dir: Path, labels_dir: Path, output_json: Path, split_name: str):
    images = []
    annotations = []
    categories = [{"id": 0, "name": "vine", "supercategory": "none"}]

    img_files = sorted(list(images_dir.glob("*.png")) + list(images_dir.glob("*.jpg")))
    ann_id = 1

    for img_id, img_path in enumerate(img_files, start=1):
        with Image.open(img_path) as im:
            w, h = im.size

        images.append({
            "id": img_id,
            "file_name": img_path.name,
            "width": w,
            "height": h,
        })

        label_path = labels_dir / f"{img_path.stem}.txt"
        if not label_path.exists():
            continue

        with open(label_path, "r", encoding="utf-8") as lf:
            for line in lf:
                parts = line.strip().split()
                if len(parts) < 7:  # class + at least 3 points (6 floats)
                    continue

                cls_id = int(parts[0])
                coords = [float(x) for x in parts[1:]]

                # Denormalize coordinates to absolute pixel values
                pixel_coords = []
                xs = []
                ys = []
                for i in range(0, len(coords), 2):
                    px = round(coords[i] * w, 2)
                    py = round(coords[i + 1] * h, 2)
                    pixel_coords.extend([px, py])
                    xs.append(px)
                    ys.append(py)

                min_x = max(0.0, min(xs))
                min_y = max(0.0, min(ys))
                max_x = min(float(w), max(xs))
                max_y = min(float(h), max(ys))
                box_w = max_x - min_x
                box_h = max_y - min_y
                area = round(box_w * box_h, 2)

                annotations.append({
                    "id": ann_id,
                    "image_id": img_id,
                    "category_id": 0,
                    "segmentation": [pixel_coords],
                    "area": float(area),
                    "bbox": [round(min_x, 2), round(min_y, 2), round(box_w, 2), round(box_h, 2)],
                    "iscrowd": 0,
                })
                ann_id += 1

    coco_data = {
        "images": images,
        "annotations": annotations,
        "categories": categories,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(coco_data, f)

    print(f"[{split_name.upper()}] Converted {len(images)} images and {len(annotations)} vine polygons -> {output_json}")
    return len(images), len(annotations)


def build_yolo_archive(src_dir: Path, output_zip: Path):
    print(f"\nBuilding YOLO dataset archive: {output_zip}...")
    temp_dir = Path("/tmp/yolo_colab_staging")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    # Copy images and labels
    shutil.copytree(src_dir / "images" / "train", temp_dir / "images" / "train")
    shutil.copytree(src_dir / "images" / "val", temp_dir / "images" / "val")
    shutil.copytree(src_dir / "labels" / "train", temp_dir / "labels" / "train")
    shutil.copytree(src_dir / "labels" / "val", temp_dir / "labels" / "val")

    # Write clean data.yaml for Google Colab
    yaml_content = (
        "path: /content/dataset\n"
        "train: images/train\n"
        "val: images/val\n"
        "\n"
        "names:\n"
        "  0: vine\n"
    )
    with open(temp_dir / "data.yaml", "w", encoding="utf-8") as f:
        f.write(yaml_content)

    # Zip
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in temp_dir.rglob("*"):
            if f.is_file() and not f.name.startswith("."):
                zf.write(f, arcname=str(f.relative_to(temp_dir)))

    shutil.rmtree(temp_dir)
    size_mb = output_zip.stat().st_size / (1024 * 1024)
    print(f"YOLO archive ready: {output_zip} ({size_mb:.2f} MB)")


def build_coco_archive(src_dir: Path, output_zip: Path):
    print(f"\nBuilding RF-DETR COCO dataset archive: {output_zip}...")
    temp_dir = Path("/tmp/coco_colab_staging")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    train_out = temp_dir / "train"
    val_out = temp_dir / "valid"
    train_out.mkdir(parents=True)
    val_out.mkdir(parents=True)

    # Convert annotations
    convert_yolo_to_coco(
        src_dir / "images" / "train",
        src_dir / "labels" / "train",
        train_out / "_annotations.coco.json",
        "train",
    )
    convert_yolo_to_coco(
        src_dir / "images" / "val",
        src_dir / "labels" / "val",
        val_out / "_annotations.coco.json",
        "valid",
    )

    # Copy images directly into train and valid directories
    for img in (src_dir / "images" / "train").glob("*.png"):
        shutil.copy2(img, train_out / img.name)
    for img in (src_dir / "images" / "val").glob("*.png"):
        shutil.copy2(img, val_out / img.name)

    # Zip
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in temp_dir.rglob("*"):
            if f.is_file() and not f.name.startswith("."):
                zf.write(f, arcname=str(f.relative_to(temp_dir)))

    shutil.rmtree(temp_dir)
    size_mb = output_zip.stat().st_size / (1024 * 1024)
    print(f"COCO archive ready: {output_zip} ({size_mb:.2f} MB)")


def main():
    parser = argparse.ArgumentParser(description="Package vineyard dataset for Google Colab.")
    parser.add_argument(
        "--source-dir",
        default="dataset/INPUT/YOLODataset",
        help="Path to YOLODataset folder containing images/ and labels/",
    )
    parser.add_argument("--yolo-out", default="dataset_yolo.zip", help="Output YOLO zip archive")
    parser.add_argument("--coco-out", default="dataset_coco.zip", help="Output COCO zip archive")
    args = parser.parse_args()

    src = Path(args.source_dir)
    if not src.exists():
        raise FileNotFoundError(f"Source directory {src} does not exist.")

    print(f"Packaging dataset from: {src}")
    build_yolo_archive(src, Path(args.yolo_out))
    build_coco_archive(src, Path(args.coco_out))
    print("\nAll datasets packaged successfully! Both zip files are ready for Google Colab.")


if __name__ == "__main__":
    main()
