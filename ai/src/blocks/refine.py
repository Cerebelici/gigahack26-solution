"""Second pass at 10 cm on ground the coarse map left blank.

A vine row is about 2.7 m apart. At 40 cm that is only ~7 pixels, so pale and
young rows disappear. At 10 cm the same row is ~27 pixels. Tiles already
covered by a coarse detection are skipped.
"""

from __future__ import annotations

import numpy as np

from src.blocks.catalog import TileSource
from src.blocks.mosaic import CoarseMosaic, build_mosaic
from src.blocks.teacher import row_score, vine_mask
from src.spatial.grid import parse_tile_indices


def refine_unmarked(
    tiles: list[TileSource],
    mosaic: CoarseMosaic,
    vine: np.ndarray,
    fine_gsd: float = 0.1,
    score_threshold: float = 0.20,
    peakiness_threshold: float = 1.22,
    min_unmarked_m2: float = 120.0,
) -> np.ndarray:
    """Return a coarse-grid mask of extra vine pixels found at fine_gsd."""
    factor = mosaic.gsd / fine_gsd
    if abs(factor - round(factor)) > 1e-6:
        raise ValueError(f"fine gsd {fine_gsd} does not divide coarse gsd {mosaic.gsd}")
    factor = int(round(factor))
    cells = mosaic.cells
    pixel_area = mosaic.gsd * mosaic.gsd

    by_index = {parse_tile_indices(tile.name): tile for tile in tiles}
    candidates = []
    for name, (row0, col0) in mosaic.placements.items():
        valid = mosaic.valid[row0 : row0 + cells, col0 : col0 + cells]
        marked = vine[row0 : row0 + cells, col0 : col0 + cells]
        unmarked_m2 = float((valid & ~marked).sum()) * pixel_area
        if unmarked_m2 >= min_unmarked_m2:
            candidates.append(parse_tile_indices(name))

    extra = np.zeros_like(vine)
    scanned: set[tuple[int, int]] = set()
    print(f"  fine pass: {len(candidates)} tiles with unmarked ground, {fine_gsd} m/px")
    done_windows = 0
    for r, c in candidates:
        if (r, c) in scanned:
            continue
        group = []
        covered = []
        for rr in range(r - 1, r + 2):
            for cc in range(c - 1, c + 2):
                tile = by_index.get((rr, cc))
                if tile is None:
                    continue
                group.append(tile)
                covered.append((rr, cc))
        local = build_mosaic(group, gsd=fine_gsd, verbose=False)
        score, peakiness = row_score(local.rgb, local.valid, fine_gsd)
        # 8 m² of row pixels. A short remnant stays; a roof speck does not.
        min_pixels = max(40, int(8.0 / (fine_gsd * fine_gsd)))
        mask = vine_mask(
            score,
            peakiness,
            local.valid,
            score_threshold=score_threshold,
            peakiness_threshold=peakiness_threshold,
            min_pixels=min_pixels,
        )
        for name, (local_row, local_col) in local.placements.items():
            tile_mask = mask[local_row : local_row + local.cells, local_col : local_col + local.cells]
            coarse_hit = _downsample_hit(tile_mask, factor)
            row0, col0 = mosaic.placements[name]
            valid = mosaic.valid[row0 : row0 + cells, col0 : col0 + cells]
            marked = vine[row0 : row0 + cells, col0 : col0 + cells]
            extra[row0 : row0 + cells, col0 : col0 + cells] |= coarse_hit & valid & ~marked
        scanned.update(covered)
        done_windows += 1
        if done_windows % 10 == 0:
            print(f"  fine windows {done_windows}, tiles scanned {len(scanned)}/{len(candidates)}")

    added = float(extra.sum()) * pixel_area
    print(f"  fine pass added {added / 10000:.2f} ha of row pixels")
    return extra


def _downsample_hit(mask: np.ndarray, factor: int) -> np.ndarray:
    """A coarse cell counts if a thin row crosses it."""
    height, width = mask.shape
    height = height - height % factor
    width = width - width % factor
    cropped = mask[:height, :width]
    pooled = cropped.reshape(height // factor, factor, width // factor, factor).mean(axis=(1, 3))
    return pooled >= 0.10
