"""
Prepares training crops (chips) from official Sireț3 annotated example tiles.
Crops 2048x2048 tiles into 1024x1024 chips and converts CVAT polygons into YOLO segmentation format.
"""

from pathlib import Path
from typing import List, Tuple
import numpy as np
from PIL import Image

from src.export.cvat_parser import parse_cvat_xml


CHIP_SIZE = 1024
STRIDE = 512  # 50% overlap


def crop_tile_with_annotations(
    img_path: str,
    tile_ann,
    output_img_dir: Path,
    output_lbl_dir: Path,
):
    with Image.open(img_path) as img:
        img_np = np.array(img.convert("RGB"))

    h, w = img_np.shape[:2]
    tile_stem = Path(img_path).stem

    # Iterate through grid of crops
    crop_idx = 0
    for y0 in range(0, h - CHIP_SIZE + 1, STRIDE):
        for x0 in range(0, w - CHIP_SIZE + 1, STRIDE):
            x1, y1 = x0 + CHIP_SIZE, y0 + CHIP_SIZE
            crop_img = img_np[y0:y1, x0:x1]

            # Collect canopies inside this crop
            chip_labels = []
            for canopy in tile_ann.canopies:
                pts = np.array(canopy.points)
                # Check if canopy is inside or mostly inside crop
                inside_x = (pts[:, 0] >= x0) & (pts[:, 0] <= x1)
                inside_y = (pts[:, 1] >= y0) & (pts[:, 1] <= y1)

                if np.any(inside_x & inside_y):
                    # Shift coordinates relative to crop and clamp
                    shifted_x = np.clip(pts[:, 0] - x0, 0, CHIP_SIZE) / CHIP_SIZE
                    shifted_y = np.clip(pts[:, 1] - y0, 0, CHIP_SIZE) / CHIP_SIZE

                    # Valid polygon needs at least 3 points and non-zero area
                    if len(shifted_x) >= 3:
                        poly_str = " ".join(
                            f"{float(x):.6f} {float(y):.6f}"
                            for x, y in zip(shifted_x, shifted_y)
                        )
                        # Class 2 in our dataset is 'trunk'/individual plant canopy
                        chip_labels.append(f"2 {poly_str}")

            # Save crop image and labels if it contains annotations
            if chip_labels:
                crop_idx += 1
                chip_name = f"{tile_stem}_crop_{crop_idx:02d}"
                Image.fromarray(crop_img).save(output_img_dir / f"{chip_name}.jpg", quality=95)
                with open(output_lbl_dir / f"{chip_name}.txt", "w") as f:
                    f.write("\n".join(chip_labels) + "\n")

    print(f"Generated {crop_idx} chips from {tile_stem}")


def main():
    example_xml = "assets/05_examples/siret3_examples_cvat/annotations.xml"
    tiles = parse_cvat_xml(example_xml)

    out_train_img = Path("dataset/train/images")
    out_train_lbl = Path("dataset/train/labels")
    out_train_img.mkdir(parents=True, exist_ok=True)
    out_train_lbl.mkdir(parents=True, exist_ok=True)

    img_dir = Path("assets/05_examples/siret3_examples_cvat/images")

    for tile in tiles:
        img_file = img_dir / tile.image_name
        if img_file.exists():
            crop_tile_with_annotations(
                img_path=str(img_file),
                tile_ann=tile,
                output_img_dir=out_train_img,
                output_lbl_dir=out_train_lbl,
            )


if __name__ == "__main__":
    main()

