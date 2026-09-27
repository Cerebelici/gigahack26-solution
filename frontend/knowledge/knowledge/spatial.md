# Spatial

Part of the [Sireț3 knowledge base](../KNOWLEDGE_BASE.md). Cite [sources](sources.md).

## Challenge tiles (the surface that is scored)

| Property | Value | Source |
|---|---|---|
| Count | 311 unique names | MEASURED [S-GEO] |
| File name | `siret3_r{row:03d}_c{col:03d}.tif` | [S-README] |
| Size | 2048 × 2048 px | [S-README] [S-GEO] |
| Ground sample distance | 0.025 m/px | [S-README] [S-GEO] |
| Ground size | 51.2 m × 51.2 m | [S-README] |
| CRS | EPSG:32635 | [S-README] [S-GEO] |
| Raster type | PixelIsArea. Tiepoint is the upper-left corner of pixel (0,0), not the centre. | MEASURED GeoKey 1025 = 1 [S-GEO] |
| Compression | JPEG-in-TIFF (compression 7), photometric YCbCr (6), subsampling 2×2, 8-bit, 3 bands, internal tiles 256×256 | MEASURED [S-GEO] |
| Nodata | Edge tiles include black outside the flight footprint. Do not annotate it. | [S-RULES] |

**Grid.** Rows increase south. Columns increase east. Tiles do not overlap. The study-area polygon area equals `311 × 51.2² = 815,267.84 m² = 81.527 ha`. [S-GEO]

Upper-left corner of tile `r`, `c` in EPSG:32635 metres (verified on five tiles, max error 0): [S-GEO]

```text
X_ul = 628992.0 + c * 51.2
Y_ul = 5221222.4 - r * 51.2
X_lr = X_ul + 51.2
Y_lr = Y_ul - 51.2
```

Pixel corner `(px, py)` to map metres (pixel-is-area, `py` downward):

```text
E = X_ul + px * 0.025
N = Y_ul - py * 0.025
```

Half a pixel is 1.25 cm. That is small next to the 0.4 m axis tolerance and the 2 m route tolerance. Whether Marcaj treats a CVAT point as a pixel corner or a pixel centre is not stated.

Row index runs 5–39 (35 distinct rows). Column index runs 0–33 (34 distinct columns). There is no `r000`–`r004` in the package; the indices sit on this virtual grid. [S-GEO]

Intentional holes inside the row/column bounding box (these tiles were not supplied): [S-GEO]

| Row | Missing columns |
|---|---|
| 25 | 20–30 |
| 26 | 23–28 |
| 27 | 28 |

Per-row column span (inclusive, after those holes): [S-GEO]

| Row | Cols | n | Row | Cols | n | Row | Cols | n |
|---|---|---:|---|---|---:|---|---|---:|
| 5 | 4–4 | 1 | 17 | 6–12 | 7 | 29 | 15–33 | 19 |
| 6 | 2–4 | 3 | 18 | 7–13 | 7 | 30 | 16–32 | 17 |
| 7 | 1–4 | 4 | 19 | 8–14 | 7 | 31 | 17–31 | 15 |
| 8 | 0–5 | 6 | 20 | 8–15 | 8 | 32 | 18–30 | 13 |
| 9 | 0–6 | 7 | 21 | 9–16 | 8 | 33 | 18–30 | 13 |
| 10 | 0–6 | 7 | 22 | 10–17 | 8 | 34 | 19–29 | 11 |
| 11 | 1–8 | 8 | 23 | 10–17 | 8 | 35 | 20–28 | 9 |
| 12 | 2–9 | 8 | 24 | 11–18 | 8 | 36 | 21–27 | 7 |
| 13 | 3–9 | 7 | 25 | 12–19 and 31–31 | 9 | 37 | 22–26 | 5 |
| 14 | 4–10 | 7 | 26 | 13–22 and 29–32 | 14 | 38 | 22–25 | 4 |
| 15 | 4–11 | 8 | 27 | 13–27 and 29–33 | 20 | 39 | 23–23 | 1 |
| 16 | 5–11 | 7 | 28 | 14–33 | 20 | | | |

ZIP membership (name order, uncompressed sizes are almost equal to the zip size because the TIFFs are already JPEG): [S-GEO]

| Part | Files | First | Last | Bytes |
|---|---:|---|---|---:|
| part1of5 | 74 | `siret3_r005_c004.tif` | `siret3_r017_c006.tif` | 93,823,066 |
| part2of5 | 71 | `siret3_r017_c007.tif` | `siret3_r026_c014.tif` | 93,624,576 |
| part3of5 | 78 | `siret3_r026_c015.tif` | `siret3_r030_c022.tif` | 93,207,449 |
| part4of5 | 76 | `siret3_r030_c023.tif` | `siret3_r036_c025.tif` | 94,108,721 |
| part5of5 | 12 | `siret3_r036_c026.tif` | `siret3_r039_c023.tif` | 10,414,422 |

Tile file size ranges from 0.15 MB to 1.66 MB (median 1.37 MB). Small files are edge tiles with a lot of black. [S-GEO]

Study-area bounding box, EPSG:32635: X 628,992.0 – 630,732.8 (1,740.8 m), Y 5,219,174.4 – 5,220,966.4 (1,792.0 m). The polygon has 145 vertices and no holes. [S-GEO]

## Start / finish

| Field | Value |
|---|---|
| Name | START |
| Role | Route start **and** finish |
| Description | Dirt-road junction at the north-west corner of the vineyard block |
| EPSG:32635 | X = 629,504.70 , Y = 5,220,250.75 |
| WGS84 | 47.1230335 N , 28.7073776 E |
| Tile | `siret3_r018_c010.tif` |
| Position in that tile | about 0.70 m / 28 px from the west edge, about 50.05 m / 2002 px from the north edge (near the south edge) |

[S-README] [S-GEO] from `start.geojson`.

That point lies inside the source orthomosaic footprint. [S-GEO]

## Passages and forbidden zones

Both files are a single `FeatureCollection` with one feature, CRS `urn:ogc:def:crs:EPSG::32635`, geometry `MultiPolygon`. [S-GEO]

| File | `properties.type` | `properties.source` | Parts | Area |
|---|---|---|---:|---|
| `passages.geojson` | `passage` | “OpenStreetMap highways, buffered; plus 5 passages digitised from the orthomosaic (`work/manual_passages.json`)” | 2 polygons, 13 holes | 40,000 m² (4.00 ha) |
| `forbidden.geojson` | `forbidden` | “village core outside the study area; OSM buildings (+1 m); commercial/religious compounds” | 19 polygons, no holes | 744,927 m² (74.49 ha), of which one part is 74.02 ha |

[S-GEO] [S-README]

The passage buffer width is not stated. Do not invent a centre-line from the area. The route may use these polygons plus passable inter-row areas. It may not cross canopies, fences, or forbidden polygons. More than 2% of route length outside the allowed surfaces scores 0 for the route criterion. [S-DESC] [S-RULES]

The overview and the passage preview show the same rotated flight: vineyards on the west and south, a dense village on the northeast, roads between them. The start marker sits on a track junction at the north-west corner of a vineyard block. Forbidden cover sits mainly on the village. Magenta corridors follow roads, tracks, and some headlands. Preview colors are not the Marcaj label colors. [S-PREVIEW] [S-README]

## Source orthomosaic (training only)

`04_source/siret3_source_orthomosaic_EPSG4326.tif`. [S-README]

| Property | Measured from the file [S-GEO] | Stated in the PDF [S-DESC] [S-README] |
|---|---|---|
| Container | BigTIFF, 658,583,344 bytes (~628 MiB; README says 659 MB) | 659 MB |
| CRS | EPSG:4326 (geographic). GeoKey 1024 = 2. | EPSG:4326 |
| Size | 70,246 × 81,986 px | not stated |
| Pixel scale | 3.16481e-7 ° lon × 2.16017e-7 ° lat ≈ **0.0240 m** on both axes at the mosaic centre | **3.52 cm/px** |
| Upper left | lon 28.7009351352 , lat 47.1312466746 | not stated |
| Lower right | lon 28.7231666595 , lat 47.1135363048 | not stated |
| Footprint box | about 1,687 m × 1,969 m ≈ 332 ha | not stated |
| Valid pixels | GDAL `STATISTICS_VALID_PERCENT` = 43.59% (per band) | not stated |
| Implied valid area at 2.40 cm | about **145 ha** | “~145 ha” |
| Capture | not in the TIFF tags that were read | 20 May 2025, UAV, RGB, unannotated |
| Provider | not in the TIFF | 3DATA COLLECT, via OpenAerialMap |
| Compression | JPEG-in-TIFF, YCbCr, 2×2 subsampling, internal tiles 512×512, 8-bit RGB | RGB |

Use the **tile** geotransform (2.5 cm, EPSG:32635) for anything that is scored. The source file is for training on the whole survey. The PDF’s 3.52 cm/px does not reproduce the ~145 ha figure; the measured 2.40 cm GSD does. See [Conflicts](conflicts.md).

GDAL metadata on the source also says `UNITTYPE` = metre on the byte samples. That is a sample-unit tag, not the CRS. Coordinates in this file are degrees. [S-GEO]

A public OpenAerialMap item URL was **not** found while writing this file. The package says the mosaic is the one published on OpenAerialMap. [S-README]

Related: [Data](data.md) · [Route](route.md) · [Conflicts](conflicts.md) · [Annotation](annotation.md)
