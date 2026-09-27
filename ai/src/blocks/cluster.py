"""Turn a vine mask into block territories.

Two plantings are one block when the non-vineyard gap is under 5 m.
A road or track (the passage layer) always splits blocks, even when it is
narrower than 5 m. The returned labels are the filled territory, so the
inter-row ground inside a block stays visible for the next model.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import binary_dilation, binary_fill_holes, label

_EIGHT = np.ones((3, 3), dtype=bool)


def build_territories(
    vine: np.ndarray,
    barrier: np.ndarray,
    valid: np.ndarray,
    gsd: float,
    gap_m: float = 5.0,
    min_vine_m2: float = 80.0,
    min_territory_m2: float = 200.0,
) -> np.ndarray:
    """Return int32 labels. 0 is background. Ids are temporary, not V01.. order."""
    free = valid & ~barrier
    grown = vine & free
    steps = int(np.floor((gap_m / 2.0) / gsd))
    for _ in range(steps):
        grown = binary_dilation(grown, structure=_EIGHT) & free

    raw, count = label(grown, structure=_EIGHT)
    if count == 0:
        return np.zeros(vine.shape, dtype=np.int32)

    pixel_area = gsd * gsd
    territories = np.zeros(vine.shape, dtype=np.int32)
    next_id = 1
    for old in range(1, count + 1):
        component = raw == old
        vine_area = float((component & vine).sum()) * pixel_area
        if vine_area < min_vine_m2:
            continue
        filled = binary_fill_holes(component) & free
        territory_area = float(filled.sum()) * pixel_area
        if territory_area < min_territory_m2:
            continue
        territories[filled] = next_id
        next_id += 1
    return territories


def order_blocks_north_west(
    labels: np.ndarray,
    origin_x: float,
    origin_y: float,
    gsd: float,
) -> tuple[np.ndarray, list[int]]:
    """Renumber labels V-order: northern centroid first, then western."""
    ids = [int(i) for i in np.unique(labels) if i != 0]
    ranked = []
    for old in ids:
        rows, cols = np.nonzero(labels == old)
        north = origin_y - float(rows.mean()) * gsd
        east = origin_x + float(cols.mean()) * gsd
        ranked.append((-north, east, old))
    ranked.sort()
    out = np.zeros_like(labels)
    order = []
    for new_id, (_, _, old) in enumerate(ranked, start=1):
        out[labels == old] = new_id
        order.append(new_id)
    return out, order
