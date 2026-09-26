import asyncio
import json
import math
from collections import Counter
from io import BytesIO

import numpy as np
import pytest
import rasterio
from fastapi import HTTPException
from fastapi.testclient import TestClient
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.warp import transform
from starlette.datastructures import UploadFile

from app.main import app
from app.routers.process_tif import BOUNDARY, store_uploaded_tiff
from app.services import cvat_annotations, tif
from app.services.tif import CHUNK_SIZE

client = TestClient(app)

UL_X, UL_Y = 629504.7, 5220301.95  # EPSG:32635, near the challenge start point
PIXEL_M = 0.025
COLOR = (200, 40, 90)


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tif, "UPLOAD_DIR", tmp_path)
    return tmp_path


def make_geotiff(size: int = 300, crs: str | None = "EPSG:32635", transform_=None, **profile) -> bytes:
    """Solid-colour 3-band uint8 GeoTIFF, stripped and without overviews."""
    data = np.empty((3, size, size), dtype=np.uint8)
    for band, value in enumerate(COLOR):
        data[band] = value
    with MemoryFile() as mem:
        with mem.open(
            driver="GTiff",
            width=size,
            height=size,
            count=3,
            dtype="uint8",
            crs=crs,
            transform=transform_ or from_origin(UL_X, UL_Y, PIXEL_M, PIXEL_M),
            **profile,
        ) as dst:
            dst.write(data)
        return mem.read()


def upload(data: bytes, name: str = "tile.tif", content_type: str = "image/tiff"):
    return client.post("/process-tif", files={"file": (name, data, content_type)})


def stored_tiles(data: bytes, name: str = "tile.tif") -> dict:
    """Tile metadata from the raster store. `/process-tif` streams the TIFF itself."""
    raster = asyncio.run(store_uploaded_tiff(UploadFile(filename=name, file=BytesIO(data))))
    return {
        "id": raster.id,
        "boundsEpsg32635": list(raster.bounds_epsg32635),
        "tileUrl": f"http://testserver/tiles/{raster.id}/{{z}}/{{x}}/{{y}}.png",
        "minzoom": raster.minzoom,
        "maxzoom": raster.maxzoom,
    }


def store_error(data: bytes, name: str = "tile.tif") -> HTTPException:
    with pytest.raises(HTTPException) as caught:
        asyncio.run(store_uploaded_tiff(UploadFile(filename=name, file=BytesIO(data))))
    return caught.value


def parse_multipart(body: bytes) -> tuple[dict, bytes]:
    closing = f"\r\n--{BOUNDARY}--\r\n".encode()
    head = f"--{BOUNDARY}\r\n".encode()
    marker = f"\r\n--{BOUNDARY}\r\n".encode()
    assert body.startswith(head)
    assert body.endswith(closing)
    first, second = body[len(head) : -len(closing)].split(marker, 1)
    annotations = json.loads(_part_body(first))
    return annotations, _part_body(second)


def _part_body(raw: bytes) -> bytes:
    header_blob, body = raw.split(b"\r\n\r\n", 1)
    headers = {}
    for line in header_blob.decode("ascii").split("\r\n"):
        name, value = line.split(":", 1)
        headers[name] = value[1:] if value.startswith(" ") else value
    if b"image/tiff" in header_blob:
        assert headers["Content-Disposition"].startswith("attachment; filename=")
        assert headers["Content-Type"] == "image/tiff"
    else:
        assert headers["Content-Disposition"] == 'form-data; name="annotations"'
        assert headers["Content-Type"] == "application/json; charset=utf-8"
    return body


def lnglat_to_tile(lng: float, lat: float, z: int) -> tuple[int, int]:
    n = 2**z
    x = int((lng + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def utm_to_lnglat(x: float, y: float) -> tuple[float, float]:
    lngs, lats = transform("EPSG:32635", "EPSG:4326", [x], [y])
    return lngs[0], lats[0]


def tile_path(body: dict, z: int, x: int, y: int) -> str:
    return body["tileUrl"].removeprefix("http://testserver").format(z=z, x=x, y=y)


def read_png(content: bytes) -> np.ndarray:
    with MemoryFile(content) as mem, mem.open() as ds:
        assert ds.driver == "PNG"
        return ds.read()


def center_tile(body: dict, z: int) -> tuple[int, int]:
    min_x, min_y, max_x, max_y = body["boundsEpsg32635"]
    return lnglat_to_tile(*utm_to_lnglat((min_x + max_x) / 2, (min_y + max_y) / 2), z)


def test_returns_tile_contract():
    body = stored_tiles(make_geotiff())
    assert tif.RASTER_ID.fullmatch(body["id"])
    assert body["boundsEpsg32635"] == pytest.approx(
        [UL_X, UL_Y - 300 * PIXEL_M, UL_X + 300 * PIXEL_M, UL_Y], abs=1e-6
    )
    assert body["tileUrl"] == f"http://testserver/tiles/{body['id']}/{{z}}/{{x}}/{{y}}.png"
    assert body["maxzoom"] == 22
    assert 0 <= body["minzoom"] < body["maxzoom"]


def test_tile_intersecting_raster_is_png():
    body = stored_tiles(make_geotiff())
    z = body["maxzoom"]
    res = client.get(tile_path(body, z, *center_tile(body, z)), headers={"Origin": "http://localhost:5173"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"
    rgba = read_png(res.content)
    assert rgba.shape == (4, 256, 256)
    opaque = rgba[3] == 255
    assert opaque.sum() > 1000
    assert rgba[:3, opaque].mean(axis=1) == pytest.approx(COLOR, abs=4)  # stored as a JPEG COG


def test_challenge_sized_tile_becomes_cog_with_overviews():
    body = stored_tiles(make_geotiff(size=2048))
    assert body["maxzoom"] == 22
    with rasterio.open(tif.find_raster(body["id"])) as ds:
        assert ds.tags(ns="IMAGE_STRUCTURE")["LAYOUT"] == "COG"
        assert ds.overviews(1)

    z = body["minzoom"]
    rgba = read_png(client.get(tile_path(body, z, *center_tile(body, z))).content)
    assert rgba.shape == (4, 256, 256)
    assert 0 < (rgba[3] > 0).sum() < 256 * 256


def test_tile_outside_raster_is_transparent():
    body = stored_tiles(make_geotiff())
    z = body["maxzoom"]
    x, y = center_tile(body, z)
    res = client.get(tile_path(body, z, x + 50, y))
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    rgba = read_png(res.content)
    assert rgba.shape == (4, 256, 256)
    assert not rgba[3].any()


def test_unknown_raster_returns_404():
    assert client.get(f"/tiles/{'0' * 32}/0/0/0.png").status_code == 404
    assert client.get("/tiles/..%2F..%2Fetc/0/0/0.png").status_code == 404


def test_out_of_range_tile_returns_404():
    body = stored_tiles(make_geotiff())
    assert client.get(tile_path(body, 3, 8, 0)).status_code == 404


def test_reprojects_geographic_bounds_to_utm():
    lng, lat = utm_to_lnglat(UL_X, UL_Y)
    data = make_geotiff(crs="EPSG:4326", transform_=from_origin(lng, lat, 3e-7, 2e-7))
    body = stored_tiles(data)
    min_x, min_y, max_x, max_y = body["boundsEpsg32635"]
    assert min_x == pytest.approx(UL_X, abs=0.5)
    assert max_y == pytest.approx(UL_Y, abs=0.5)
    assert max_x - min_x == pytest.approx(300 * 3e-7 * 111320 * math.cos(math.radians(lat)), rel=0.05)


def test_tiff_without_crs_returns_400(upload_dir):
    exc = store_error(make_geotiff(crs=None))
    assert exc.status_code == 400
    assert "no georeferencing" in exc.detail
    assert not any(upload_dir.iterdir())


def test_unreadable_tiff_returns_400(upload_dir):
    exc = store_error(b"II+\x00" + b"\x08\x00\x00\x00" + bytes(64), name="big.tif")
    assert exc.status_code == 400
    assert exc.detail == "Uploaded TIFF could not be read as a raster."
    assert not any(upload_dir.iterdir())


def test_accepts_octet_stream():
    res = upload(make_geotiff(), name="tile.tiff", content_type="application/octet-stream")
    assert res.status_code == 200


def test_streams_large_upload_in_chunks(monkeypatch):
    data = make_geotiff() + bytes(range(256)) * (5 * CHUNK_SIZE // 256 + 123)
    read_sizes = []
    original_read = UploadFile.read

    async def spy_read(self, size=-1):
        read_sizes.append(size)
        return await original_read(self, size)

    monkeypatch.setattr(UploadFile, "read", spy_read)

    res = upload(data, name="large.tif")

    assert res.status_code == 200
    assert len(read_sizes) > len(data) // CHUNK_SIZE
    assert all(0 < size <= CHUNK_SIZE for size in read_sizes)


def test_missing_file_returns_400():
    res = client.post("/process-tif")
    assert res.status_code == 400
    assert "No file uploaded" in res.json()["detail"]


def test_empty_file_returns_400():
    res = upload(b"")
    assert res.status_code == 400
    assert res.json()["detail"] == "Uploaded file is empty."


def test_non_tiff_returns_400():
    res = upload(b"\x89PNG\r\n\x1a\n", name="photo.png", content_type="image/png")
    assert res.status_code == 400
    assert res.json()["detail"] == "Uploaded file is not a TIFF."


def test_cors_allows_vite_dev_origin():
    res = client.options(
        "/process-tif",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_known_filename_returns_annotations_then_tiff():
    data = make_geotiff()
    res = upload(data, name="siret3_r021_c012.tif")
    assert res.status_code == 200
    assert res.headers["content-type"] == f"multipart/mixed; boundary={BOUNDARY}"
    annotations, tiff = parse_multipart(res.content)
    assert tiff == data
    assert annotations["image"] == "siret3_r021_c012.tif"
    assert (annotations["width"], annotations["height"]) == (2048, 2048)
    assert Counter(item["label"] for item in annotations["items"]) == {
        "row": 25,
        "interrow_area": 24,
        "vineyard": 399,
    }
    assert annotations["items"][0] == {
        "label": "row",
        "shape": "polyline",
        "points": [[2048.0, 32.1], [2017.8, 0.0]],
        "attributes": {"vineyard_id": "V01", "row_id": "V01-R01", "row_structure": "regular"},
    }
    assert all("id" not in item for item in annotations["items"])
    assert {item["attributes"]["vineyard_id"] for item in annotations["items"]} == {"V01"}


def test_second_example_image_returns_only_its_annotations():
    data = make_geotiff()
    res = upload(data, name="siret3_r006_c004.tif")
    assert res.status_code == 200
    annotations, tiff = parse_multipart(res.content)
    assert tiff == data
    assert annotations["image"] == "siret3_r006_c004.tif"
    assert (annotations["width"], annotations["height"]) == (2048, 2048)
    assert Counter(item["label"] for item in annotations["items"]) == {
        "row": 26,
        "interrow_area": 25,
        "vineyard": 251,
    }
    assert annotations["items"][0]["attributes"]["row_id"] == "V02-R01"
    assert annotations["items"][0]["points"] == [[2048.0, 188.5], [1967.1, 0.0]]
    assert {item["attributes"]["vineyard_id"] for item in annotations["items"]} == {"V02"}


def test_directory_prefix_matches_image_basename():
    data = make_geotiff()
    res = upload(data, name="images/siret3_r021_c012.tif")
    assert res.status_code == 200
    annotations, tiff = parse_multipart(res.content)
    assert annotations["image"] == "siret3_r021_c012.tif"
    assert tiff == data
    assert b'filename="images/siret3_r021_c012.tif"' in res.content


def test_unmatched_filename_streams_the_tiff():
    data = make_geotiff()
    res = upload(data, name="other.tif")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/tiff"
    assert res.headers["content-disposition"] == 'attachment; filename="other.tif"'
    assert res.content == data

    near = upload(data, name="siret3_r021_c012.tiff")
    assert near.status_code == 200
    assert near.headers["content-type"] == "image/tiff"
    assert near.content == data

    xtiff = upload(data, name="other.tif", content_type="image/x-tiff")
    assert xtiff.status_code == 200
    assert xtiff.headers["content-type"] == "image/x-tiff"
    assert xtiff.content == data


def test_broken_annotations_file_falls_back_to_tiff(monkeypatch, tmp_path, caplog):
    data = make_geotiff()
    missing = tmp_path / "missing.xml"
    monkeypatch.setattr(cvat_annotations, "ANNOTATIONS_PATH", missing)
    with caplog.at_level("ERROR"):
        res = upload(data, name="siret3_r021_c012.tif")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/tiff"
    assert res.content == data
    assert any("Could not load CVAT annotations" in record.message for record in caplog.records)

    bad = tmp_path / "bad.xml"
    bad.write_text("<annotations>", encoding="utf-8")
    monkeypatch.setattr(cvat_annotations, "ANNOTATIONS_PATH", bad)
    broken = upload(data, name="siret3_r006_c004.tif")
    assert broken.status_code == 200
    assert broken.headers["content-type"] == "image/tiff"
    assert broken.content == data
