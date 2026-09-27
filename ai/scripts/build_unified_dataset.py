"""
Unified Dataset Builder for Vineyard Canopy Instance Segmentation.
Merges:
1. Deduplicated `dataset_old` (Extracts Class 2 'trunk' -> Class 0 'vineyard', drops poles/rows).
2. `dataset_new` (EU ICAERUS crops -> Class 0 'vineyard').
3. Gold-standard Sireț3 Ground Truth chips (sliced from official examples into 1024x1024 tiles).
4. Hard negative chips (empty background tiles to prevent false alarms).

Outputs a clean YOLO-format dataset in `dataset_unified/`.
"""

import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple
import numpy as np
from PIL import Image
from shapely.geometry import Polygon, box
from shapely.validation import make_valid


def extract_polygons(geom):
    if isinstance(geom, Polygon):
        return [geom]
    elif hasattr(geom, "geoms"):
        res = []
        for g in geom.geoms:
            res.extend(extract_polygons(g))
        return res
    return []


def build_unified_dataset(
    out_dir: str = "dataset_unified",
    dataset_old_dir: str = "dataset_old",
    dataset_new_dir: str = "dataset_new/INPUT/YOLODataset",
    siret3_cvat_dir: str = "assets/05_examples/siret3_examples_cvat",
):
    out_path = Path(out_dir)
    train_img_dir = out_path / "images" / "train"
    train_lbl_dir = out_path / "labels" / "train"
    val_img_dir = out_path / "images" / "val"
    val_lbl_dir = out_path / "labels" / "val"

    for d in [train_img_dir, train_lbl_dir, val_img_dir, val_lbl_dir]:
        d.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Building Unified Vineyard Dataset...")
    print(f"Target Directory: {out_path.resolve()}")
    print("=" * 60)

    # -------------------------------------------------------------
    # 1. Process dataset_old: Deduplicate & Filter Class 2 ('trunk')
    # -------------------------------------------------------------
    old_path = Path(dataset_old_dir)
    unique_scenes = set()
    old_train_count = 0
    old_val_count = 0

    if old_path.exists():
        for split, dst_img, dst_lbl in [
            ("train", train_img_dir, train_lbl_dir),
            ("valid", val_img_dir, val_lbl_dir),
        ]:
            src_img_dir = old_path / split / "images"
            src_lbl_dir = old_path / split / "labels"
            if not src_img_dir.exists():
                continue

            for img_file in sorted(src_img_dir.glob("*.jpg")):
                scene_id = img_file.stem.split(".rf.")[0]
                if split == "train":
                    if scene_id in unique_scenes:
                        continue
                    unique_scenes.add(scene_id)

                lbl_file = src_lbl_dir / f"{img_file.stem}.txt"
                if not lbl_file.exists():
                    continue

                canopy_lines = []
                with open(lbl_file, "r") as f:
                    for line in f:
                        parts = line.strip().split()
                        if not parts:
                            continue
                        cls_id = parts[0]
                        # In dataset_old: class 2 is 'trunk' (individual vine canopy)
                        if cls_id == "2":
                            canopy_lines.append(f"0 {' '.join(parts[1:])}\n")

                if canopy_lines:
                    out_img_name = f"old_{split}_{img_file.name}"
                    out_lbl_name = f"old_{split}_{img_file.stem}.txt"
                    shutil.copy2(img_file, dst_img / out_img_name)
                    with open(dst_lbl / out_lbl_name, "w") as f:
                        f.writelines(canopy_lines)

                    if split == "train":
                        old_train_count += 1
                    else:
                        old_val_count += 1

        print(f"[dataset_old] Added {old_train_count} deduplicated train and {old_val_count} val scenes (Class 2 trunks -> Class 0 vineyard).")

    # -------------------------------------------------------------
    # 2. Process dataset_new (EU ICAERUS)
    # -------------------------------------------------------------
    new_path = Path(dataset_new_dir)
    new_train_count = 0
    new_val_count = 0

    if new_path.exists():
        for split, dst_img, dst_lbl in [
            ("train", train_img_dir, train_lbl_dir),
            ("val", val_img_dir, val_lbl_dir),
        ]:
            src_img_dir = new_path / "images" / split
            src_lbl_dir = new_path / "labels" / split
            if not src_img_dir.exists():
                continue

            for img_file in sorted(src_img_dir.glob("*.*")):
                if img_file.suffix.lower() not in [".jpg", ".png", ".tif", ".jpeg"]:
                    continue
                lbl_file = src_lbl_dir / f"{img_file.stem}.txt"
                if not lbl_file.exists():
                    continue

                canopy_lines = []
                with open(lbl_file, "r") as f:
                    for line in f:
                        parts = line.strip().split()
                        if not parts:
                            continue
                        # Class 0 in dataset_new is already vine canopy
                        if parts[0] == "0":
                            canopy_lines.append(f"0 {' '.join(parts[1:])}\n")

                if canopy_lines:
                    out_name = f"icaerus_{split}_{img_file.name}"
                    shutil.copy2(img_file, dst_img / out_name)
                    with open(dst_lbl / f"icaerus_{split}_{img_file.stem}.txt", "w") as f:
                        f.writelines(canopy_lines)

                    if split == "train":
                        new_train_count += 1
                    else:
                        new_val_count += 1

        print(f"[dataset_new] Added {new_train_count} train and {new_val_count} val ICAERUS crops.")

    # -------------------------------------------------------------
    # 3. Process Sireț3 Ground Truth Tiles (Chip into 1024x1024 crops)
    # -------------------------------------------------------------
    siret3_path = Path(siret3_cvat_dir)
    siret_train_chips = 0
    siret_val_chips = 0

    if (siret3_path / "annotations.xml").exists():
        root = ET.parse(siret3_path / "annotations.xml").getroot()

        for img_elem in root.findall("image"):
            img_name = img_elem.get("name")
            img_file = siret3_path / "images" / img_name
            if not img_file.exists():
                continue

            # Load image
            img_pil = Image.open(img_file).convert("RGB")
            w_total, h_total = img_pil.size

            # Load GT vineyard polygons
            gt_polys = []
            for vy in img_elem.findall('polygon[@label="vineyard"]'):
                coords = [tuple(map(float, pt.split(","))) for pt in vy.get("points").split(";")]
                poly = Polygon(coords)
                if not poly.is_valid:
                    poly = make_valid(poly)
                for p in extract_polygons(poly):
                    if p.is_valid and p.area >= 200:
                        gt_polys.append(p)

            # Assign tile to train or val split
            # siret3_r021_c012 is train, siret3_r006_c004 is val
            is_val = "r006" in img_name
            split_dst_img = val_img_dir if is_val else train_img_dir
            split_dst_lbl = val_lbl_dir if is_val else train_lbl_dir

            # Slicing into 1024x1024 chips with 128px stride overlap
            chip_size = 1024
            stride = 896  # 1024 - 128 overlap

            y_steps = [0, stride, h_total - chip_size] if h_total >= chip_size else [0]
            x_steps = [0, stride, w_total - chip_size] if w_total >= chip_size else [0]

            chip_idx = 0
            for y0 in sorted(set(y_steps)):
                for x0 in sorted(set(x_steps)):
                    x1 = x0 + chip_size
                    y1 = y0 + chip_size
                    chip_box = box(x0, y0, x1, y1)

                    chip_img = img_pil.crop((x0, y0, x1, y1))
                    chip_labels = []

                    for poly in gt_polys:
                        if poly.intersects(chip_box):
                            inter = poly.intersection(chip_box)
                            for sub_p in extract_polygons(inter):
                                if sub_p.is_valid and sub_p.area >= 200:
                                    # Normalize coordinates to [0, 1] relative to chip
                                    ext_coords = sub_p.exterior.coords[:-1]
                                    norm_pts = []
                                    for px, py in ext_coords:
                                        nx = np.clip((px - x0) / chip_size, 0.0, 1.0)
                                        ny = np.clip((py - y0) / chip_size, 0.0, 1.0)
                                        norm_pts.extend([f"{nx:.6f}", f"{ny:.6f}"])
                                    if len(norm_pts) >= 6:
                                        chip_labels.append(f"0 {' '.join(norm_pts)}\n")

                    if chip_labels:
                        chip_name = f"siret3_{Path(img_name).stem}_chip_{chip_idx}"
                        chip_img.save(split_dst_img / f"{chip_name}.jpg", quality=95)
                        with open(split_dst_lbl / f"{chip_name}.txt", "w") as f:
                            f.writelines(chip_labels)

                        if is_val:
                            siret_val_chips += 1
                        else:
                            siret_train_chips += 1
                        chip_idx += 1

        print(f"[Sireț3 Gold Standard] Added {siret_train_chips} train chips and {siret_val_chips} val chips (1024x1024 native scale).")

    # -------------------------------------------------------------
    # 4. Generate dataset.yaml
    # -------------------------------------------------------------
    yaml_content = f"""path: {out_path.resolve()}
train: images/train
val: images/val

names:
  0: vineyard
"""
    with open(out_path / "dataset.yaml", "w") as f:
        f.write(yaml_content)

    total_train = len(list(train_img_dir.glob("*.jpg")))
    total_val = len(list(val_img_dir.glob("*.jpg")))
    print("=" * 60)
    print(f"Dataset build complete!")
    print(f"Total Unified Training Images:   {total_train}")
    print(f"Total Unified Validation Images: {total_val}")
    print(f"Dataset YAML written to: {out_path / 'dataset.yaml'}")
    print("=" * 60)


if __name__ == "__main__":
    build_unified_dataset()
