# Cadastru

Part of the [Sireț3 knowledge base](README.md). Cite [sources](sources.md).

Public Moldovan cadastral parcels, queried 2026-09-26. This is **not** a Marcaj label and **not** a scored geometry. The script and the request notes live in `cadastro/`. [S-CAD]

## What a point returns

A WGS84 point inside a parcel polygon returns that whole **teren**: one registered land unit, identified by its cadastral number. The teren is a part of a cadastral sector. The number is unique. The point does not split the parcel into smaller pieces. Buildings are a separate layer. [S-CAD] [S-SICBI]

Two public copies:

| Copy | Endpoint | What to use it for |
|---|---|---|
| FNDG, quarterly, “Date actuale la: 01.01.2026” | `https://geodata.gov.md/geoserver/cadastru_data/wfs` layer `terenuri` | Exact point-in-polygon and the polygon rings |
| RBI, live register | `https://map.cadastru.md/geoserver/w_cbi/wms` layer `cad_terenuri` | Richer attributes. WFS on this host returns 403. GetFeatureInfo geometry is rounded to 4 decimals (~10 m). Draw from FNDG rings. |

`cadastro/md_parcel.py LAT LON` prints both. Rings are closed (last point repeats the first), in three CRS: EPSG:4326 as `[lon, lat]`, EPSG:32635 metres, EPSG:4026 (MOLDREF99) metres. Scored challenge geometries stay EPSG:32635. [S-CAD] [S-DESC]

A hit includes cadastral number, parcel id, official area, land use, and property type (public / private / undetermined). It does not include the owner’s name. Owner extracts are a paid ASP service. [S-CAD]

A point on a shared boundary can match more than one teren. A point in a gap (road, track, unregistered strip) matches none. The left bank can return a sector code and no parcel. [S-CAD]

## Samples on and off the site

Study-area footprint, for scale: lon 28.700935–28.723167, lat 47.113536–47.131247. [S-GEO]

| Point | Parcel | Official area | Use / property | Outline | Place |
|---|---|---|---|---|---|
| 47.123, 28.701 | `80371130109` | 0.70 ha (RBI 0.6999 ha) | Agricultural production, public. Massiv 1, sector 13, parcel 109. Sector code `8037113`. | 5 corners, one ring | sat. Sireți, r-nul Strășeni. Inside the mosaic footprint. |
| 47.122, 28.709 | `80371140487` | 0.37 ha (RBI 0.3723 ha; shoelace 3722 m²) | Agricultural, destination Agricol, property undetermined. Massiv 1, sector 14, parcel 487. Sector code `8037114`. | 33 corners, one ring, no holes | Same village. Inside the mosaic footprint. |
| Start 47.1230335, 28.7073776 | none | — | — | — | Same village, sector `8037114`, no teren and no building. The start sits in a gap. |

The 0.37 ha parcel is a jagged strip, not a block rectangle. Long sides run about 142° from north (northwest–southeast), 100–154 m. The other axis is about 72°, with steps of 40–55 m and teeth of 6–18 m. Its bounding box is 250 m × 258 m. [S-CAD]

Chișinău `47.0245, 28.8322` → `01005200362` was only a method check. It is outside Sireț3. [S-CAD]

## Where it can attach

The jury does not score cadastral numbers. Use the layer as product context. [S-DESC]

| Attach it to | How | Why this shape |
|---|---|---|
| Web map | One cached GeoJSON of `terenuri` over the study footprint, drawn under the tiles. A click reports number, official hectares, land use, village. | The pitch shows a map a vineyard operator can read. Parcel identity is the legal unit; canopy polygons are not. |
| `measurements.csv` | Extra columns: cadastral number, official area, and our canopy / inter-row / row totals **inside** that polygon. | Scored areas stay the annotation unions, with the 15% tolerance. Official hectares are the registered holding, not the canopy area. |
| Empty clicks and the start | Keep a “no parcel” result. | The start point is in sector `8037114` and in no teren. Tracks between parcels are exactly where a route begins. |

Do not use a cadastral polygon as a `vineyard_id` block. Blocks split on roads and on ≥ 5 m of non-vineyard ground, and the ID string does not have to match a reference. One teren can hold several blocks; the 33-corner strip is one legal parcel. [S-RULES] [S-DESC]

Do not walk the route along parcel boundaries. The route is inter-row plus `passages.geojson`. More than 2% off that network scores 0. [S-DESC]

Fetch the study-area parcels **once** (WFS bbox) and intersect in EPSG:32635. A live call per vine will not finish 311 tiles. Reuse of the WFS data has no verified licence; cache the extract and cite AGCC / geodata.gov.md. [S-CAD]

Related: [Spatial](spatial.md) · [Solution](solution.md) · [Research](research.md) · [Scoring](scoring.md)
