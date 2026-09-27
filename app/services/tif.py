import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import rasterio
from rasterio.enums import ColorInterp
from rasterio.errors import RasterioError
from rasterio.io import DatasetReader
from rasterio.shutil import copy as rio_copy
from rasterio.warp import transform_bounds
from starlette.concurrency import run_in_threadpool

from app import config
from app.services.tiles import DENSIFY_POINTS, WEB_MERCATOR, Bounds, zoom_range

TIFF_MAGICS = (
    b"II*\x00",  # classic TIFF, little-endian
    b"MM\x00*",  # classic TIFF, big-endian
    b"II+\x00",  # BigTIFF, little-endian
    b"MM\x00+",  # BigTIFF, big-endian
)
TIFF_MAGIC_SIZE = 4
CHUNK_SIZE = 1024 * 1024  # 1 MiB

UPLOAD_DIR = config.UPLOAD_DIR
UPLOAD_FILENAME = "upload.tif"
RASTER_FILENAME = "raster.tif"
RASTER_ID = re.compile(r"[0-9a-f]{32}")
TARGET_CRS = "EPSG:32635"
# Low-zoom tiles read the coarsest level, so it must stay small for any raster size.
MAX_COARSEST_LEVEL_PX = 1024


class AsyncReader(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


class RasterError(Exception):
    """The upload is a TIFF but cannot be served as georeferenced tiles."""


@dataclass(frozen=True)
class StoredRaster:
    id: str
    bounds_epsg32635: Bounds
    minzoom: int
    maxzoom: int
    width: int
    height: int
    transform: tuple[float, float, float, float, float, float]  # affine a, b, c, d, e, f in the file's CRS
    crs_wkt: str
    epsg: int | None


def is_tiff(header: bytes) -> bool:
    return header[:TIFF_MAGIC_SIZE] in TIFF_MAGICS


def find_raster(raster_id: str) -> Path | None:
    if not RASTER_ID.fullmatch(raster_id):
        return None
    path = UPLOAD_DIR / raster_id / RASTER_FILENAME
    return path if path.is_file() else None


async def save_upload(src: AsyncReader, dest: Path, chunk_size: int = CHUNK_SIZE) -> None:
    # Inputs can be hundreds of MB, so never read `src` in one call.
    with dest.open("wb") as out:
        while chunk := await src.read(chunk_size):
            await run_in_threadpool(out.write, chunk)


def _needs_cog(src: DatasetReader) -> bool:
    is_cog = src.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") == "COG"
    factors = src.overviews(1)
    coarsest = max(src.width, src.height) // (factors[-1] if factors else 1)
    return not is_cog or coarsest > MAX_COARSEST_LEVEL_PX


def _jpeg_compatible(src: DatasetReader) -> bool:
    if src.nodata is not None or set(src.dtypes) != {"uint8"}:
        return False
    # Alpha marks the empty space between mosaicked tiles. JPEG would drop it and paint those gaps black.
    if any(band == ColorInterp.alpha for band in src.colorinterp):
        return False
    return src.count == 3


def _bounds(src: DatasetReader, crs: str) -> Bounds:
    try:
        bounds = transform_bounds(src.crs, crs, *src.bounds, densify_pts=DENSIFY_POINTS)
    except Exception as exc:
        raise RasterError(f"Could not reproject the TIFF from {src.crs} to {crs}.") from exc
    if not all(math.isfinite(v) for v in bounds):
        raise RasterError(f"Could not reproject the TIFF from {src.crs} to {crs}.")
    return bounds


def _prepare(raster_id: str, upload: Path, dest: Path) -> StoredRaster:
    """Validate georeferencing and leave a tiled COG with overviews at `dest`."""
    try:
        with rasterio.open(upload) as src:
            if src.crs is None or src.transform.is_identity:
                raise RasterError("Uploaded TIFF has no georeferencing (CRS and geotransform).")
            bounds = _bounds(src, TARGET_CRS)
            minzoom, maxzoom = zoom_range(_bounds(src, WEB_MERCATOR), src.width, src.height)
            needs_cog = _needs_cog(src)
            compress = "JPEG" if _jpeg_compatible(src) else "DEFLATE"
            stored = StoredRaster(
                id=raster_id,
                bounds_epsg32635=bounds,
                minzoom=minzoom,
                maxzoom=maxzoom,
                width=src.width,
                height=src.height,
                transform=tuple(src.transform)[:6],
                crs_wkt=src.crs.to_wkt(),
                epsg=src.crs.to_epsg(),
            )
        if needs_cog:
            rio_copy(upload, dest, driver="COG", compress=compress, bigtiff="IF_SAFER", num_threads="ALL_CPUS")
            upload.unlink()
        else:
            upload.replace(dest)
    except RasterioError as exc:
        raise RasterError("Uploaded TIFF could not be read as a raster.") from exc
    return stored


async def store_raster(src: AsyncReader) -> StoredRaster:
    raster_id = uuid4().hex
    folder = UPLOAD_DIR / raster_id
    folder.mkdir(parents=True)
    upload = folder / UPLOAD_FILENAME
    try:
        await save_upload(src, upload)
        return await run_in_threadpool(_prepare, raster_id, upload, folder / RASTER_FILENAME)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def remove_raster(raster_id: str) -> None:
    if RASTER_ID.fullmatch(raster_id):
        shutil.rmtree(UPLOAD_DIR / raster_id, ignore_errors=True)
