# Submission

Part of the [Sireț3 knowledge base](../KNOWLEDGE_BASE.md). Cite [sources](sources.md).

One repository link. The **repository root** must contain: [S-DESC]

| Path | Contract |
|---|---|
| `route.geojson` | One `LineString` in EPSG:32635. Starts and ends at the supplied start point (5 m tolerance). Property `length_m`. |
| `measurements.csv` | Block and row counts, row lengths, and areas by `vineyard_id` / `row_id`. Shown to the jury. Numeric scores for counts and areas are computed from the Marcaj export, the same way for every team, not from this CSV. **Column schema is not specified.** |
| `README.md` | Install and run from the supplied tiles to `route.geojson` and `measurements.csv`. Pinned dependencies (Dockerfile is a plus). Where to get model weights. Processing time for the full 311-tile set and the hardware it was measured on. Any paid APIs or LLMs used. Link to the working web interface. |
| application and processing code | Reproduce the result. |
| model weights | In the repo or by link. No size limit. Compute is not provided. |

Also required in the product, not necessarily as a single file: a web UI that shows route polylines and their lengths, `vineyard_id` / `row_id`, canopy and inter-row areas, block and row counts, and individual and total row lengths. [S-DESC]

Geometries, the route, and measurement tables are EPSG:32635. GeoJSON coordinates are in that system (metres), not longitude/latitude. Areas in m² and hectares. Lengths in metres. Measurements are horizontal, with no terrain correction. [S-DESC]

Annotations themselves are taken from the team’s Marcaj project. Teams do not upload an annotation export for scoring. Export from Marcaj (for example `json_simple` or CVAT XML) is for the team’s own measurements and UI. [S-MARCAJ]

Suggested interchange: GeoJSON and CSV/JSON; **CVAT for images 1.1** for Marcaj import. Any implementation stack is allowed. [S-DESC]

Related: [Challenge](challenge.md) · [Scoring](scoring.md) · [Spatial](spatial.md) · [Route](route.md)
