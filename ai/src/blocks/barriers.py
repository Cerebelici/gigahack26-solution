"""Rasterize passage polygons. A road or track always separates blocks."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.geometry import shape


def passage_barrier(path: Path, height: int, width: int, origin_x: float, origin_y: float, gsd: float) -> np.ndarray:
    if not path.exists():
        return np.zeros((height, width), dtype=bool)
    collection = json.loads(path.read_text())
    geoms = []
    for feature in collection.get("features", []):
        geometry = feature.get("geometry")
        if geometry:
            geoms.append(shape(geometry))
    if not geoms:
        return np.zeros((height, width), dtype=bool)
    transform = from_origin(origin_x, origin_y, gsd, gsd)
    burned = rasterize(
        [(geom, 1) for geom in geoms],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        dtype=np.uint8,
    )
    return burned.astype(bool)
