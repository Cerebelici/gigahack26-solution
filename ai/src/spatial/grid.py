"""
Georeferencing and Grid transformation module for Sireț3 tiles (EPSG:32635).
Strictly follows the empirical spatial reference defined in knowledge/spatial.md.
"""

import re
from typing import Tuple, Optional

# Constants
CRS = "EPSG:32635"
TILE_PIXELS = 2048
GSD = 0.025  # metres per pixel
TILE_SIZE_M = 51.2  # metres on ground (2048 * 0.025)

# Grid origin reference
GRID_ORIGIN_X = 628992.0
GRID_ORIGIN_Y = 5221222.4

# Start/Finish point (EPSG:32635)
START_POINT = (629504.70, 5220250.75)
START_TILE = "siret3_r018_c010.tif"


def parse_tile_indices(tile_name: str) -> Tuple[int, int]:
    """Extract row (r) and column (c) indices from tile filename like 'siret3_r021_c012.tif'."""
    m = re.search(r"r(\d+)_c(\d+)", tile_name)
    if not m:
        raise ValueError(f"Could not parse row and column indices from '{tile_name}'")
    return int(m.group(1)), int(m.group(2))


def tile_upper_left(r: int, c: int) -> Tuple[float, float]:
    """Compute the Upper-Left corner (X_ul, Y_ul) of tile (r, c) in EPSG:32635 metres."""
    x_ul = GRID_ORIGIN_X + c * TILE_SIZE_M
    y_ul = GRID_ORIGIN_Y - r * TILE_SIZE_M
    return round(x_ul, 4), round(y_ul, 4)


def tile_bounds(r: int, c: int) -> Tuple[float, float, float, float]:
    """Compute the bounding box (X_min, Y_min, X_max, Y_max) of tile (r, c) in EPSG:32635 metres."""
    x_ul, y_ul = tile_upper_left(r, c)
    x_lr = x_ul + TILE_SIZE_M
    y_lr = y_ul - TILE_SIZE_M
    return round(x_ul, 4), round(y_lr, 4), round(x_lr, 4), round(y_ul, 4)


def pixel_to_map(r: int, c: int, px: float, py: float) -> Tuple[float, float]:
    """
    Convert tile pixel coordinates (px, py) to map coordinates (Easting, Northing) in EPSG:32635.
    Pixel origin is top-left, py points downward.
    """
    x_ul, y_ul = tile_upper_left(r, c)
    easting = x_ul + px * GSD
    northing = y_ul - py * GSD
    return round(easting, 4), round(northing, 4)


def map_to_pixel(r: int, c: int, easting: float, northing: float) -> Tuple[float, float]:
    """Convert EPSG:32635 coordinates to tile pixel coordinates (px, py)."""
    x_ul, y_ul = tile_upper_left(r, c)
    px = (easting - x_ul) / GSD
    py = (y_ul - northing) / GSD
    return round(px, 2), round(py, 2)


def map_to_tile_indices(easting: float, northing: float) -> Tuple[int, int]:
    """Find the tile row (r) and column (c) containing the given map coordinate."""
    c = int((easting - GRID_ORIGIN_X) // TILE_SIZE_M)
    r = int((GRID_ORIGIN_Y - northing) // TILE_SIZE_M)
    return r, c
