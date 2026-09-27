import math
import warnings
from functools import cache
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import DatasetReader, MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window
from rasterio.windows import from_bounds as window_from_bounds

TILE_SIZE = 256
WEB_MERCATOR = "EPSG:3857"
WORLD_SIZE_M = 2 * math.pi * 6378137.0
MAX_ZOOM = 24
MINZOOM_MARGIN = 2
DENSIFY_POINTS = 21
WINDOW_PADDING_PX = 2

Bounds = tuple[float, float, float, float]


def tile_resolution(z: int) -> float:
    """Web Mercator metres per tile pixel at zoom `z`."""
    return WORLD_SIZE_M / (TILE_SIZE * 2**z)


def tile_bounds(z: int, x: int, y: int) -> Bounds:
    """XYZ tile extent in EPSG:3857 as (left, bottom, right, top)."""
    size = WORLD_SIZE_M / 2**z
    left = -WORLD_SIZE_M / 2 + x * size
    top = WORLD_SIZE_M / 2 - y * size
    return left, top - size, left + size, top


def is_valid_tile(z: int, x: int, y: int) -> bool:
    return 0 <= z <= MAX_ZOOM and 0 <= x < 2**z and 0 <= y < 2**z


def native_resolution(mercator_bounds: Bounds, width: int, height: int) -> float:
    left, bottom, right, top = mercator_bounds
    return min((right - left) / width, (top - bottom) / height)


def zoom_range(mercator_bounds: Bounds, width: int, height: int) -> tuple[int, int]:
    """maxzoom reaches native resolution; at minzoom the whole raster spans well under one tile."""
    left, bottom, right, top = mercator_bounds
    native_zoom = round(math.log2(tile_resolution(0) / native_resolution(mercator_bounds, width, height)))
    fit_zoom = math.floor(math.log2(WORLD_SIZE_M / max(right - left, top - bottom)))
    maxzoom = min(max(native_zoom, 0), MAX_ZOOM)
    minzoom = min(max(fit_zoom - MINZOOM_MARGIN, 0), maxzoom)
    return minzoom, maxzoom


def encode_png(rgba: np.ndarray) -> bytes:
    _, height, width = rgba.shape
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with MemoryFile() as mem:
            with mem.open(driver="PNG", width=width, height=height, count=4, dtype="uint8") as dst:
                dst.write(rgba)
            return mem.read()


@cache
def empty_tile() -> bytes:
    return encode_png(np.zeros((4, TILE_SIZE, TILE_SIZE), dtype=np.uint8))


def _to_uint8(data: np.ndarray) -> np.ndarray:
    if data.dtype == np.uint8:
        return data
    if np.issubdtype(data.dtype, np.integer):
        data = data.astype(np.float32) * (255 / np.iinfo(data.dtype).max)
    return np.clip(data, 0, 255).astype(np.uint8)


def _overview_level(src: DatasetReader, target_resolution: float) -> int | None:
    """Coarsest overview that is still at least as fine as the tile; None means full resolution."""
    mercator = transform_bounds(src.crs, WEB_MERCATOR, *src.bounds, densify_pts=DENSIFY_POINTS)
    resolution = native_resolution(mercator, src.width, src.height)
    level = None
    for index, factor in enumerate(src.overviews(1)):
        if resolution * factor > target_resolution:
            break
        level = index
    return level


def _source_window(ds: DatasetReader, bounds: Bounds) -> Window | None:
    src_bounds = transform_bounds(WEB_MERCATOR, ds.crs, *bounds, densify_pts=DENSIFY_POINTS)
    window = window_from_bounds(*src_bounds, transform=ds.transform)
    col0 = max(math.floor(window.col_off) - WINDOW_PADDING_PX, 0)
    row0 = max(math.floor(window.row_off) - WINDOW_PADDING_PX, 0)
    col1 = min(math.ceil(window.col_off + window.width) + WINDOW_PADDING_PX, ds.width)
    row1 = min(math.ceil(window.row_off + window.height) + WINDOW_PADDING_PX, ds.height)
    if col0 >= col1 or row0 >= row1:
        return None
    return Window(col0, row0, col1 - col0, row1 - row0)


def _adjacent(hit: np.ndarray) -> np.ndarray:
    near = np.zeros(hit.shape, dtype=bool)
    near[1:] |= hit[:-1]
    near[:-1] |= hit[1:]
    near[:, 1:] |= hit[:, :-1]
    near[:, :-1] |= hit[:, 1:]
    return near


def _source_frame_mask(rgb: np.ndarray) -> np.ndarray:
    """Magenta frames painted on the edge of each source tile, including averaged overviews."""
    r = rgb[0].astype(np.int16)
    g = rgb[1].astype(np.int16)
    b = rgb[2].astype(np.int16)
    line = (r >= 130) & (b >= 120) & ((r - g) >= 60) & ((b - g) >= 50) & (np.abs(r - b) <= 50)
    line = line & _adjacent(line)
    if not line.any():
        return line
    # Overview resampling bleeds the frame into the next pixel. That pixel is still magenta, not imagery.
    bleed = (b > g + 8) & (r > g)
    hole = line
    for _ in range(2):
        hole = hole | (bleed & _adjacent(hole))
    return hole


def _fill_along_width(
    image: np.ndarray, hole: np.ndarray, source: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fill holes from the nearest imagery on the left or right."""
    _, width, _ = image.shape
    if width == 0 or not hole.any():
        return image, hole, source
    columns = np.arange(width, dtype=np.int32)
    left = np.where(source, columns, np.int32(-1))
    np.maximum.accumulate(left, axis=1, out=left)
    right = np.where(source, columns, np.int32(width))
    right = np.minimum.accumulate(right[:, ::-1], axis=1)[:, ::-1]

    fill = hole & ((left >= 0) | (right < width))
    if not fill.any():
        return image, hole, source

    rows, cols = np.nonzero(fill)
    left_at = left[rows, cols]
    right_at = right[rows, cols]
    has_left = left_at >= 0
    has_right = right_at < width
    use_left = has_left & (~has_right | ((cols - left_at) <= (right_at - cols)))
    taken = np.where(use_left, left_at, right_at)
    image[rows, cols] = image[rows, taken]
    hole[rows, cols] = False
    source[rows, cols] = True
    return image, hole, source


def _erase_source_frames(rgb: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Replace baked-in magenta tile frames. Pixels with no imagery beside them become empty."""
    hole = _source_frame_mask(rgb)
    if not hole.any():
        return rgb, mask
    image = np.moveaxis(rgb, 0, -1).copy()
    hole = hole.copy()
    source = (~hole) & (mask > 0)
    image, hole, source = _fill_along_width(image, hole, source)
    swapped = (
        np.swapaxes(image, 0, 1),
        np.swapaxes(hole, 0, 1),
        np.swapaxes(source, 0, 1),
    )
    _fill_along_width(*swapped)
    if hole.any():
        image[hole] = 0
        mask = np.array(mask, copy=True)
        mask[hole] = 0
    return np.moveaxis(image, -1, 0), mask


def _render(ds: DatasetReader, bounds: Bounds) -> bytes:
    window = _source_window(ds, bounds)
    if window is None:
        return empty_tile()
    indexes = [1, 2, 3] if ds.count >= 3 else [1, 1, 1]
    rgb = _to_uint8(ds.read(indexes, window=window))
    rgb, valid = _erase_source_frames(rgb, ds.dataset_mask(window=window))
    source = np.concatenate([rgb, valid[np.newaxis]])
    tile = np.zeros((4, TILE_SIZE, TILE_SIZE), dtype=np.uint8)
    reproject(
        source,
        tile,
        src_transform=ds.window_transform(window),
        src_crs=ds.crs,
        src_alpha=4,
        dst_transform=from_bounds(*bounds, TILE_SIZE, TILE_SIZE),
        dst_crs=WEB_MERCATOR,
        dst_alpha=4,
        resampling=Resampling.bilinear,
    )
    if not tile[3].any():
        return empty_tile()
    return encode_png(tile)


def render_tile(path: Path, z: int, x: int, y: int) -> bytes:
    """Render one 256x256 Web Mercator PNG tile, reading only a window of the matching overview."""
    bounds = tile_bounds(z, x, y)
    with rasterio.open(path) as src:
        level = _overview_level(src, tile_resolution(z))
        if level is None:
            return _render(src, bounds)
    with rasterio.open(path, overview_level=level) as overview:
        return _render(overview, bounds)
