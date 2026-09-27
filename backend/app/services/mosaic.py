"""Combine georeferenced tiles from one or more zips into one orthophoto.

Each TIFF is pasted by its CRS and geotransform, so neighbouring tiles meet on the ground
whether they arrived in the same zip or in separate ones. A tile that carries no georeferencing,
as in a CVAT export, is placed by its challenge-grid name. CVAT shapes from XML files in a
zip are moved into that mosaic's pixel grid, and they match the tiles from that same zip.
Empty space between tiles is transparent.
"""

import logging
import math
import shutil
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4
from xml.etree.ElementTree import ParseError

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import ColorInterp, Resampling
from rasterio.io import DatasetReader, DatasetWriter
from rasterio.transform import Affine
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window
from starlette.concurrency import run_in_threadpool

from app.services import tif
from app.services.cvat_annotations import TILE_SIZE_M, UTM, file_basename, parse_annotations, tile_origin
from app.services.tif import TIFF_MAGIC_SIZE, RasterError, StoredRaster, is_tiff


class _Upload(Protocol):
    filename: str | None

    async def read(self, size: int = -1) -> bytes: ...

    async def seek(self, offset: int) -> Any: ...

logger = logging.getLogger(__name__)

TIFF_SUFFIXES = {".tif", ".tiff"}
MAX_SIDE = 120_000
MAX_ZIP_BYTES = 8 * 1024**3


@dataclass(frozen=True)
class _Tile:
    name: str
    dataset: DatasetReader


def is_zip(header: bytes) -> bool:
    return header.startswith(b"PK")


async def store_project_imagery(
    files: Sequence[_Upload] | None,
) -> tuple[StoredRaster, list[dict[str, Any]] | None]:
    """Store one GeoTIFF, or mosaic every tile from one or more zips into one map.

    The annotation list is None for GeoTIFFs with no zip, which still take shapes from the
    repository catalog. Zips return the shapes from their own XML files, in mosaic pixels.
    A shape matches a tile from the same zip.
    """
    uploads = [file for file in files or [] if file is not None]
    if not uploads:
        raise RasterError("No file uploaded. Send a GeoTIFF or a zip of GeoTIFFs in the 'file' form field.")
    kinds: list[str] = []
    for upload in uploads:
        header = await upload.read(TIFF_MAGIC_SIZE)
        if not header:
            raise RasterError("Uploaded file is empty.")
        await upload.seek(0)
        if is_tiff(header):
            kinds.append("tiff")
        elif is_zip(header):
            kinds.append("zip")
        else:
            raise RasterError("Send a GeoTIFF (.tif, .tiff) or a zip of GeoTIFFs and their CVAT XML files.")
    if len(uploads) == 1 and kinds[0] == "tiff":
        return await tif.store_raster(uploads[0]), None
    return await _store_mosaic(list(zip(uploads, kinds, strict=True)))


async def _store_mosaic(parts: list[tuple[_Upload, str]]) -> tuple[StoredRaster, list[dict[str, Any]] | None]:
    raster_id = uuid4().hex
    folder = tif.UPLOAD_DIR / raster_id
    folder.mkdir(parents=True)
    saved: list[tuple[Path, str]] = []
    try:
        for index, (upload, kind) in enumerate(parts):
            path = folder / _saved_name(upload.filename, index, kind)
            await tif.save_upload(upload, path)
            saved.append((path, kind))
        has_zip = any(kind == "zip" for _, kind in saved)
        stored, items = await run_in_threadpool(_mosaic_saved, raster_id, saved, folder)
        # Bare GeoTIFFs still take shapes from the catalog. A zip brings its own.
        return stored, items if has_zip else None
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def _saved_name(filename: str | None, index: int, kind: str) -> str:
    if kind == "zip":
        return f"upload-{index}.zip"
    candidate = Path(filename or "").name
    if candidate.lower().endswith((".tif", ".tiff")) and _safe_member(candidate) is not None:
        return f"{index}-{candidate}"
    return f"{index}-tile.tif"


def _mosaic_saved(
    raster_id: str, saved: list[tuple[Path, str]], folder: Path
) -> tuple[StoredRaster, list[dict[str, Any]]]:
    extract = folder / "parts"
    extract.mkdir()
    budget = _ByteBudget(MAX_ZIP_BYTES)
    bundles: list[tuple[list[_Tile], list[Path]]] = []
    try:
        for index, (path, kind) in enumerate(saved):
            dest = extract / str(index)
            dest.mkdir()
            if kind == "zip":
                tiff_paths, xml_paths = _extract(path, dest, budget)
                path.unlink(missing_ok=True)
            else:
                target = dest / path.name.split("-", 1)[-1]
                path.replace(target)
                tiff_paths, xml_paths = [target], []
            if tiff_paths:
                bundles.append((_open_tiles(tiff_paths), xml_paths))
        tiles = [tile for bundle_tiles, _ in bundles for tile in bundle_tiles]
        if not tiles:
            raise RasterError("Zip does not contain a GeoTIFF.")
        mosaic_path = folder / "mosaic.tif"
        _write_mosaic(tiles, mosaic_path)
        stored = tif._prepare(raster_id, mosaic_path, folder / tif.RASTER_FILENAME)
        items = [item for bundle_tiles, xml_paths in bundles for item in _placed_items(bundle_tiles, xml_paths, stored)]
    finally:
        for bundle_tiles, _ in bundles:
            for tile in bundle_tiles:
                tile.dataset.close()
    shutil.rmtree(extract, ignore_errors=True)
    return stored, items


class _ByteBudget:
    """Shared cap on the bytes read out of every zip in one upload."""

    def __init__(self, limit: int) -> None:
        self.left = limit

    def take(self, amount: int) -> None:
        if amount > self.left:
            raise RasterError("Zip is too large to mosaic.")
        self.left -= amount


def _extract(zip_path: Path, dest: Path, budget: _ByteBudget) -> tuple[list[Path], list[Path]]:
    tiffs: list[Path] = []
    xmls: list[Path] = []
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise RasterError("Uploaded file is not a valid zip.") from exc
    with archive:
        root = dest.resolve()
        for info in archive.infolist():
            if info.is_dir():
                continue
            relative = _safe_member(info.filename)
            if relative is None:
                continue
            suffix = relative.suffix.lower()
            if suffix not in TIFF_SUFFIXES and suffix != ".xml":
                continue
            if info.file_size > budget.left:
                raise RasterError("Zip is too large to mosaic.")
            target = (dest / relative).resolve()
            if not target.is_relative_to(root):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with archive.open(info) as src, target.open("wb") as out:
                while chunk := src.read(1024 * 1024):
                    written += len(chunk)
                    if written > budget.left:
                        raise RasterError("Zip is too large to mosaic.")
                    out.write(chunk)
            budget.take(written)
            if suffix in TIFF_SUFFIXES:
                tiffs.append(target)
            else:
                xmls.append(target)
    tiffs.sort(key=lambda path: path.name.lower())
    return tiffs, xmls


def _safe_member(name: str) -> Path | None:
    parts = [part for part in name.replace("\\", "/").split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    if parts[0] == "__MACOSX" or parts[-1].startswith("."):
        return None
    return Path(*parts)


def _open_tiles(paths: list[Path]) -> list[_Tile]:
    tiles: list[_Tile] = []
    try:
        for path in paths:
            try:
                dataset = rasterio.open(path)
            except rasterio.RasterioError as exc:
                raise RasterError(f"Could not read {path.name} as a GeoTIFF.") from exc
            if dataset.crs is None or dataset.transform.is_identity:
                dataset = _place_by_name(path, dataset)
            tiles.append(_Tile(name=path.name, dataset=dataset))
    except Exception:
        for tile in tiles:
            tile.dataset.close()
        raise
    return tiles


def _place_by_name(path: Path, dataset: DatasetReader) -> DatasetReader:
    """Rewrite a tile that lost its georeferencing onto the challenge cell its file name gives.

    A CVAT export re-encodes every tile as a PNG and keeps only the original ".tif" name, so
    the pixels survive but the CRS and geotransform do not. The name still says which 51.2 m
    cell the tile covers, which is enough to put it back on the grid.
    """
    origin = tile_origin(path.name)
    if origin is None:
        dataset.close()
        raise RasterError(f"{path.name} has no georeferencing (CRS and geotransform).")
    west, north = origin
    profile: dict[str, Any] = {
        "driver": "GTiff",
        "width": dataset.width,
        "height": dataset.height,
        "count": dataset.count,
        "dtype": dataset.dtypes[0],
        "crs": UTM,
        "transform": Affine(TILE_SIZE_M / dataset.width, 0, west, 0, -TILE_SIZE_M / dataset.height, north),
        "compress": "deflate",
    }
    data = dataset.read()
    dataset.close()
    placed = path.with_name(f"{path.stem}-grid.tif")
    with rasterio.open(placed, "w", **profile) as out:
        out.write(data)
    placed.replace(path)
    return rasterio.open(path)


def _write_mosaic(tiles: list[_Tile], dest: Path) -> None:
    dst_crs = _destination_crs(tiles)
    res_x, res_y = _resolution(tiles, dst_crs)
    min_x, min_y, max_x, max_y = _union_bounds(tiles, dst_crs, res_x, res_y)
    width = int(round((max_x - min_x) / res_x))
    height = int(round((max_y - min_y) / res_y))
    if width < 1 or height < 1 or width > MAX_SIDE or height > MAX_SIDE:
        raise RasterError("These GeoTIFFs cover too large an area to combine.")
    logger.info("Mosaicking %d GeoTIFFs into a %dx%d raster.", len(tiles), width, height)
    transform = Affine(res_x, 0, min_x, 0, -res_y, max_y)
    profile: dict[str, Any] = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": 4,
        "dtype": "uint8",
        "crs": dst_crs,
        "transform": transform,
        "compress": "deflate",
        "BIGTIFF": "IF_SAFER",
    }
    if width >= 512 and height >= 512:
        profile.update(tiled=True, blockxsize=512, blockysize=512)
    with rasterio.open(dest, "w", **profile) as dst:
        dst.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha)
        for tile in tiles:
            _paste(tile.dataset, dst, dst_crs)


def _destination_crs(tiles: list[_Tile]) -> CRS:
    codes = [tile.dataset.crs.to_epsg() for tile in tiles]
    if codes[0] is not None and all(code == codes[0] for code in codes):
        return CRS.from_epsg(codes[0])
    return CRS.from_epsg(32635)


def _resolution(tiles: list[_Tile], dst_crs: CRS) -> tuple[float, float]:
    sizes = [_pixel_size(tile.dataset, dst_crs) for tile in tiles]
    res_x = min(size[0] for size in sizes)
    res_y = min(size[1] for size in sizes)
    if res_x <= 0 or res_y <= 0 or not math.isfinite(res_x) or not math.isfinite(res_y):
        raise RasterError("Could not determine a pixel size for the mosaic.")
    return res_x, res_y


def _same_epsg(dataset: DatasetReader, dst_crs: CRS) -> bool:
    code = dataset.crs.to_epsg()
    return code is not None and code == dst_crs.to_epsg()


def _north_up(dataset: DatasetReader) -> bool:
    transform = dataset.transform
    return transform.b == 0 and transform.d == 0 and transform.a > 0 and transform.e < 0


def _pixel_size(dataset: DatasetReader, dst_crs: CRS) -> tuple[float, float]:
    transform = dataset.transform
    # Same grid as the file. Reprojecting a 2.5 cm step nudges it off the tile edges and opens a seam.
    if _same_epsg(dataset, dst_crs) and _north_up(dataset):
        return transform.a, -transform.e
    corners = [transform @ (0, 0), transform @ (1, 0), transform @ (0, 1)]
    xs, ys = zip(*corners)
    if not _same_epsg(dataset, dst_crs):
        from rasterio.warp import transform as reproject_points

        xs, ys = reproject_points(dataset.crs, dst_crs, list(xs), list(ys))
    return math.hypot(xs[1] - xs[0], ys[1] - ys[0]), math.hypot(xs[2] - xs[0], ys[2] - ys[0])


def _union_bounds(tiles: list[_Tile], dst_crs: CRS, res_x: float, res_y: float) -> tuple[float, float, float, float]:
    boxes = [_bounds_in(tile.dataset, dst_crs) for tile in tiles]
    min_x = min(box[0] for box in boxes)
    min_y = min(box[1] for box in boxes)
    max_x = max(box[2] for box in boxes)
    max_y = max(box[3] for box in boxes)
    anchor = tiles[0].dataset
    if _same_epsg(anchor, dst_crs) and _north_up(anchor):
        anchor_x, anchor_y = anchor.transform.c, anchor.transform.f
    else:
        anchor_x, anchor_y = min_x, max_y
    return (
        _snap(min_x, anchor_x, res_x, down=True),
        _snap(min_y, anchor_y, res_y, down=True),
        _snap(max_x, anchor_x, res_x, down=False),
        _snap(max_y, anchor_y, res_y, down=False),
    )


def _snap(value: float, anchor: float, step: float, *, down: bool) -> float:
    cells = (value - anchor) / step
    # A fraction of a pixel is float noise when the tiles already share a grid.
    snapped = math.floor(cells + 1e-4) if down else math.ceil(cells - 1e-4)
    return anchor + snapped * step


def _bounds_in(dataset: DatasetReader, dst_crs: CRS) -> tuple[float, float, float, float]:
    if _same_epsg(dataset, dst_crs):
        left, bottom, right, top = dataset.bounds
        return left, bottom, right, top
    try:
        bounds = transform_bounds(dataset.crs, dst_crs, *dataset.bounds, densify_pts=21)
    except Exception as exc:
        raise RasterError(f"Could not place {Path(dataset.name).name} on the map.") from exc
    if not all(math.isfinite(value) for value in bounds):
        raise RasterError("Could not place a GeoTIFF on the map.")
    return bounds


def _paste(src: DatasetReader, dst: DatasetWriter, dst_crs: CRS) -> None:
    """Copy one tile into the mosaic. Unwritten pixels stay transparent, so gaps stay empty."""
    aligned = _aligned_origin(src, dst)
    if aligned is not None:
        _paste_aligned(src, dst, *aligned)
        return
    _paste_reprojected(src, dst, dst_crs)


def _aligned_origin(src: DatasetReader, dst: DatasetWriter) -> tuple[int, int] | None:
    """Pixel column and row of this tile's top-left when it sits on the mosaic grid."""
    if not _same_epsg(src, dst.crs) or not _north_up(src):
        return None
    res_x, res_y = dst.res
    if abs(src.transform.a - res_x) > res_x * 1e-6 or abs(-src.transform.e - res_y) > res_y * 1e-6:
        return None
    col = (src.transform.c - dst.transform.c) / dst.transform.a
    row = (dst.transform.f - src.transform.f) / -dst.transform.e
    if abs(col - round(col)) > 1e-3 or abs(row - round(row)) > 1e-3:
        return None
    col_i, row_i = int(round(col)), int(round(row))
    if col_i < 0 or row_i < 0 or col_i + src.width > dst.width or row_i + src.height > dst.height:
        return None
    return col_i, row_i


def _paste_aligned(src: DatasetReader, dst: DatasetWriter, col: int, row: int) -> None:
    window = Window(col, row, src.width, src.height)
    dst.write(_read_rgb(src), indexes=(1, 2, 3), window=window)
    dst.write(np.full((src.height, src.width), 255, dtype=np.uint8), indexes=4, window=window)


def _paste_reprojected(src: DatasetReader, dst: DatasetWriter, dst_crs: CRS) -> None:
    width, height = src.width, src.height
    ground = [src.transform @ (x, y) for x, y in ((0, 0), (width, 0), (0, height), (width, height))]
    if not _same_epsg(src, dst_crs):
        from rasterio.warp import transform as reproject_points

        xs, ys = zip(*ground)
        xs, ys = reproject_points(src.crs, dst_crs, list(xs), list(ys))
        ground = list(zip(xs, ys))
    inverse = ~dst.transform
    cols, rows = zip(*(inverse @ (x, y) for x, y in ground))
    col0 = max(int(math.floor(min(cols) + 1e-4)), 0)
    row0 = max(int(math.floor(min(rows) + 1e-4)), 0)
    col1 = min(int(math.ceil(max(cols) - 1e-4)), dst.width)
    row1 = min(int(math.ceil(max(rows) - 1e-4)), dst.height)
    if col0 >= col1 or row0 >= row1:
        return
    window = Window(col0, row0, col1 - col0, row1 - row0)
    window_transform = dst.window_transform(window)
    for index, source in enumerate(_rgb_sources(src), start=1):
        array = np.zeros((int(window.height), int(window.width)), dtype=np.uint8)
        reproject(
            source=source,
            destination=array,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=window_transform,
            dst_crs=dst_crs,
            resampling=Resampling.nearest,
        )
        dst.write(array, index, window=window)
    dst.write(np.full((int(window.height), int(window.width)), 255, dtype=np.uint8), 4, window=window)


def _read_rgb(src: DatasetReader) -> np.ndarray:
    if src.count == 1:
        band = _as_uint8(src.read(1))
        return np.stack([band, band, band])
    return _as_uint8(src.read([1, 2, 3]))


def _rgb_sources(src: DatasetReader) -> list[Any]:
    if set(src.dtypes) == {"uint8"} and src.count >= 3:
        return [rasterio.band(src, band) for band in (1, 2, 3)]
    if set(src.dtypes) == {"uint8"} and src.count == 1:
        band = rasterio.band(src, 1)
        return [band, band, band]
    indexes = 1 if src.count == 1 else [1, 2, 3]
    data = _as_uint8(src.read(indexes))
    if data.ndim == 2:
        data = np.stack([data, data, data])
    return [data[band] for band in range(3)]


def _as_uint8(data: np.ndarray) -> np.ndarray:
    if data.dtype == np.uint8:
        return data
    if np.issubdtype(data.dtype, np.integer):
        data = data.astype(np.float32) * (255 / np.iinfo(data.dtype).max)
    return np.clip(data, 0, 255).astype(np.uint8)


def _placed_items(tiles: list[_Tile], xml_paths: list[Path], stored: StoredRaster) -> list[dict[str, Any]]:
    """CVAT shapes moved from each tile's pixels into the mosaic's pixels."""
    by_name: dict[str, list[dict[str, Any]]] = {}
    for path in xml_paths:
        try:
            images = parse_annotations(path.read_bytes())
        except (ParseError, KeyError, ValueError, TypeError):
            logger.warning("Skipped annotation file %s: it is not usable CVAT XML.", path.name)
            continue
        for image_name, image in images.items():
            by_name.setdefault(file_basename(image_name).lower(), []).extend(image["items"])
    mosaic = Affine(*stored.transform)
    mosaic_crs = CRS.from_wkt(stored.crs_wkt)
    inverse = ~mosaic
    placed: list[dict[str, Any]] = []
    for tile in tiles:
        for item in by_name.get(tile.name.lower(), []):
            points = _to_mosaic_pixels(item["points"], tile, inverse, mosaic_crs)
            if points is None:
                continue
            placed.append({**item, "points": points})
    return placed


def _to_mosaic_pixels(
    points: list[list[float]], tile: _Tile, inverse: Affine, mosaic_crs: CRS
) -> list[list[float]] | None:
    if len(points) < 2:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for point in points:
        if len(point) < 2:
            return None
        ground_x, ground_y = tile.dataset.transform @ (point[0], point[1])
        xs.append(ground_x)
        ys.append(ground_y)
    if tile.dataset.crs != mosaic_crs:
        from rasterio.warp import transform as reproject_points

        try:
            xs, ys = reproject_points(tile.dataset.crs, mosaic_crs, xs, ys)
        except Exception:
            logger.warning("Skipped a shape on %s: it could not be placed on the mosaic.", tile.name)
            return None
    placed: list[list[float]] = []
    for ground_x, ground_y in zip(xs, ys):
        col, row = inverse @ (ground_x, ground_y)
        if not math.isfinite(col) or not math.isfinite(row):
            return None
        placed.append([float(col), float(row)])
    return placed
