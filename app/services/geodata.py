"""Point-in-parcel lookup against the public Moldova cadastral WFS.

The FNDG copy on geodata.gov.md answers a WGS84 point with the land parcel under it.
A CQL point is longitude then latitude. GeoJSON rings come back the same way.
"""

import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request

import certifi
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

logger = logging.getLogger(__name__)
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

WFS_URL = "https://geodata.gov.md/geoserver/cadastru_data/wfs"
USER_AGENT = "geobelic-backend/1.0"
TIMEOUT_SECONDS = 20

# Geometry is requested with the parcel attributes. Locality layers only need a name.
LAYERS = {
    "terenuri": "codcadastral,cod_parcel,aria,landuse,typeproperty,geom",
    "UAT1": "gfullname",
    "UAT2": "gfullname",
}


class GeodataError(Exception):
    """The cadastral service did not return a usable answer."""


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS, context=SSL_CONTEXT) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise GeodataError("Cadastral service is unavailable.") from exc
    if not isinstance(payload, dict):
        raise GeodataError("Cadastral service is unavailable.")
    return payload


def lookup_parcel(lat: float, lon: float, *, fetch: Callable[[str], dict] = fetch_json) -> dict:
    """Parcel under a WGS84 point, or `parcel: None` when the point hits no land parcel."""
    with ThreadPoolExecutor(max_workers=len(LAYERS)) as pool:
        futures = {layer: pool.submit(fetch, _url(layer, lat, lon)) for layer in LAYERS}
        try:
            parcels = futures["terenuri"].result()
        except GeodataError:
            raise
        except Exception as exc:
            raise GeodataError("Cadastral service is unavailable.") from exc
        locality = _place_name(_outcome(futures["UAT1"]))
        district = _place_name(_outcome(futures["UAT2"]))
    return {"lat": lat, "lon": lon, "parcel": _parcel(parcels, locality, district)}


def _url(layer: str, lat: float, lon: float) -> str:
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": f"cadastru_data:{layer}",
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "count": 5,
        "propertyName": LAYERS[layer],
        # CQL points are longitude latitude, unlike a WMS 1.3.0 bbox.
        "CQL_FILTER": f"INTERSECTS(geom,SRID=4326;POINT({lon:.8f} {lat:.8f}))",
    }
    return f"{WFS_URL}?{urllib.parse.urlencode(params)}"


def _outcome(future: Future[dict]) -> dict | None:
    try:
        return future.result()
    except GeodataError as exc:
        logger.warning("Cadastral locality lookup failed: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Cadastral locality lookup failed: %s", exc)
        return None


def _place_name(payload: dict | None) -> str | None:
    if not payload:
        return None
    features = payload.get("features") or []
    if not features:
        return None
    return _text((features[0].get("properties") or {}).get("gfullname"))


def _parcel(payload: dict, locality: str | None, district: str | None) -> dict | None:
    for feature in payload.get("features") or []:
        geometry = _geometry(feature.get("geometry"))
        if geometry is None:
            continue
        props = feature.get("properties") or {}
        return {
            "cadastralCode": _text(props.get("codcadastral")),
            "parcelCode": _text(props.get("cod_parcel")),
            "area": _text(props.get("aria")),
            "landUse": _text(props.get("landuse")),
            "propertyType": _text(props.get("typeproperty")),
            "locality": locality,
            "district": district,
            "geometry": geometry,
        }
    return None


def _geometry(geometry: object) -> dict | None:
    if not isinstance(geometry, dict):
        return None
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind not in ("Polygon", "MultiPolygon") or not isinstance(coordinates, list) or not coordinates:
        return None
    return {"type": kind, "coordinates": coordinates}


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
