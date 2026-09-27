import json
import zipfile
from io import BytesIO

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.windows import Window
from sqlalchemy import text

from app.main import app
from app.services import cvat_annotations, tif
from tests.test_process_tif import (
    COLOR,
    PIXEL_M,
    UL_X,
    UL_Y,
    center_tile,
    lnglat_to_tile,
    make_geotiff,
    read_png,
    tile_path,
    utm_to_lnglat,
)

client = TestClient(app)

PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tif, "UPLOAD_DIR", tmp_path)
    return tmp_path


def signup(email: str = "ion@example.com", password: str = PASSWORD, name: str = "Ion") -> dict:
    res = client.post("/auth/signup", json={"email": email, "password": password, "name": name})
    assert res.status_code == 201, res.text
    return res.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def token(db_conn) -> str:
    return signup()["token"]


@pytest.fixture
def project(token) -> dict:
    res = client.post("/projects", json={"name": "Sireț3 north"}, headers=auth(token))
    assert res.status_code == 201, res.text
    return res.json()


def upload_raster(token: str, project_id: int, data: bytes | None = None):
    files = {"file": ("tile.tif", data or make_geotiff(), "image/tiff")}
    return client.post(f"/projects/{project_id}/raster", files=files, headers=auth(token))


def pixel_to_utm(x: float, y: float, pixel_m: float = PIXEL_M) -> tuple[float, float]:
    return UL_X + x * pixel_m, UL_Y - y * pixel_m


# Auth


def test_signup_returns_token_and_user(db_conn):
    body = signup(email="  Ion@Example.com ")
    assert body["user"] == {"id": body["user"]["id"], "email": "ion@example.com", "name": "Ion"}
    assert body["token"]
    stored = db_conn.execute(text("SELECT password_hash FROM users")).scalar_one()
    assert stored.startswith("$argon2") and PASSWORD not in stored


def test_signup_rejects_duplicate_email(db_conn):
    signup()
    res = client.post("/auth/signup", json={"email": "ION@example.com", "password": PASSWORD, "name": "Other"})
    assert res.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": PASSWORD, "name": "Ion"},
        {"email": "ion@example.com", "password": "short", "name": "Ion"},
        {"email": "ion@example.com", "password": PASSWORD, "name": "   "},
    ],
)
def test_signup_validates_fields(db_conn, payload):
    assert client.post("/auth/signup", json=payload).status_code == 422


def test_login(db_conn):
    user = signup()["user"]
    res = client.post("/auth/login", json={"email": "ION@example.com", "password": PASSWORD})
    assert res.status_code == 200
    assert res.json()["user"] == user
    me = client.get("/auth/me", headers=auth(res.json()["token"]))
    assert me.status_code == 200 and me.json() == user


def test_login_rejects_bad_credentials(db_conn):
    signup()
    assert client.post("/auth/login", json={"email": "ion@example.com", "password": "wrong password"}).status_code == 401
    assert client.post("/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}).status_code == 401


def test_me_requires_valid_token(db_conn):
    res = client.get("/auth/me")
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == "Bearer"
    assert client.get("/auth/me", headers=auth("garbage")).status_code == 401


def test_update_me_changes_name_and_password(token):
    res = client.patch("/auth/me", json={"name": "Ion Popescu", "password": "a brand new secret"}, headers=auth(token))
    assert res.status_code == 200
    assert res.json()["name"] == "Ion Popescu"
    assert client.get("/auth/me", headers=auth(token)).json()["name"] == "Ion Popescu"
    old = client.post("/auth/login", json={"email": "ion@example.com", "password": PASSWORD})
    new = client.post("/auth/login", json={"email": "ion@example.com", "password": "a brand new secret"})
    assert old.status_code == 401
    assert new.status_code == 200


def test_update_me_requires_auth(db_conn):
    assert client.patch("/auth/me", json={"name": "X"}).status_code == 401


# Projects


def test_create_and_update_project(token, project):
    assert project["name"] == "Sireț3 north"
    assert project["raster"] is None
    assert "features" not in project

    res = client.patch(f"/projects/{project['id']}", json={"name": "Renamed"}, headers=auth(token))
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed"
    assert "features" not in res.json()

    got = client.get(f"/projects/{project['id']}", headers=auth(token))
    assert got.status_code == 200 and got.json()["name"] == "Renamed"
    assert got.json()["features"]["type"] == "FeatureCollection"
    assert got.json()["features"]["features"] == []

    listed = client.get("/projects", headers=auth(token)).json()
    assert [p["id"] for p in listed] == [project["id"]]
    assert "features" not in listed[0]


def test_projects_are_private_to_their_owner(project):
    other = signup(email="other@example.com")["token"]
    assert client.get("/projects", headers=auth(other)).json() == []
    assert client.get(f"/projects/{project['id']}", headers=auth(other)).status_code == 404
    assert client.patch(f"/projects/{project['id']}", json={"name": "x"}, headers=auth(other)).status_code == 404
    assert client.delete(f"/projects/{project['id']}", headers=auth(other)).status_code == 404
    route = {"routeType": "x", "obstacles": [], "start": [0, 0], "targets": []}
    assert client.post(f"/projects/{project['id']}/routes", json=route, headers=auth(other)).status_code == 404


def test_projects_require_auth(db_conn):
    assert client.get("/projects").status_code == 401
    assert client.post("/projects", json={"name": "x"}).status_code == 401
    assert client.delete("/projects/1").status_code == 401


def test_delete_project_removes_it_and_its_imagery(token, project, upload_dir):
    raster = upload_raster(token, project["id"]).json()
    folder = upload_dir / raster["id"]
    assert folder.is_dir()

    res = client.delete(f"/projects/{project['id']}", headers=auth(token))

    assert res.status_code == 204
    assert res.content == b""
    assert client.get(f"/projects/{project['id']}", headers=auth(token)).status_code == 404
    assert client.get("/projects", headers=auth(token)).json() == []
    assert not folder.exists()


# Raster upload


def test_raster_upload_is_stored_under_upload_dir_and_tiles(token, project, upload_dir, db_conn):
    res = upload_raster(token, project["id"])
    assert res.status_code == 200, res.text
    raster = res.json()
    assert tif.RASTER_ID.fullmatch(raster["id"])
    assert raster["tileUrl"] == f"http://testserver/tiles/{raster['id']}/{{z}}/{{x}}/{{y}}.png?v=2"
    assert raster["boundsEpsg32635"] == pytest.approx([UL_X, UL_Y - 300 * PIXEL_M, UL_X + 300 * PIXEL_M, UL_Y])
    assert raster["maxzoom"] == 22
    assert (upload_dir / raster["id"] / "raster.tif").is_file()

    assert client.get(f"/projects/{project['id']}", headers=auth(token)).json()["raster"] == raster

    row = db_conn.execute(text("SELECT width, height, transform, srid FROM rasters")).one()
    assert (row.width, row.height, row.srid) == (300, 300, 32635)
    assert row.transform == pytest.approx([PIXEL_M, 0, UL_X, 0, -PIXEL_M, UL_Y])

    z = raster["maxzoom"]
    tile = client.get(tile_path(raster, z, *center_tile(raster, z)))
    assert tile.status_code == 200
    assert tile.headers["content-type"] == "image/png"
    rgba = read_png(tile.content)
    opaque = rgba[3] == 255
    assert opaque.sum() > 1000
    assert rgba[:3, opaque].mean(axis=1) == pytest.approx(COLOR, abs=4)


def test_raster_upload_replaces_current_raster(token, project):
    first = upload_raster(token, project["id"]).json()
    second = upload_raster(token, project["id"]).json()
    assert first["id"] != second["id"]
    assert client.get(f"/projects/{project['id']}", headers=auth(token)).json()["raster"]["id"] == second["id"]


# Catalog tile r017_c010 has its top-left corner at (629504.0, 5220352.0) on the challenge grid.
TILE_WEST, TILE_NORTH = 629504.0, 5220352.0
CATALOG = {
    "siret3_r017_c010.tif": {
        "image": "siret3_r017_c010.tif",
        "width": 2048,
        "height": 2048,
        "items": [
            {
                "id": "1",
                "label": "vineyard",
                "shape": "polygon",
                "points": [[20, 20], [60, 20], [60, 60]],
                "attributes": {"vineyard_id": "V01"},
            },
            {
                "id": "2",
                "label": "row",
                "shape": "polyline",
                "points": [[0, 100], [200, 100]],
                "attributes": {"vineyard_id": "V01", "row_id": "V01-R01", "row_structure": "not-a-structure"},
            },
            {"id": "3", "label": "waste", "shape": "rectangle", "points": [[10, 10], [30, 10], [30, 40], [10, 40]]},
            {"id": "4", "label": "vineyard", "shape": "polygon", "points": [[1, 1], [2, 2]]},
            {"id": "5", "label": "vineyard", "shape": "polygon", "points": [[1000, 1000], [1010, 1000], [1010, 1010]]},
        ],
    }
}


def tile_geotiff(pixel_m: float = PIXEL_M) -> bytes:
    return make_geotiff(transform_=from_origin(TILE_WEST, TILE_NORTH, pixel_m, pixel_m))


def test_raster_upload_places_catalog_shapes_by_location_not_file_name(token, project, monkeypatch):
    monkeypatch.setattr(cvat_annotations, "catalog", lambda: CATALOG)
    assert upload_raster(token, project["id"], tile_geotiff()).status_code == 200

    opened = client.get(f"/projects/{project['id']}", headers=auth(token)).json()
    listed = client.get("/projects", headers=auth(token)).json()
    assert "features" not in listed[0]

    features = opened["features"]["features"]
    by_label = {feature["properties"]["label"]: feature for feature in features}
    assert sorted(by_label) == ["row", "vineyard", "waste"], "invalid and off-raster shapes are skipped"

    vineyard = by_label["vineyard"]
    assert vineyard["properties"]["vineyard_id"] == "V01"
    assert vineyard["properties"]["pixelRings"] == [[pytest.approx(p) for p in [[20, 20], [60, 20], [60, 60]]]]
    expected = [[TILE_WEST + x * PIXEL_M, TILE_NORTH - y * PIXEL_M] for x, y in [(20, 20), (60, 20), (60, 60), (20, 20)]]
    assert vineyard["geometry"]["coordinates"][0] == [pytest.approx(p, abs=1e-6) for p in expected]

    row = by_label["row"]["properties"]
    assert (row["row_id"], row["row_structure"]) == (None, None), "an invalid attribute drops the item's attributes"
    assert by_label["waste"]["properties"]["pixelBox"] == pytest.approx({"xtl": 10, "ytl": 10, "xbr": 30, "ybr": 40})

    assert upload_raster(token, project["id"], tile_geotiff()).status_code == 200
    again = client.get(f"/projects/{project['id']}/annotations", headers=auth(token)).json()["features"]
    assert len(again) == 3, "a new upload replaces the previous raster's annotations"


def test_catalog_shapes_follow_the_raster_pixel_size(token, project, monkeypatch):
    monkeypatch.setattr(cvat_annotations, "catalog", lambda: CATALOG)
    upload_raster(token, project["id"], tile_geotiff(pixel_m=PIXEL_M * 2))
    features = client.get(f"/projects/{project['id']}/annotations", headers=auth(token)).json()["features"]
    vineyard = next(feature for feature in features if feature["properties"]["label"] == "vineyard")
    assert vineyard["properties"]["pixelRings"] == [[pytest.approx(p) for p in [[10, 10], [30, 10], [30, 30]]]]


def test_raster_without_catalog_shapes_keeps_existing_annotations(token, project, monkeypatch):
    monkeypatch.setattr(cvat_annotations, "catalog", lambda: CATALOG)
    upload_raster(token, project["id"], tile_geotiff())
    far_away = make_geotiff(transform_=from_origin(TILE_WEST + 500, TILE_NORTH, PIXEL_M, PIXEL_M))
    upload_raster(token, project["id"], far_away)
    assert len(client.get(f"/projects/{project['id']}/annotations", headers=auth(token)).json()["features"]) == 3


def test_raster_upload_rejects_non_tiff_and_foreign_project(token, project, upload_dir):
    res = client.post(
        f"/projects/{project['id']}/raster", files={"file": ("a.png", b"\x89PNG\r\n", "image/png")}, headers=auth(token)
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "Send a GeoTIFF (.tif, .tiff) or a zip of GeoTIFFs and their CVAT XML files."
    other = signup(email="other@example.com")["token"]
    assert upload_raster(other, project["id"]).status_code == 404
    anonymous = client.post(f"/projects/{project['id']}/raster", files={"file": ("t.tif", make_geotiff(), "image/tiff")})
    assert anonymous.status_code == 401
    assert not any(upload_dir.iterdir())


# A zip of tiles. Left tile is 32 m square at the challenge tile's origin; an 8 m gap; then the right tile.
ZIP_WEST, ZIP_NORTH = 629504.0, 5220352.0
ZIP_SIZE = 32
ZIP_GAP = 8
LEFT_COLOR = (10, 40, 200)
RIGHT_COLOR = (220, 30, 30)


def solid_geotiff(
    west: float, north: float, color: tuple[int, int, int], size: int = ZIP_SIZE, pixel: float = 1
) -> bytes:
    data = np.empty((3, size, size), dtype=np.uint8)
    data[0], data[1], data[2] = color
    with MemoryFile() as mem:
        with mem.open(
            driver="GTiff",
            width=size,
            height=size,
            count=3,
            dtype="uint8",
            crs="EPSG:32635",
            transform=from_origin(west, north, pixel, pixel),
        ) as dst:
            dst.write(data)
        return mem.read()


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def upload_zip(token: str, project_id: int, data: bytes):
    files = {"file": ("tiles.zip", data, "application/zip")}
    return client.post(f"/projects/{project_id}/raster", files=files, headers=auth(token))


TILES_XML = """<?xml version="1.0" encoding="utf-8"?>
<annotations>
  <image name="left.tif" width="32" height="32">
    <polygon label="vineyard" points="2,2;8,2;8,8">
      <attribute name="vineyard_id">FROMZIP</attribute>
    </polygon>
    <box label="waste" xtl="1" ytl="2" xbr="5" ybr="7">
      <attribute name="vineyard_id">FROMZIP</attribute>
    </box>
  </image>
  <image name="tiles/right.tif" width="32" height="32">
    <polyline label="row" points="0,10;31,10">
      <attribute name="vineyard_id">V02</attribute>
      <attribute name="row_id">V02-R01</attribute>
      <attribute name="row_structure">regular</attribute>
    </polyline>
  </image>
</annotations>
"""


def test_zip_of_tiles_becomes_one_map_with_annotations(token, project, upload_dir, monkeypatch):
    monkeypatch.setattr(cvat_annotations, "catalog", lambda: CATALOG)
    right_west = ZIP_WEST + ZIP_SIZE + ZIP_GAP
    payload = zip_bytes(
        {
            "tiles/left.tif": solid_geotiff(ZIP_WEST, ZIP_NORTH, LEFT_COLOR),
            "tiles/right.tif": solid_geotiff(right_west, ZIP_NORTH, RIGHT_COLOR),
            "tiles/annotations.xml": TILES_XML.encode(),
            "tiles/readme.txt": b"ignored",
        }
    )
    res = upload_zip(token, project["id"], payload)
    assert res.status_code == 200, res.text
    raster = res.json()
    assert raster["boundsEpsg32635"] == pytest.approx(
        [ZIP_WEST, ZIP_NORTH - ZIP_SIZE, right_west + ZIP_SIZE, ZIP_NORTH], abs=1e-3
    )

    with rasterio.open(upload_dir / raster["id"] / "raster.tif") as ds:
        assert (ds.width, ds.height) == (ZIP_SIZE + ZIP_GAP + ZIP_SIZE, ZIP_SIZE)
        assert tuple(int(v) for v in ds.read(window=Window(4, 4, 1, 1))[:3, 0, 0]) == LEFT_COLOR
        assert tuple(int(v) for v in ds.read(window=Window(ZIP_SIZE + ZIP_GAP + 10, 4, 1, 1))[:3, 0, 0]) == RIGHT_COLOR
        assert int(ds.read(4, window=Window(ZIP_SIZE + ZIP_GAP // 2, 4, 1, 1))[0, 0]) == 0

    body = client.get(f"/projects/{project['id']}", headers=auth(token)).json()
    by_label = {feature["properties"]["label"]: feature for feature in body["features"]["features"]}
    assert sorted(by_label) == ["row", "vineyard", "waste"]
    assert by_label["vineyard"]["properties"]["vineyard_id"] == "FROMZIP"
    assert by_label["vineyard"]["properties"]["pixelRings"] == [[[pytest.approx(v, abs=1e-3) for v in point] for point in [[2, 2], [8, 2], [8, 8]]]]
    expected = [
        [ZIP_WEST + 2, ZIP_NORTH - 2],
        [ZIP_WEST + 8, ZIP_NORTH - 2],
        [ZIP_WEST + 8, ZIP_NORTH - 8],
        [ZIP_WEST + 2, ZIP_NORTH - 2],
    ]
    assert by_label["vineyard"]["geometry"]["coordinates"][0] == [pytest.approx(p, abs=1e-3) for p in expected]
    assert by_label["waste"]["properties"]["pixelBox"] == pytest.approx({"xtl": 1, "ytl": 2, "xbr": 5, "ybr": 7}, abs=1e-3)
    assert by_label["row"]["properties"]["row_id"] == "V02-R01"
    assert by_label["row"]["geometry"]["coordinates"] == [
        pytest.approx(p, abs=1e-3) for p in [[right_west, ZIP_NORTH - 10], [right_west + 31, ZIP_NORTH - 10]]
    ]

    z = raster["maxzoom"]
    lng, lat = utm_to_lnglat(ZIP_WEST + ZIP_SIZE / 2, ZIP_NORTH - ZIP_SIZE / 2)
    tile = client.get(tile_path(raster, z, *lnglat_to_tile(lng, lat, z)))
    assert tile.status_code == 200
    rgba = read_png(tile.content)
    samples = rgba[:3].reshape(3, -1)[:, rgba[3].reshape(-1) > 200]
    assert samples.shape[1] > 100
    left = np.abs(samples - np.array(LEFT_COLOR)[:, None]) <= 8
    assert left.all(axis=0).any()

    replacement = zip_bytes(
        {
            "left.tif": solid_geotiff(ZIP_WEST, ZIP_NORTH, LEFT_COLOR),
            "only.xml": """<annotations><image name="left.tif" width="32" height="32">
              <polygon label="vineyard" points="2,2;8,2;8,8"><attribute name="vineyard_id">V99</attribute></polygon>
            </image></annotations>""".encode(),
        }
    )
    assert upload_zip(token, project["id"], replacement).status_code == 200
    features = client.get(f"/projects/{project['id']}/annotations", headers=auth(token)).json()["features"]
    assert [feature["properties"]["vineyard_id"] for feature in features] == ["V99"]


def test_several_zips_become_one_map(token, project, upload_dir):
    right_west = ZIP_WEST + ZIP_SIZE + ZIP_GAP
    left_xml = """<?xml version="1.0" encoding="utf-8"?>
    <annotations><image name="left.tif" width="32" height="32">
      <polygon label="vineyard" points="2,2;8,2;8,8"><attribute name="vineyard_id">WEST</attribute></polygon>
    </image></annotations>"""
    right_xml = """<?xml version="1.0" encoding="utf-8"?>
    <annotations><image name="right.tif" width="32" height="32">
      <polyline label="row" points="0,10;31,10">
        <attribute name="vineyard_id">V02</attribute>
        <attribute name="row_id">V02-R01</attribute>
        <attribute name="row_structure">regular</attribute>
      </polyline>
    </image></annotations>"""
    res = client.post(
        f"/projects/{project['id']}/raster",
        files=[
            ("file", ("west.zip", zip_bytes({"left.tif": solid_geotiff(ZIP_WEST, ZIP_NORTH, LEFT_COLOR), "a.xml": left_xml.encode()}), "application/zip")),
            ("file", ("east.zip", zip_bytes({"right.tif": solid_geotiff(right_west, ZIP_NORTH, RIGHT_COLOR), "b.xml": right_xml.encode()}), "application/zip")),
        ],
        headers=auth(token),
    )
    assert res.status_code == 200, res.text
    raster = res.json()
    assert raster["boundsEpsg32635"] == pytest.approx(
        [ZIP_WEST, ZIP_NORTH - ZIP_SIZE, right_west + ZIP_SIZE, ZIP_NORTH], abs=1e-3
    )
    with rasterio.open(upload_dir / raster["id"] / "raster.tif") as ds:
        assert (ds.width, ds.height) == (ZIP_SIZE + ZIP_GAP + ZIP_SIZE, ZIP_SIZE)
        assert tuple(int(v) for v in ds.read(window=Window(4, 4, 1, 1))[:3, 0, 0]) == LEFT_COLOR
        assert tuple(int(v) for v in ds.read(window=Window(ZIP_SIZE + ZIP_GAP + 10, 4, 1, 1))[:3, 0, 0]) == RIGHT_COLOR

    features = client.get(f"/projects/{project['id']}/annotations", headers=auth(token)).json()["features"]
    by_label = {feature["properties"]["label"]: feature for feature in features}
    assert by_label["vineyard"]["properties"]["vineyard_id"] == "WEST"
    assert by_label["row"]["properties"]["row_id"] == "V02-R01"
    assert by_label["row"]["geometry"]["coordinates"] == [
        pytest.approx(p, abs=1e-3) for p in [[right_west, ZIP_NORTH - 10], [right_west + 31, ZIP_NORTH - 10]]
    ]


def test_adjacent_zip_tiles_share_an_edge(token, project, upload_dir):
    pixel = 0.025
    size = 64
    west, north = 629504.0, 5220352.0
    res = upload_zip(
        token,
        project["id"],
        zip_bytes(
            {
                "a.tif": solid_geotiff(west, north, LEFT_COLOR, size=size, pixel=pixel),
                "b.tif": solid_geotiff(west + size * pixel, north, RIGHT_COLOR, size=size, pixel=pixel),
            }
        ),
    )
    assert res.status_code == 200, res.text
    with rasterio.open(upload_dir / res.json()["id"] / "raster.tif") as ds:
        assert (ds.width, ds.height) == (size * 2, size)
        mid = size // 2
        assert tuple(int(v) for v in ds.read(window=Window(size - 1, mid, 1, 1))[:3, 0, 0]) == LEFT_COLOR
        assert tuple(int(v) for v in ds.read(window=Window(size, mid, 1, 1))[:3, 0, 0]) == RIGHT_COLOR
        assert int(ds.read(4, window=Window(size - 1, mid, 1, 1))[0, 0]) == 255
        assert int(ds.read(4, window=Window(size, mid, 1, 1))[0, 0]) == 255


def plain_tiff(color: tuple[int, int, int], size: int = 32) -> bytes:
    data = np.empty((3, size, size), dtype=np.uint8)
    data[0], data[1], data[2] = color
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=size, height=size, count=3, dtype="uint8") as dst:
            dst.write(data)
        return mem.read()


def test_cvat_export_without_geotags_uses_the_challenge_grid(token, project, upload_dir):
    # r005_c004: top-left (628992 + 4 * 51.2, 5221222.4 - 5 * 51.2), a 51.2 m square.
    west, north, tile_m = 629196.8, 5220966.4, 51.2
    size = 32
    pixel = tile_m / size
    xml = """<?xml version="1.0" encoding="utf-8"?>
    <annotations><image name="siret3_r005_c004.tif" width="32" height="32">
      <polygon label="vineyard" points="2,2;8,2;8,8"><attribute name="vineyard_id">GRID</attribute></polygon>
    </image></annotations>"""
    res = upload_zip(
        token,
        project["id"],
        zip_bytes({"images/6436_siret3_r005_c004.tif": plain_tiff(LEFT_COLOR, size), "annotations.xml": xml.encode()}),
    )
    assert res.status_code == 200, res.text
    assert res.json()["boundsEpsg32635"] == pytest.approx(
        [west, north - tile_m, west + tile_m, north], abs=1e-3
    )
    features = client.get(f"/projects/{project['id']}/annotations", headers=auth(token)).json()["features"]
    assert len(features) == 1
    assert features[0]["properties"]["vineyard_id"] == "GRID"
    assert features[0]["geometry"]["coordinates"][0] == [
        pytest.approx(point, abs=1e-3)
        for point in [
            [west + 2 * pixel, north - 2 * pixel],
            [west + 8 * pixel, north - 2 * pixel],
            [west + 8 * pixel, north - 8 * pixel],
            [west + 2 * pixel, north - 2 * pixel],
        ]
    ]
    with rasterio.open(upload_dir / res.json()["id"] / "raster.tif") as ds:
        assert tuple(int(v) for v in ds.read(window=Window(4, 4, 1, 1))[:3, 0, 0]) == LEFT_COLOR


def test_named_geotiff_keeps_its_own_position(token, project):
    west, north = 1000.0, 2000.0
    res = upload_zip(
        token,
        project["id"],
        zip_bytes({"siret3_r005_c004.tif": solid_geotiff(west, north, LEFT_COLOR, size=32, pixel=1)}),
    )
    assert res.status_code == 200, res.text
    assert res.json()["boundsEpsg32635"] == pytest.approx([west, north - 32, west + 32, north], abs=1e-3)


def test_plain_tiff_without_a_challenge_name_is_rejected(token, project, upload_dir):
    res = upload_zip(token, project["id"], zip_bytes({"notes.tif": plain_tiff(LEFT_COLOR)}))
    assert res.status_code == 400
    assert res.json()["detail"] == "notes.tif has no georeferencing (CRS and geotransform)."
    assert not any(upload_dir.iterdir())


def test_zip_without_a_geotiff_is_rejected(token, project, upload_dir):
    res = upload_zip(
        token,
        project["id"],
        zip_bytes({"notes.xml": b"<annotations></annotations>", "../outside.tif": b"II*\x00not-a-tiff"}),
    )
    assert res.status_code == 400
    assert "GeoTIFF" in res.json()["detail"]
    assert not (upload_dir.parent / "outside.tif").exists()
    assert not any(path.name == "outside.tif" for path in upload_dir.rglob("*"))

    corrupt = client.post(
        f"/projects/{project['id']}/raster",
        files={"file": ("bad.zip", b"PK\x03\x04not-a-zip", "application/zip")},
        headers=auth(token),
    )
    assert corrupt.status_code == 400
    assert corrupt.json()["detail"] == "Uploaded file is not a valid zip."


# Annotations


def test_annotation_requires_raster(token, project):
    res = client.post(
        f"/projects/{project['id']}/annotations",
        json={"label": "vineyard", "rings": [[0, 0], [10, 0], [10, 10]]},
        headers=auth(token),
    )
    assert res.status_code == 409


def test_polygon_annotation_round_trips_pixels_and_lands_in_postgis(token, project, db_conn):
    upload_raster(token, project["id"])
    ring = [[100, 200], [300, 200], [300, 400.5], [100, 400.5]]
    res = client.post(
        f"/projects/{project['id']}/annotations",
        json={"label": "vineyard", "rings": ring, "vineyard_id": "V01", "area_m2": 25.1},
        headers=auth(token),
    )
    assert res.status_code == 201, res.text
    feature = res.json()
    props = feature["properties"]
    assert props["label"] == "vineyard"
    assert props["vineyard_id"] == "V01"
    assert props["area_m2"] == 25.1
    assert props["pixelRings"] == [ring]
    assert set(feature["geometry"]) == {"type", "coordinates"}
    assert feature["geometry"]["type"] == "Polygon"
    expected = [list(pixel_to_utm(x, y)) for x, y in ring + [ring[0]]]
    assert feature["geometry"]["coordinates"][0] == [pytest.approx(p, abs=1e-6) for p in expected]

    row = db_conn.execute(
        text(
            "SELECT ST_SRID(geom) AS srid, GeometryType(geom) AS kind, ST_Area(geom) AS area, "
            "ST_XMin(geom) AS xmin, ST_YMax(geom) AS ymax, pixel_rings, shape FROM annotations"
        )
    ).one()
    assert row.srid == 32635
    assert row.kind == "POLYGON"
    assert row.area == pytest.approx((200 * PIXEL_M) * (200.5 * PIXEL_M))
    assert (row.xmin, row.ymax) == pytest.approx(pixel_to_utm(100, 200))
    assert row.pixel_rings == [ring]
    assert row.shape == "polygon"

    index = db_conn.execute(
        text("SELECT indexdef FROM pg_indexes WHERE tablename = 'annotations' AND indexdef ILIKE '%gist%'")
    ).scalar_one()
    assert "(geom)" in index

    listed = client.get(f"/projects/{project['id']}/annotations", headers=auth(token)).json()
    assert listed["type"] == "FeatureCollection"
    assert listed["features"] == [feature]
    assert client.get(f"/projects/{project['id']}", headers=auth(token)).json()["features"]["features"] == [feature]


def test_row_polyline_and_waste_box(token, project, db_conn):
    upload_raster(token, project["id"])
    row = client.post(
        f"/projects/{project['id']}/annotations",
        json={
            "label": "row",
            "rings": [[28, 0], [28, 2048]],
            "vineyard_id": "V01",
            "row_id": "V01-R01",
            "row_structure": "regular",
            "grapevine_count": 40,
        },
        headers=auth(token),
    ).json()
    assert row["geometry"]["type"] == "LineString"
    assert row["geometry"]["coordinates"] == [
        pytest.approx(list(pixel_to_utm(28, 0))),
        pytest.approx(list(pixel_to_utm(28, 2048))),
    ]
    assert row["properties"]["pixelRings"] == [[[28, 0], [28, 2048]]]
    assert row["properties"]["row_structure"] == "regular"

    box = {"xtl": 10, "ytl": 20, "xbr": 50, "ybr": 60}
    waste = client.post(
        f"/projects/{project['id']}/annotations", json={"label": "waste", "box": box}, headers=auth(token)
    ).json()
    assert waste["geometry"]["type"] == "Polygon"
    assert waste["properties"]["pixelBox"] == box
    assert waste["properties"]["pixelRings"] == [[[10, 20], [50, 20], [50, 60], [10, 60]]]

    lengths = dict(
        db_conn.execute(text("SELECT label, COALESCE(ST_Length(geom), 0) + ST_Area(geom) FROM annotations")).all()
    )
    assert lengths["row"] == pytest.approx(2048 * PIXEL_M)
    assert lengths["waste"] == pytest.approx(40 * PIXEL_M * 40 * PIXEL_M)


def test_annotation_uses_raster_pixel_size(token, project):
    upload_raster(token, project["id"], make_geotiff(transform_=from_origin(UL_X, UL_Y, 0.05, 0.05)))
    feature = client.post(
        f"/projects/{project['id']}/annotations",
        json={"label": "interrow_area", "rings": [[0, 0], [100, 0], [100, 50], [0, 50]], "interrow_cover": "mixed"},
        headers=auth(token),
    ).json()
    corner = feature["geometry"]["coordinates"][0][2]
    assert corner == pytest.approx(list(pixel_to_utm(100, 50, pixel_m=0.05)))


def test_annotation_on_geographic_raster_is_reprojected_to_utm(token, project, db_conn):
    lng, lat = utm_to_lnglat(UL_X, UL_Y)
    upload_raster(token, project["id"], make_geotiff(crs="EPSG:4326", transform_=from_origin(lng, lat, 3e-7, 2e-7)))
    feature = client.post(
        f"/projects/{project['id']}/annotations",
        json={"label": "vineyard", "rings": [[0, 0], [100, 0], [100, 100], [0, 100]]},
        headers=auth(token),
    ).json()
    x0, y0 = feature["geometry"]["coordinates"][0][0]
    assert (x0, y0) == pytest.approx((UL_X, UL_Y), abs=0.05)
    assert db_conn.execute(text("SELECT ST_SRID(geom) FROM annotations")).scalar_one() == 32635
    assert db_conn.execute(text("SELECT srid FROM rasters")).scalar_one() == 4326


@pytest.mark.parametrize(
    "payload",
    [
        {"label": "row", "rings": [[1, 1]]},
        {"label": "vineyard", "rings": [[0, 0], [1, 1]]},
        {"label": "vineyard", "box": {"xtl": 0, "ytl": 0, "xbr": 1, "ybr": 1}},
        {"label": "waste", "box": {"xtl": 5, "ytl": 0, "xbr": 1, "ybr": 1}},
        {"label": "waste", "rings": [[0, 0], [1, 0], [1, 1]], "box": {"xtl": 0, "ytl": 0, "xbr": 1, "ybr": 1}},
        {"label": "vineyard"},
        {"label": "tree", "rings": [[0, 0], [1, 0], [1, 1]]},
        {"label": "row", "rings": [[0, 0], [1, 1]], "row_structure": "Regular"},
        {"label": "vineyard", "rings": [[]]},
    ],
)
def test_annotation_validation(token, project, payload):
    upload_raster(token, project["id"])
    res = client.post(f"/projects/{project['id']}/annotations", json=payload, headers=auth(token))
    assert res.status_code == 422, res.text


def test_polygon_with_hole(token, project):
    upload_raster(token, project["id"])
    rings = [[[0, 0], [100, 0], [100, 100], [0, 100]], [[25, 25], [75, 25], [75, 75], [25, 75]]]
    feature = client.post(
        f"/projects/{project['id']}/annotations", json={"label": "interrow_area", "rings": rings}, headers=auth(token)
    ).json()
    assert len(feature["geometry"]["coordinates"]) == 2
    assert feature["properties"]["pixelRings"] == rings


# Route stub and CORS


def test_route_returns_a_closed_walk_in_map_metres(token, project):
    res = client.post(
        f"/projects/{project['id']}/routes",
        json={
            "routeType": "full_inspection",
            "obstacles": [[[1, 0], [2, 0], [2, 4], [1, 4]]],
            "start": [0, 2],
            "targets": [[4, 2]],
        },
        headers=auth(token),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["route"]["type"] == "LineString"
    assert body["route"]["coordinates"][0] == pytest.approx([0, 2])
    assert body["route"]["coordinates"][-1] == pytest.approx([0, 2])
    assert body["length_m"] > 8
    assert body["unreachable"] == []
    anonymous = {"routeType": "x", "obstacles": [], "start": [0, 0], "targets": []}
    assert client.post(f"/projects/{project['id']}/routes", json=anonymous).status_code == 401
    assert client.post(f"/projects/{project['id']}/routes", json={}, headers=auth(token)).status_code == 422


def test_route_rejects_a_start_inside_an_obstacle(token, project):
    res = client.post(
        f"/projects/{project['id']}/routes",
        json={
            "routeType": "walk",
            "obstacles": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
            "start": [5, 5],
            "targets": [],
        },
        headers=auth(token),
    )
    assert res.status_code == 400
    assert "inside" in res.json()["detail"].lower()


def test_route_reports_an_unreachable_target(token, project):
    res = client.post(
        f"/projects/{project['id']}/routes",
        json={
            "routeType": "walk",
            "obstacles": [[[0, 0], [30, 0], [30, 30], [0, 30]]],
            "start": [-5, 15],
            "targets": [[15, 15]],
        },
        headers=auth(token),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["unreachable"] == [[15, 15]]
    assert body["length_m"] == 0
    assert body["route"]["coordinates"] == [[-5, 15], [-5, 15]]


def test_cors_preflight_allows_authorization_header():
    res = client.options(
        "/projects",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "authorization" in res.headers["access-control-allow-headers"].lower()


def test_feature_collection_is_valid_json_with_crs(token, project):
    body = client.get(f"/projects/{project['id']}/annotations", headers=auth(token)).json()
    assert json.loads(json.dumps(body))["crs"]["properties"]["name"] == "urn:ogc:def:crs:EPSG::32635"
