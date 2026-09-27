"""Paths and training defaults for the waste detector.

The dataset stays in Downloads. This package only writes labels, symlinks, and runs.
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parent

DATASET = Path(
    os.environ.get(
        "WASTE_DATASET",
        "/Users/stepancovanji/Downloads/UAVVasteDataset",
    )
)
YOLO_ROOT = Path(os.environ.get("WASTE_YOLO", str(PACKAGE / "data")))
RUNS = PACKAGE / "runs"

CLASS_NAME = "waste"
IMAGE_SIZE = 640
WINDOW = 640
STRIDE = 512

# 8 images per weight update fits 16 GB unified memory on an M4.
# Drop to 4 if the process is killed.
BATCH = 8
EPOCHS = 80
PATIENCE = 15
WORKERS = 2
SEED = 0
# Solution decision 2026-09-26: drop anything below 0.90.
CONF = 0.90
NMS_IOU = 0.5
