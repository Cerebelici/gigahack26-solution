# Knowledge base — Vineyard AI Field Challenge (Sireț3)

<!--
KB-RETRIEVAL
challenge: Vineyard AI Field Challenge · Deeptech GigaHack 2026 · provider Marcaj · dataset Sireț3 / Siret3
event: 25–27 September 2026 · Tekwill, Chișinău · online and offline
deadline: 2026-09-27 15:00 Europe/Chisinau (EEST, UTC+3) · repo AND Marcaj
prize: MDL 30,000 · 1 team
crs: EPSG:32635 (WGS 84 / UTM 35N, metres) for every submission geometry
tiles: 311 GeoTIFF · 2048×2048 · 0.025 m/px · 51.2 m · JPEG-in-TIFF YCbCr · names siret3_rNNN_cNNN.tif
labels: vineyard=polygon canopy · waste=axis-aligned box · row=polyline · interrow_area=polygon
attributes: vineyard_id · row_id · row_structure=regular|disrupted|unassessable · interrow_cover=bare_soil|vegetation|mixed|unassessable
start: EPSG:32635 (629504.70, 5220250.75) · 47.1230335 N, 28.7073776 E · tile siret3_r018_c010.tif
submission_root: route.geojson · measurements.csv · README.md · code · weights · web UI link
marcaj: upload all 311 BEFORE publish · 63 jobs · only submitted jobs are scored
plan: Friday night pre-annotate · route and web in parallel on the examples · publish by Saturday ~14:00 · Sunday 15:00 freeze
scoring: 85% automatic + 15% engineering · hidden tile subset · annotate every tile
licence: imagery CC BY 4.0 (3DATA COLLECT / OpenAerialMap) · passages/forbidden include OSM ODbL
cadastru: public parcel polygons (FNDG/RBI) · not a scored label · start point has no parcel · see cadastru.md
status: waste model chosen (YOLO26n, waste/best.pt, confidence ≥ 0.90) · other pieces open · weekend sequence in plan.md · updated 2026-09-26
local_assets: assets/ in this repo (orthomosaic via Git LFS)
index: this file routes; facts live in the other files in this folder
-->

**Status:** waste detector chosen (`waste/best.pt`, confidence at least 0.90). No route or web stack chosen.
**Updated:** 2026-09-26.

This folder is the knowledge base. Each other file is one topic and the only place for that topic. Facts are tagged with a source id from [Sources](sources.md). `MEASURED` means computed from the local files on 2026-09-25, not copied from a PDF. Decisions go in [Solution](solution.md). Experiments go in [Research](research.md). Do not treat those two files as challenge rules.

The participant package is in `assets/` at the repository root. The source orthomosaic is stored with Git LFS.

## Retrieval index

| If you need… | File |
|---|---|
| One-paragraph brief, deadline, prize, what “done” means | [Challenge](challenge.md) |
| Weekend clock: who does what, and by when | [Plan](plan.md) |
| Exact files the jury expects in the repo | [Submission](submission.md) |
| Score weights and match rules | [Scoring](scoring.md) |
| Label names, attributes, drawing rules | [Annotation](annotation.md) |
| Marcaj upload / publish / submit sequence | [Marcaj](marcaj.md) |
| Tile names, CRS, geotransform, grid formula | [Spatial](spatial.md) |
| What each asset folder contains | [Data](data.md) |
| The two worked example tiles | [Examples](examples.md) |
| PDF vs file disagreements, upload-size trap, visual-guide traps | [Conflicts](conflicts.md) |
| What the organizer slide deck adds, and what to ignore | [Visual guide](visual-guide.md) |
| Inspection targets and the walking route | [Route](route.md) |
| Cadastral parcel at a point, and how it can sit on the map | [Cadastru](cadastru.md) |
| Where a number came from | [Sources](sources.md) |
| What we decided, and what we have not | [Solution](solution.md) |
| Experiments still to run | [Research](research.md) |
| Which trainer to use on ICAERUS | [Training stack](training-stack.md) |
| How to adapt ICAERUS and Riseholme masks | [Mask adaptation](mask-adaptation.md) |
| Terms | [Glossary](glossary.md) |

## How to extend

1. New fact from an organizer: add a source row in [Sources](sources.md), then update the matching topic file. Update the retrieval comment at the top of this file if a keyword changes.
2. New measurement: tag it `MEASURED` in the topic file it belongs to, name the file, and date it.
3. New team decision: only [Solution](solution.md) and its decision log.
4. New experiment: only [Research](research.md) and its findings log.
5. Imagery and route files live in `assets/`. Do not recompress or rename the challenge tiles. Redistribution keeps the CC BY 4.0 and ODbL credits in the repository README.
