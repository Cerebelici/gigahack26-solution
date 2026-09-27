from fastapi import APIRouter, HTTPException, Response

from app.services.tif import find_raster
from app.services.tiles import is_valid_tile, render_tile

router = APIRouter()

TILE_CACHE_CONTROL = "public, max-age=86400, immutable"


@router.get(
    "/tiles/{raster_id}/{z}/{x}/{y}.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "A 256x256 Web Mercator tile."}},
)
def get_tile(raster_id: str, z: int, x: int, y: int) -> Response:
    path = find_raster(raster_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Unknown raster id.")
    if not is_valid_tile(z, x, y):
        raise HTTPException(status_code=404, detail="Tile coordinates are out of range.")
    return Response(render_tile(path, z, x, y), media_type="image/png", headers={"Cache-Control": TILE_CACHE_CONTROL})
