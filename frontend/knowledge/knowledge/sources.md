# Sources

Part of the [Sireț3 knowledge base](../KNOWLEDGE_BASE.md).

Cite these ids in later notes. If a later Slack pin contradicts a PDF, add a new source row and update the fact. Do not silently overwrite.

| ID | What | Path or citation | Used for |
|---|---|---|---|
| S-README | Package index, v. the data drop | `/Users/chirill/Downloads/assets_for_participants/README.md` (file date 24 Sep 2026) | Folder contract, example counts, licence, start coordinates, tile spec |
| S-DESC | Challenge description, 5 pages, title “Vineyard AI Field Challenge”, producer WeasyPrint 70.0 | `03_docs/Vineyard_AI_Field_Challenge_description.pdf` | Problem, scope, submission, rules, scoring, named datasets |
| S-RULES | Annotation rules v1.0, 25 Sep 2026, 8 pages | `03_docs/Vineyard_AI_annotation_rules.pdf` | Labels, attributes, drawing rules, ZIP appendix |
| S-MARCAJ | Marcaj quick-start v1.0, 25 Sep 2026, 6 pages | `03_docs/Marcaj_quick_start_for_teams.pdf` | Account, upload, publish, editor, submit |
| S-EX | Example CVAT project | `05_examples/siret3_examples_cvat.zip` → `annotations.xml`, two TIFFs | Real XML, object counts, point statistics |
| S-GEO | Measurements made while writing this file, 2026-09-25 | GeoTIFF tags of one or more tiles and of the source BigTIFF; shoelace areas of the GeoJSON; ZIP central directories | Grid formula, GSD check, areas, part byte sizes, image dimensions |
| S-PREVIEW | Qualitative read of the PNG/JPG previews | `01_tiles/overview.png`, `02_route/preview_passages_forbidden.png`, `05_examples/preview_siret3_r021_c012.jpg`, `05_examples/preview_siret3_r006_c004.jpg` | Site layout and example appearance. Not used for measurements. |
| S-RISE | Riseholme COCO vineyard set, opened 2026-09-25 | https://doi.org/10.5281/zenodo.19234906 | Classes, counts, CC BY 4.0, zip size |
| S-AGRIDS | AGRIDS YOLO vineyard set, opened 2026-09-25 | https://doi.org/10.5281/zenodo.15211733 | CC BY-NC-ND 4.0, altitudes |
| S-WASTE | DroneWaste, opened 2026-09-25 | https://doi.org/10.5281/zenodo.17045559 | Landfill boxes, CC BY 4.0 |
| S-UAVV | UAVVaste, opened 2026-09-25 | https://doi.org/10.5281/zenodo.8214061 and Kraft et al., Remote Sensing 2021, 13, 965 | Aerial litter boxes |
| S-UOP | UOPNOA record and Pedrayes et al., Remote Sensing 2021, 13, 2292 | https://doi.org/10.5281/zenodo.4648002 | Plot masks, 0.25 m/px, CC BY 4.0 |
| S-BARROS | Barros et al. vineyard orthomosaics | arXiv:2108.01200 and https://github.com/Cybonic/DL_vineyard_segmentation_study | GSD and semantic vine masks |
| S-ESCA | EscaYard, opened 2026-09-25 | https://doi.org/10.5281/zenodo.10362567 | Trunk points, not canopy polygons |

External names mentioned by the brief and still not fetched: OpenAerialMap, SAM, YOLO. Add a source row when one of them is actually opened.

How to add a fact: see [How to extend](../KNOWLEDGE_BASE.md#how-to-extend) on the index.
