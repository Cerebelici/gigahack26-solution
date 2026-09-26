import json

import pytest
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from sqlalchemy import text

from app.main import app
from app.services import tif
from tests.test_process_tif import (
    COLOR,
    PIXEL_M,
    UL_X,
    UL_Y,
    center_tile,
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
    assert project["features"]["type"] == "FeatureCollection"
    assert project["features"]["features"] == []

    res = client.patch(f"/projects/{project['id']}", json={"name": "Renamed"}, headers=auth(token))
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed"

    got = client.get(f"/projects/{project['id']}", headers=auth(token))
    assert got.status_code == 200 and got.json()["name"] == "Renamed"

    listed = client.get("/projects", headers=auth(token)).json()
    assert [p["id"] for p in listed] == [project["id"]]


def test_projects_are_private_to_their_owner(project):
    other = signup(email="other@example.com")["token"]
    assert client.get("/projects", headers=auth(other)).json() == []
    assert client.get(f"/projects/{project['id']}", headers=auth(other)).status_code == 404
    assert client.patch(f"/projects/{project['id']}", json={"name": "x"}, headers=auth(other)).status_code == 404
    route = {"routeType": "x", "obstacles": [], "start": [0, 0], "targets": []}
    assert client.post(f"/projects/{project['id']}/routes", json=route, headers=auth(other)).status_code == 404


def test_projects_require_auth(db_conn):
    assert client.get("/projects").status_code == 401
    assert client.post("/projects", json={"name": "x"}).status_code == 401


# Raster upload


def test_raster_upload_is_stored_under_upload_dir_and_tiles(token, project, upload_dir, db_conn):
    res = upload_raster(token, project["id"])
    assert res.status_code == 200, res.text
    raster = res.json()
    assert tif.RASTER_ID.fullmatch(raster["id"])
    assert raster["tileUrl"] == f"http://testserver/tiles/{raster['id']}/{{z}}/{{x}}/{{y}}.png"
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


def test_raster_upload_rejects_non_tiff_and_foreign_project(token, project, upload_dir):
    res = client.post(
        f"/projects/{project['id']}/raster", files={"file": ("a.png", b"\x89PNG\r\n", "image/png")}, headers=auth(token)
    )
    assert res.status_code == 400
    other = signup(email="other@example.com")["token"]
    assert upload_raster(other, project["id"]).status_code == 404
    anonymous = client.post(f"/projects/{project['id']}/raster", files={"file": ("t.tif", make_geotiff(), "image/tiff")})
    assert anonymous.status_code == 401
    assert not any(upload_dir.iterdir())


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
