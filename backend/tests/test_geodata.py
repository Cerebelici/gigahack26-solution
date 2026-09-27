"""Cadastral lookup: a map click's latitude and longitude come back as a parcel polygon."""

import urllib.parse

from fastapi.testclient import TestClient

from app.main import app
from app.routers import geodata as geodata_router
from app.services.geodata import GeodataError

client = TestClient(app)

LAT = 47.0245
LON = 28.8322
RING = [
    [28.83074928, 47.02528821],
    [28.8334, 47.02528821],
    [28.8334, 47.0238],
    [28.83074928, 47.0238],
    [28.83074928, 47.02528821],
]


def _feature(properties: dict, geometry: dict | None) -> dict:
    return {"type": "Feature", "properties": properties, "geometry": geometry}


def _collection(*features: dict) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


def install_wfs(responses: dict[str, dict | Exception]):
    def fetch(url: str) -> dict:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        cql = query["CQL_FILTER"][0]
        assert cql == f"INTERSECTS(geom,SRID=4326;POINT({LON:.8f} {LAT:.8f}))"
        layer = query["typeNames"][0]
        payload = responses[layer]
        if isinstance(payload, Exception):
            raise payload
        return payload

    app.dependency_overrides[geodata_router.wfs_fetch] = lambda: fetch
    return fetch


def teardown_function():
    app.dependency_overrides.clear()


def test_click_returns_the_parcel_polygon_and_its_fields():
    install_wfs(
        {
            "cadastru_data:terenuri": _collection(
                _feature(
                    {
                        "codcadastral": "01005200362",
                        "cod_parcel": " 0362",
                        "aria": "1.33 ha",
                        "landuse": "Amenajat",
                        "typeproperty": "PUBLICA",
                        "description": "drop me",
                    },
                    {"type": "Polygon", "coordinates": [RING]},
                )
            ),
            "cadastru_data:UAT1": _collection(_feature({"gfullname": "mun. Chișinău", "aria": "12296 ha"}, None)),
            "cadastru_data:UAT2": _collection(_feature({"gfullname": "mun. Chișinău", "aria": "57537 ha"}, None)),
        }
    )

    res = client.get("/geodata/parcel", params={"lat": LAT, "lon": LON})

    assert res.status_code == 200, res.text
    assert res.json() == {
        "lat": LAT,
        "lon": LON,
        "parcel": {
            "cadastralCode": "01005200362",
            "parcelCode": "0362",
            "area": "1.33 ha",
            "landUse": "Amenajat",
            "propertyType": "PUBLICA",
            "locality": "mun. Chișinău",
            "district": "mun. Chișinău",
            "geometry": {"type": "Polygon", "coordinates": [RING]},
        },
    }


def test_click_outside_any_parcel_returns_no_polygon():
    install_wfs(
        {
            "cadastru_data:terenuri": _collection(),
            "cadastru_data:UAT1": _collection(),
            "cadastru_data:UAT2": _collection(),
        }
    )

    res = client.get("/geodata/parcel", params={"lat": LAT, "lon": LON})

    assert res.status_code == 200, res.text
    assert res.json()["parcel"] is None


def test_parcel_is_returned_when_the_locality_service_fails():
    install_wfs(
        {
            "cadastru_data:terenuri": _collection(
                _feature(
                    {"codcadastral": "01005200362", "aria": "1.33 ha"},
                    {"type": "MultiPolygon", "coordinates": [[RING]]},
                )
            ),
            "cadastru_data:UAT1": GeodataError("timed out"),
            "cadastru_data:UAT2": GeodataError("timed out"),
        }
    )

    res = client.get("/geodata/parcel", params={"lat": LAT, "lon": LON})

    assert res.status_code == 200, res.text
    parcel = res.json()["parcel"]
    assert parcel["geometry"] == {"type": "MultiPolygon", "coordinates": [[RING]]}
    assert parcel["cadastralCode"] == "01005200362"
    assert parcel["locality"] is None
    assert parcel["district"] is None


def test_cadastral_service_failure_is_unavailable():
    install_wfs(
        {
            "cadastru_data:terenuri": GeodataError("down"),
            "cadastru_data:UAT1": _collection(),
            "cadastru_data:UAT2": _collection(),
        }
    )

    res = client.get("/geodata/parcel", params={"lat": LAT, "lon": LON})

    assert res.status_code == 502
    assert res.json()["detail"] == "Cadastral service is unavailable."


def test_coordinates_outside_wgs84_are_rejected():
    assert client.get("/geodata/parcel", params={"lat": 95, "lon": LON}).status_code == 422
    assert client.get("/geodata/parcel", params={"lat": LAT, "lon": 200}).status_code == 422
