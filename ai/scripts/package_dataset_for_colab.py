"""
Helper utility to package training images and YOLO polygon labels into dataset.zip
for instant upload to Google Colab.
"""

import argparse
import zipfile
from pathlib import Path


def package_dataset(dataset_dir: str = "dataset", output_zip: str = "dataset.zip"):
    d_path = Path(dataset_dir)
    if not d_path.exists():
        print(f"Error: {d_path} does not exist.")
        return

    out_path = Path(output_zip)
    print(f"Packaging {d_path} into {out_path} for Google Colab...")

    file_count = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in d_path.rglob("*"):
            if f.is_file() and not f.name.startswith("."):
                arcname = f.relative_to(d_path)
                zf.write(f, arcname=str(arcname))
                file_count += 1

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"Successfully packaged {file_count} files into {out_path} ({size_mb:.2f} MB).")
    print("You can now drag and drop dataset.zip directly into Google Colab!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="dataset", help="Local dataset folder path")
    parser.add_argument("--output", default="dataset.zip", help="Output zip filename")
    args = parser.parse_args()
    package_dataset(args.data_dir, args.output)
