# Data

Part of the [Sireț3 knowledge base](README.md). Cite [sources](sources.md).

Committed copy of the participant package: `assets/` at the repository root. The source orthomosaic is Git LFS. The same drop was first read from `/Users/chirill/Downloads/assets_for_participants`. [S-README]

| Folder | File | Role |
|---|---|---|
| `01_tiles/` | `siret3_challenge_tiles_part1of5.zip` … `part5of5.zip` | The 311 challenge tiles. |
| `01_tiles/` | `overview.png` | ~1 m/px overview. Challenge tiles outlined, route START marked. |
| `02_route/` | `start.geojson` | Start and finish point. |
| `02_route/` | `passages.geojson` | Authorised passages. `type=passage`. |
| `02_route/` | `forbidden.geojson` | Forbidden zones. `type=forbidden`. |
| `02_route/` | `study_area.geojson` | Outline of the 311 tiles. Property `name` = “study area, 311 tiles”. |
| `02_route/` | `preview_passages_forbidden.png` | Preview of passages and forbidden zones. |
| `03_docs/` | `Vineyard_AI_Field_Challenge_description.pdf` | Tasks, submission, rules, scoring. 5 pages. |
| `03_docs/` | `Vineyard_AI_annotation_rules.pdf` | Labels, attributes, cases. v1.0, 8 pages. |
| `03_docs/` | `Marcaj_quick_start_for_teams.pdf` | Sign-in through submit. v1.0, 6 pages. |
| `03_docs/` | `Marcaj_Vineyard_AI_Visual_Journey.pdf` | Illustrative 9-page workflow. Not a rule. [S-VISUAL] |
| `04_source/` | `siret3_source_orthomosaic_EPSG4326.tif` | Full original mosaic. Training only. |
| `05_examples/` | `siret3_examples_cvat.zip` | Two annotated tiles in the upload format. **Not scored.** |
| `05_examples/` | `preview_siret3_r021_c012.jpg`, `preview_siret3_r006_c004.jpg` | Preview renders of those annotations. |
| package root | `README.md` | Index of the package. |

## Not in the package

No trained weights. No labelled Sireț3 set beyond the two unscored examples. No waste example. No `measurements.csv` template. No sample `route.geojson`. No Marcaj credentials. No formal CSV column list. No inspection-target layer (that list is hidden and used only for scoring). No stated passage buffer width.

## Rules that constrain training data

Allowed: any open pretrained model (the brief names SAM and YOLO as examples), open datasets whose licences were checked, libraries, classical vision. Paid APIs and LLMs are allowed if the result stays reproducible and the README lists them. [S-DESC]

Manual annotation of **Sireț3** happens only in Marcaj. Annotating other datasets for training is unrestricted. The orthomosaic may be retiled any way for training. The submission is the annotation of the **supplied** tiles. Using another team’s annotations is not allowed. [S-DESC]

Named open datasets (names and counts are from the brief): [S-DESC] Licences and downloads were checked on 2026-09-25 and written in [Research](research.md).

| Dataset | What the brief says | What it is not |
|---|---|---|
| Riseholme | 855 UAV RGB images, 40,215 COCO segmentation annotations, including canopy and row classes | Not Sireț3. Scale, season, and appearance differ. |
| UOPNOA | About 34,000 RGB aerial images and land-use masks | Vineyard-block labels are not individual-canopy ground truth. |
| DroneWaste | An open annotated aerial-waste reference | Not this site. |

## Licence

Sireț3 imagery: **CC BY 4.0**. Credit 3DATA COLLECT / OpenAerialMap, contributors to the Open Imagery Network. The brief states that this licence permits reuse, adaptation, and redistribution, including commercial use, subject to its terms. Challenge tiles are that mosaic, reprojected to EPSG:32635 and cut. Keep the attribution when the imagery is reused. [S-README] [S-DESC]

The brief also lists the tiles as “ZIP and cloud link” and the source mosaic as “cloud link / OpenAerialMap”. No URL for either link is in the package, and a public OpenAerialMap item URL was not found on 2026-09-25. [S-DESC] [S-GEO]

Route layers contain OpenStreetMap data, © OpenStreetMap contributors, ODbL. [S-README]

Related: [Spatial](spatial.md) · [Examples](examples.md) · [Research](research.md)
