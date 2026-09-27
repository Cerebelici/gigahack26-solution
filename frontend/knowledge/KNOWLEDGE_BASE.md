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
scoring: 85% automatic + 15% engineering · hidden tile subset · annotate every tile
licence: imagery CC BY 4.0 (3DATA COLLECT / OpenAerialMap) · passages/forbidden include OSM ODbL
status: context only · no solution chosen · updated 2026-09-25
local_assets: /Users/chirill/Downloads/assets_for_participants  (NOT in this git repo)
index: this file routes; facts live in knowledge/*.md
-->

**Status:** context capture only. No model, route, or architecture has been chosen.
**Updated:** 2026-09-25.

This file is the index. Each subdomain below is one file and the only place for that topic. Facts are tagged with a source id from [Sources](knowledge/sources.md). `MEASURED` means computed from the local files on 2026-09-25, not copied from a PDF. Decisions go in [Solution](knowledge/solution.md). Experiments go in [Research](knowledge/research.md). Do not treat those two files as challenge rules.

## Retrieval index

| If you need… | File |
|---|---|
| One-paragraph brief, deadline, prize, what “done” means | [Challenge](knowledge/challenge.md) |
| Exact files the jury expects in the repo | [Submission](knowledge/submission.md) |
| Score weights and match rules | [Scoring](knowledge/scoring.md) |
| Label names, attributes, drawing rules | [Annotation](knowledge/annotation.md) |
| Marcaj upload / publish / submit sequence | [Marcaj](knowledge/marcaj.md) |
| Tile names, CRS, geotransform, grid formula | [Spatial](knowledge/spatial.md) |
| What each asset folder contains | [Data](knowledge/data.md) |
| The two worked example tiles | [Examples](knowledge/examples.md) |
| PDF vs file disagreements, upload-size trap | [Conflicts](knowledge/conflicts.md) |
| Inspection targets and the walking route | [Route](knowledge/route.md) |
| Where a number came from | [Sources](knowledge/sources.md) |
| What we decided, and what we have not | [Solution](knowledge/solution.md) |
| Experiments still to run | [Research](knowledge/research.md) |
| Terms | [Glossary](knowledge/glossary.md) |
| Short working summary, formulas, and checklist | [MEMORY](MEMORY.md) |

## How to extend

1. New fact from an organizer: add a source row in [Sources](knowledge/sources.md), then update the matching subdomain. Update the retrieval comment at the top of this file if a keyword changes.
2. New measurement: tag it `MEASURED` in the subdomain it belongs to, name the file, and date it.
3. New team decision: only [Solution](knowledge/solution.md) and its decision log.
4. New experiment: only [Research](knowledge/research.md) and its findings log.
5. Do not copy the orthomosaic or the tile ZIPs into git. They are large, and the imagery licence requires attribution wherever they are redistributed.
