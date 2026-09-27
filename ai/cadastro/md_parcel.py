#!/usr/bin/env python3
"""Look up a Moldovan cadastral parcel at a WGS84 lat/lon, including the polygon.

Uses the public GeoServer endpoints behind https://geodata.gov.md (map 99). stdlib only.
Usage: python3 md_parcel.py 47.0245 28.8322

Polygon rings are closed: the last point repeats the first.
Coordinates are [x, y]:
  wgs84      EPSG:4326   longitude, latitude
  utm35n     EPSG:32635  easting, northing in metres
  moldref99  EPSG:4026   easting, northing in metres (native cadastral CRS)
"""
import json, sys, urllib.parse, urllib.request

UA = {"User-Agent": "md-parcel-lookup/1.0"}
WFS = "https://geodata.gov.md/geoserver/cadastru_data/wfs"

def _get(url, params):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def _rings(geom):
    if not geom:
        return []
    kind, coords = geom.get("type"), geom.get("coordinates") or []
    if kind == "Polygon":
        return coords
    if kind == "MultiPolygon":
        return [ring for poly in coords for ring in poly]
    return []

def _props(feature):
    props = dict(feature.get("properties") or {})
    props.pop("description", None)
    return props

def wfs_hits(layer, lat, lon, srs="EPSG:4326"):
    """FNDG copy on geodata.gov.md. WFS 2.0 point-in-polygon, with geometry."""
    data = _get(WFS, {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": f"cadastru_data:{layer}", "outputFormat": "application/json",
        "srsName": srs, "count": 5,
        "CQL_FILTER": f"INTERSECTS(geom,SRID=4326;POINT({lon} {lat}))"})
    return data.get("features") or []

def wfs_props(layer, lat, lon):
    return [_props(f) for f in wfs_hits(layer, lat, lon)]

def wms_info(base, layer, lat, lon, pad=0.0002):
    """Live RBI on map.cadastru.md. WMS 1.3.0 GetFeatureInfo. EPSG:4326 bbox is lat,lon."""
    data = _get(base, {
        "service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo",
        "layers": layer, "query_layers": layer, "crs": "EPSG:4326",
        "bbox": f"{lat-pad},{lon-pad},{lat+pad},{lon+pad}", "width": 101, "height": 101,
        "i": 50, "j": 50, "info_format": "application/json", "feature_count": 5})
    return [_props(f) for f in data.get("features") or []]

def parcel_polygons(lat, lon):
    """One entry per parcel under the point. Rings come from FNDG (full precision)."""
    by_srs = {
        "wgs84": wfs_hits("terenuri", lat, lon, "EPSG:4326"),
        "utm35n": wfs_hits("terenuri", lat, lon, "EPSG:32635"),
        "moldref99": wfs_hits("terenuri", lat, lon, "EPSG:4026"),
    }
    out = []
    for i, feature in enumerate(by_srs["wgs84"]):
        item = _props(feature)
        item["polygon"] = {
            "closed": True,
            "wgs84": {"crs": "EPSG:4326", "axis": ["lon", "lat"], "rings": _rings(feature.get("geometry"))},
            "utm35n": {"crs": "EPSG:32635", "axis": ["easting_m", "northing_m"],
                       "rings": _rings(by_srs["utm35n"][i].get("geometry")) if i < len(by_srs["utm35n"]) else []},
            "moldref99": {"crs": "EPSG:4026", "axis": ["easting_m", "northing_m"],
                          "rings": _rings(by_srs["moldref99"][i].get("geometry")) if i < len(by_srs["moldref99"]) else []},
        }
        out.append(item)
    return out

def lookup(lat, lon):
    out = {"lat": lat, "lon": lon}
    out["parcel_fndg"] = parcel_polygons(lat, lon)
    out["building_fndg"] = wfs_props("cladiri", lat, lon)
    out["cadastral_sector"] = wfs_props("sector_cadastral", lat, lon)
    out["locality_uat1"] = wfs_props("UAT1", lat, lon)
    out["district_uat2"] = wfs_props("UAT2", lat, lon)
    try:
        out["parcel_rbi"] = wms_info("https://map.cadastru.md/geoserver/w_cbi/wms", "cad_terenuri", lat, lon)
        out["uat_rbi"] = wms_info("https://map.cadastru.md/geoserver/w_rsuat/wms", "mv_uat3", lat, lon)
    except Exception as e:
        out["rbi_error"] = str(e)
    return out

if __name__ == "__main__":
    lat, lon = float(sys.argv[1]), float(sys.argv[2])
    print(json.dumps(lookup(lat, lon), ensure_ascii=False, indent=2))
