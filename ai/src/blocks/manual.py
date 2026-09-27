"""Hand-added vineyard blocks the row detector skipped.

Coordinates are EPSG:32635 metres, tile pixel-is-area corners from the grid formula.
"""

from __future__ import annotations

import numpy as np
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.geometry import Polygon

# Sparse rows beside the grey-roof house on siret3_r013_c009.
# The planting fills that tile south of the house and continues a short way
# into siret3_r014_c009. There is no tile to the east, so the photo ends in black.
HOUSE_VINEYARD = (
    (629460.0, 5220546.0),
    (629504.0, 5220546.0),
    (629504.0, 5220492.0),
    (629460.0, 5220492.0),
)

MANUAL_RINGS = (HOUSE_VINEYARD,)


def stamp_manual_blocks(labels: np.ndarray, origin_x: float, origin_y: float, gsd: float) -> np.ndarray:
    """Paint hand polygons onto background cells. Existing block ids stay put."""
    transform = from_origin(origin_x, origin_y, gsd, gsd)
    out = labels.copy()
    next_id = int(out.max()) + 1
    for ring in MANUAL_RINGS:
        burned = rasterize(
            [(Polygon(ring), 1)],
            out_shape=out.shape,
            transform=transform,
            fill=0,
            dtype=np.uint8,
        )
        added = (burned == 1) & (out == 0)
        if not added.any():
            continue
        out[added] = next_id
        print(f"  manual block {next_id}: {float(added.sum()) * gsd * gsd:.0f} m²")
        next_id += 1
    return out
