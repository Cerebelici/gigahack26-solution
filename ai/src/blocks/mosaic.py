"""Build a north-up coarse mosaic from the 51.2 m tiles.

Detection runs on this mosaic. The full 2.5 cm tiles are only read again
when a block folder is written.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import rasterio
from rasterio.enums import Resampling

from src.blocks.catalog import TileSource
from src.spatial.grid import TILE_SIZE_M, parse_tile_indices, tile_upper_left


@dataclass
class CoarseMosaic:
    rgb: np.ndarray  # uint8 H,W,3 color-corrected
    valid: np.ndarray  # bool H,W
    origin_x: float  # west edge, EPSG:32635
    origin_y: float  # north edge, EPSG:32635
    gsd: float
    cells: int
    r_min: int
    c_min: int
    placements: dict[str, tuple[int, int]] = field(default_factory=dict)


def cells_per_tile(gsd: float) -> int:
    cells = TILE_SIZE_M / gsd
    if abs(cells - round(cells)) > 1e-6:
        raise ValueError(f"gsd {gsd} does not divide the 51.2 m tile")
    return int(round(cells))


def gray_world(rgb: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Scale channels so valid pixels share one mean. Black nodata stays black."""
    image = rgb.astype(np.float32)
    if int(valid.sum()) < 16:
        return rgb
    means = np.maximum(image[valid].mean(axis=0), 1.0)
    scale = float(means.mean()) / means
    balanced = np.clip(image * scale.reshape(1, 1, 3), 0, 255).astype(np.uint8)
    balanced[~valid] = 0
    return balanced


def build_mosaic(tiles: list[TileSource], gsd: float = 0.4, verbose: bool = True) -> CoarseMosaic:
    if not tiles:
        raise ValueError("no tiles to mosaic")
    cells = cells_per_tile(gsd)
    indexes = {tile.name: parse_tile_indices(tile.name) for tile in tiles}
    r_min = min(r for r, _ in indexes.values())
    r_max = max(r for r, _ in indexes.values())
    c_min = min(c for _, c in indexes.values())
    c_max = max(c for _, c in indexes.values())
    height = (r_max - r_min + 1) * cells
    width = (c_max - c_min + 1) * cells
    origin_x, origin_y = tile_upper_left(r_min, c_min)

    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    valid = np.zeros((height, width), dtype=bool)
    placements: dict[str, tuple[int, int]] = {}

    for index, tile in enumerate(tiles, start=1):
        r, c = indexes[tile.name]
        row0 = (r - r_min) * cells
        col0 = (c - c_min) * cells
        chip, chip_valid = _read_coarse(tile, cells)
        chip = gray_world(chip, chip_valid)
        rgb[row0 : row0 + cells, col0 : col0 + cells] = chip
        valid[row0 : row0 + cells, col0 : col0 + cells] = chip_valid
        placements[tile.name] = (row0, col0)
        if verbose and (index % 25 == 0 or index == len(tiles)):
            print(f"  mosaic {index}/{len(tiles)}")

    return CoarseMosaic(
        rgb=rgb,
        valid=valid,
        origin_x=origin_x,
        origin_y=origin_y,
        gsd=gsd,
        cells=cells,
        r_min=r_min,
        c_min=c_min,
        placements=placements,
    )


def _read_coarse(tile: TileSource, cells: int) -> tuple[np.ndarray, np.ndarray]:
    with rasterio.open(tile.rasterio_path()) as src:
        if src.count < 3:
            raise ValueError(f"{tile.name} has {src.count} bands, expected RGB")
        sampled = src.read(
            indexes=(1, 2, 3),
            out_shape=(3, cells, cells),
            resampling=Resampling.bilinear,
        )
    chip = np.moveaxis(sampled, 0, -1)
    if chip.dtype != np.uint8:
        chip = np.clip(chip, 0, 255).astype(np.uint8)
    # Flight nodata is black. A dim roof is still well above this.
    valid = chip.sum(axis=2) > 18
    return chip, valid
