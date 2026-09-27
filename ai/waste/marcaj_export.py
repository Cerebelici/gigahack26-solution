"""Write one Marcaj upload per tile folder.

Each part becomes:

    waste/marcaj/<part>/
    ├── annotations.xml
    └── images/
        └── siret3_r005_c004.tif   # copy of the original, source file untouched

and waste/marcaj/<part>.zip with those same bytes. A tile is written
only when it has a waste box at confidence at least 0.90.

    python -m waste.marcaj_export
"""

from __future__ import annotations

import argparse
import logging
import shutil
import zipfile
from pathlib import Path

from waste.cvat import annotations_xml
from waste.predict import detect_tile
from waste.settings import BATCH, CONF, NMS_IOU, PACKAGE, REPO

LOG = logging.getLogger("waste.marcaj")
ZIP_LIMIT = 90_000_000


def tile_folders(root: Path) -> list[Path]:
    if not root.is_dir():
        raise SystemExit(f"Missing {root}")
    folders = [
        path
        for path in sorted(root.iterdir())
        if path.is_dir() and any(path.glob("*.tif"))
    ]
    if not folders:
        raise SystemExit(f"No tile folders with .tif files in {root}")
    return folders


def write_part(model, folder: Path, out: Path, conf: float, iou: float, device: str, batch: int) -> dict:
    tiles = sorted(folder.glob("*.tif"))
    part = out / folder.name
    images = part / "images"
    if part.exists():
        shutil.rmtree(part)
    images.mkdir(parents=True)

    records = []
    for tile in tiles:
        record = detect_tile(model, tile, conf, iou, device, batch)
        if not record["boxes"]:
            continue
        records.append(record)
        shutil.copy2(tile.resolve(), images / tile.name)
        LOG.info("%s  boxes=%d", tile.name, len(record["boxes"]))

    xml_path = part / "annotations.xml"
    xml_path.write_text(annotations_xml(records))

    zip_path = out / f"{folder.name}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.write(xml_path, "annotations.xml")
        for record in records:
            tile = folder / record["image"]
            archive.write(tile.resolve(), f"images/{tile.name}")

    boxes = sum(len(record["boxes"]) for record in records)
    size = zip_path.stat().st_size
    if size > ZIP_LIMIT:
        LOG.info("%s  zip=%d bytes, over the 90 MB Marcaj limit", folder.name, size)
    else:
        LOG.info("%s  images=%d  boxes=%d  zip=%d", folder.name, len(records), boxes, size)
    return {"images": len(records), "boxes": boxes, "zip": str(zip_path), "bytes": size}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Export waste boxes as Marcaj CVAT zips.")
    parser.add_argument("--weights", type=Path, default=PACKAGE / "best.pt")
    parser.add_argument("--tiles", type=Path, default=REPO / "assets" / "01_tiles")
    parser.add_argument("--out", type=Path, default=PACKAGE / "marcaj")
    parser.add_argument("--conf", type=float, default=CONF)
    parser.add_argument("--iou", type=float, default=NMS_IOU)
    parser.add_argument("--batch", type=int, default=BATCH)
    parser.add_argument("--device", default="mps")
    args = parser.parse_args()
    if not args.weights.is_file():
        raise SystemExit(f"Missing weights: {args.weights}")

    from ultralytics import YOLO
    from ultralytics.utils.torch_utils import select_device

    device = str(select_device(args.device, verbose=False))
    model = YOLO(str(args.weights))
    args.out.mkdir(parents=True, exist_ok=True)
    for folder in tile_folders(args.tiles):
        write_part(model, folder, args.out, args.conf, args.iou, device, args.batch)


if __name__ == "__main__":
    main()
