# Moldova Cadastral Data via API: Point-to-Parcel/Territory Lookup

_Researched and tested on 26 Sep 2026 (Europe/Chisinau)._

## Summary

The viewer at <https://geodata.gov.md/_v/2026092611/#/viewer/openlayers/99> is a MapStore2 app. It loads its layers from open GeoServer instances, which speak standard OGC protocols (WMS, WFS, WMTS). You can query those services directly over HTTP to find which cadastral parcel, building, cadastral sector, and administrative territory lies at a given latitude/longitude.

- You don't need a hosted browser service for this.
- There's no API key and no sign-up.
- CORS is open (`Access-Control-Allow-Origin: *` on geodata.gov.md), so browser apps can call it directly.
- Typical response time is 0.5–1 s per request.

## Where the configuration comes from

| What | URL |
|---|---|
| Viewer | https://geodata.gov.md/_v/2026092611/#/viewer/openlayers/99 |
| App config | https://geodata.gov.md/configs/localConfig.json |
| Map 99 config (layers and sources) | https://geodata.gov.md/rest/geostore/data/99 |

## Data sources

### 1. FNDG copy, updated quarterly (recommended for API use)

The parcel popup says "Date actuale la: 01.01.2026" (data current as of 1 Jan 2026).

- WMS: `https://geodata.gov.md/geoserver/cadastru_data/wms`
- WFS: `https://geodata.gov.md/geoserver/cadastru_data/wfs`
- Both WMS and WFS 2.0 work, with GeoJSON output (`outputFormat=application/json`) and CQL filters.

| Layer | Content | Key fields |
|---|---|---|
| `cadastru_data:terenuri` | Land parcels | `codcadastral`, `cod_parcel`, `aria`, `landuse`, `typeproperty` |
| `cadastru_data:cladiri` | Buildings | |
| `cadastru_data:sector_cadastral` | Cadastral sectors | `codcadastral` |
| `cadastru_data:UAT1` | Localities (city/town/commune/village) | `gfullname`, `aria` |
| `cadastru_data:UAT2` | Districts / municipalities | `gfullname`, `aria` |
| `cadastru_data:UAT1_intravelan` | Built-up areas of localities | |
| `cadastru_data:adresa_point` | Address points | |
| `cadastru_data:Strazi_RM` | Streets | |

### 2. RBI, the live Real Estate Cadastral Register

- Parcels and buildings: `https://map.cadastru.md/geoserver/w_cbi/wms` (layers `cad_terenuri`, `cad_cladiri`)
- Administrative units: `https://map.cadastru.md/geoserver/w_rsuat/wms` (layers `mv_uat3`, `mv_uat1`, `mv_localitate`, address points)
- WMS GetFeatureInfo works. **WFS returns 403 Forbidden.**
- It has more fields than FNDG: `codcadastral`, `parcelid`, `suprafata` (ha), `usename`, `domeniul_name`, `codtip`, `cadzone`, sector/massiv numbers, a bounding box in local coordinates (`gxmin/gxmax/...`), and a centroid.
- Admin unit fields: `gfullname`, `loc_type_ename`, `cuatm`, `uat1_name`, `area`.

### 3. Base maps (tiles only)

- `https://maps2.ingeocad.md/geoserver/gwc/service/wmts` has orthophotos (2016–2021), relief, and the 1:50k topographic map.

## Coordinate systems

- The native CRS is **EPSG:4026** (MOLDREF99 / Moldova TM).
- Both servers accept and return **EPSG:4326** (WGS84 lat/lon).
- **Axis-order catch:**
  - A CQL `POINT(...)` takes **lon lat**.
  - A WMS 1.3.0 `bbox` with `crs=EPSG:4326` takes **lat,lon** (`minLat,minLon,maxLat,maxLon`).

## Example requests

### A. Parcel at a point (FNDG, WFS + CQL)

```bash
LAT=47.0245; LON=28.8322
curl -sG "https://geodata.gov.md/geoserver/cadastru_data/wfs" \
  --data-urlencode "service=WFS" --data-urlencode "version=2.0.0" --data-urlencode "request=GetFeature" \
  --data-urlencode "typeNames=cadastru_data:terenuri" --data-urlencode "outputFormat=application/json" \
  --data-urlencode "propertyName=codcadastral,cod_parcel,aria,landuse,typeproperty" \
  --data-urlencode "CQL_FILTER=INTERSECTS(geom,SRID=4326;POINT($LON $LAT))"
```

Swap `typeNames` for `cadastru_data:UAT1`, `cadastru_data:UAT2`, `cadastru_data:sector_cadastral`, or `cadastru_data:cladiri` to get the territory, sector, or building at the same point.

### B. Parcel at a point (RBI live, WMS GetFeatureInfo)

```bash
LAT=47.0245; LON=28.8322; D=0.0002
curl -sG "https://map.cadastru.md/geoserver/w_cbi/wms" \
  --data-urlencode "service=WMS" --data-urlencode "version=1.3.0" --data-urlencode "request=GetFeatureInfo" \
  --data-urlencode "layers=cad_terenuri" --data-urlencode "query_layers=cad_terenuri" \
  --data-urlencode "crs=EPSG:4326" \
  --data-urlencode "bbox=$(awk -v a=$LAT -v o=$LON -v d=$D 'BEGIN{printf "%.6f,%.6f,%.6f,%.6f",a-d,o-d,a+d,o+d}')" \
  --data-urlencode "width=101" --data-urlencode "height=101" --data-urlencode "i=50" --data-urlencode "j=50" \
  --data-urlencode "info_format=application/json"
```

For administrative units, use `https://map.cadastru.md/geoserver/w_rsuat/wms` with the layer `mv_uat3`.

### C. Python script

`md_parcel.py` uses only the standard library. Run it like this:

```bash
python3 md_parcel.py 47.0245 28.8322
```

It returns JSON with `parcel_fndg`, `building_fndg`, `cadastral_sector`, `locality_uat1`, `district_uat2`, `parcel_rbi`, and `uat_rbi`.

## Test results

| Point | Result |
|---|---|
| Central Chișinău (47.0245, 28.8322) | Parcel `01005200362`, 1.33 ha (RBI: 1.3278 ha), Amenajat, public. Sector `0100520`. UAT1 "mun. Chișinău" (12296 ha), UAT2 "mun. Chișinău" (57537 ha). RBI admin unit: Municipality, CUATM `0100`. No building. |
| Bălți (47.7619, 27.9290) | Parcel `03003040764`, "Cale de comunicaţie", public, 1.47 ha |
| Stăuceni (47.0930, 28.8710) | Parcel `31532161247`, 8.12 ha, use and ownership "NEDETERMINAT". Locality "mun. Chișinău, or. Stăuceni" |
| Tiraspol (Transnistria) | No parcel and no admin unit, only a cadastral sector code. Expect this across the whole left bank. |

## Terms, access, and limits

- Both servers' GetCapabilities list Fees and AccessConstraints as "none".
- geodata.gov.md belongs to the Agenția Geodezie, Cartografie și Cadastru (AGCC). ÎS INGEOCAD runs it technically. Its "About" page describes open access through network services, with restricted data protected by law. The "Acord-tip" agreement there covers publishing data, not using it.
- **Not verified:** I found no formal reuse licence for the WMS/WFS data.
- I found no documented rate limits. WFS returns up to 50,000 features by default and supports paging. Cache results and keep request rates modest.
- **No personal data comes back.** You get property type (public/private/undetermined) but no owner names.
- Owner data, extracts, and cadastral plans are **paid services** through servicii.gov.md / EVO. They need an electronic signature and are paid via MPay. e-Cadastru offers free lookups by cadastral number or address, for information only.

## Fallback: hosted browser services (not needed here)

These are only for sites that expose data through a UI alone. Prices were checked on 26 Sep 2026.

| Service | How you connect | Free tier | Paid |
|---|---|---|---|
| Cloudflare Browser Run (formerly Browser Rendering) | REST Quick Actions (`/screenshot`, `/content`, `/markdown`) or a Workers binding | 10 browser-min/day | Workers paid plan includes 10 h/month, then $0.09/h (limits page not verified) |
| Browserbase (plus Stagehand) | Playwright/Puppeteer over CDP (`connectOverCDP(session.connectUrl)`) | 1 browser-hour, 3 concurrent | Developer $20/mo |
| Browserless | CDP and REST | 1k units | from $25/mo (yearly billing) |
| Steel.dev | CDP | $30 one-time credit | $0.10/h |
| Hyperbrowser | CDP | | $0.10/h |
| Anchor Browser | CDP | 5 credits | $50/mo |
| Browser Use cloud | Agent API | | $0.02/h browser; agents at model cost + 20% |

## Sources

- FNDG WFS capabilities: https://geodata.gov.md/geoserver/cadastru_data/wfs?service=WFS&version=2.0.0&request=GetCapabilities
- FNDG WMS capabilities: https://geodata.gov.md/geoserver/cadastru_data/wms?service=WMS&version=1.3.0&request=GetCapabilities
- RBI WMS capabilities: https://map.cadastru.md/geoserver/w_cbi/wms?service=WMS&version=1.3.0&request=GetCapabilities
- About geodata.gov.md: https://geodata.gov.md/additives/DespreGeodata_4.html
- e-Cadastru guide: https://www.ipcbi.gov.md/sites/default/files/media/documents/2025-08/accesarea_informatiilor_publice_despre_bunul_imobil.pdf
- Paid cadastral services (ASP): https://www.asp.gov.md/ro/media/2023-04-28
- Cloudflare REST API: https://developers.cloudflare.com/browser-rendering/rest-api/
- Cloudflare pricing: https://developers.cloudflare.com/browser-rendering/pricing/
- Browserbase Playwright: https://docs.browserbase.com/introduction/playwright
- Browserbase pricing: https://www.browserbase.com/pricing
- Browserless pricing: https://www.browserless.io/pricing
- Steel pricing: https://docs.steel.dev/overview/pricinglimits
- Hyperbrowser pricing: https://hyperbrowser.ai/docs/pricing.md
- Anchor: https://anchorbrowser.io
- Browser Use pricing: https://browser-use.com/pricing
