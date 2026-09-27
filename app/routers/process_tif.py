import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.cvat_annotations import annotations_for_filename
from app.services.tif import CHUNK_SIZE, TIFF_MAGIC_SIZE, RasterError, StoredRaster, is_tiff, store_raster

router = APIRouter()

BOUNDARY = "tiff-annotations-boundary"


class ProcessTifResponse(BaseModel):
    id: str
    boundsEpsg32635: tuple[float, float, float, float]
    tileUrl: str
    minzoom: int
    maxzoom: int


# Bumped when served tile pixels change. Browsers cache tiles as immutable.
TILE_VERSION = "2"


def tile_url(request: Request, raster_id: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/tiles/{raster_id}/{{z}}/{{x}}/{{y}}.png?v={TILE_VERSION}"


async def store_uploaded_tiff(file: UploadFile | None) -> StoredRaster:
    if file is None:
        raise HTTPException(status_code=400, detail="No file uploaded. Send a TIFF in the 'file' form field.")

    header = await file.read(TIFF_MAGIC_SIZE)
    if not header:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if not is_tiff(header):
        raise HTTPException(status_code=400, detail="Uploaded file is not a TIFF.")
    await file.seek(0)

    try:
        return await store_raster(file)
    except RasterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _tiff_media_type(content_type: str | None) -> str:
    media = (content_type or "").split(";", 1)[0].strip().lower()
    if media == "image/x-tiff":
        return "image/x-tiff"
    return "image/tiff"


def _content_disposition(filename: str) -> str:
    cleaned = filename.replace("\r", "").replace("\n", "").replace("\\", "\\\\").replace('"', '\\"')
    return f'attachment; filename="{cleaned}"'


async def _tiff_chunks(file: UploadFile) -> AsyncIterator[bytes]:
    await file.seek(0)
    while chunk := await file.read(CHUNK_SIZE):
        yield chunk


async def _multipart(file: UploadFile, filename: str, annotations: dict) -> AsyncIterator[bytes]:
    payload = json.dumps(annotations, ensure_ascii=False).encode("utf-8")
    yield (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="annotations"\r\n'
        "Content-Type: application/json; charset=utf-8\r\n"
        "\r\n"
    ).encode("ascii")
    yield payload
    yield (
        f"\r\n--{BOUNDARY}\r\n"
        f"Content-Disposition: {_content_disposition(filename)}\r\n"
        "Content-Type: image/tiff\r\n"
        "\r\n"
    ).encode("latin-1")
    async for chunk in _tiff_chunks(file):
        yield chunk
    yield f"\r\n--{BOUNDARY}--\r\n".encode("ascii")


@router.post("/process-tif", response_model=None)
async def process_tif_route(file: UploadFile | None = File(None)) -> StreamingResponse:
    if file is None:
        raise HTTPException(status_code=400, detail="No file uploaded. Send a TIFF in the 'file' form field.")

    header = await file.read(TIFF_MAGIC_SIZE)
    if not header:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if not is_tiff(header):
        raise HTTPException(status_code=400, detail="Uploaded file is not a TIFF.")

    filename = file.filename or "upload.tif"
    annotations = annotations_for_filename(file.filename)
    if annotations is None:
        return StreamingResponse(
            _tiff_chunks(file),
            media_type=_tiff_media_type(file.content_type),
            headers={"Content-Disposition": _content_disposition(filename)},
        )
    return StreamingResponse(
        _multipart(file, filename, annotations),
        media_type=f"multipart/mixed; boundary={BOUNDARY}",
    )
