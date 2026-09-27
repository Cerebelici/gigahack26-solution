# Sources

Part of the [Sireț3 knowledge base](README.md).

Cite these ids in later notes. If a later Slack pin contradicts a PDF, add a new source row and update the fact. Do not silently overwrite.

| ID | What | Path or citation | Used for |
|---|---|---|---|
| S-README | Package index, v. the data drop | `assets/README.md` (file date 24 Sep 2026) | Folder contract, example counts, licence, start coordinates, tile spec |
| S-DESC | Challenge description, 5 pages, title “Vineyard AI Field Challenge”, producer WeasyPrint 70.0 | `assets/03_docs/Vineyard_AI_Field_Challenge_description.pdf` | Problem, scope, submission, rules, scoring, named datasets |
| S-RULES | Annotation rules v1.0, 25 Sep 2026, 8 pages | `assets/03_docs/Vineyard_AI_annotation_rules.pdf` | Labels, attributes, drawing rules, ZIP appendix |
| S-MARCAJ | Marcaj quick-start v1.0, 25 Sep 2026, 6 pages | `assets/03_docs/Marcaj_quick_start_for_teams.pdf` | Account, upload, publish, editor, submit |
| S-EX | Example CVAT project | `assets/05_examples/siret3_examples_cvat.zip` → `annotations.xml`, two TIFFs | Real XML, object counts, point statistics |
| S-GEO | Measurements made while writing this file, 2026-09-25 | GeoTIFF tags of one or more tiles and of the source BigTIFF; shoelace areas of the GeoJSON; ZIP central directories | Grid formula, GSD check, areas, part byte sizes, image dimensions |
| S-PREVIEW | Qualitative read of the PNG/JPG previews | `assets/01_tiles/overview.png`, `assets/02_route/preview_passages_forbidden.png`, `assets/05_examples/preview_siret3_r021_c012.jpg`, `assets/05_examples/preview_siret3_r006_c004.jpg` | Site layout and example appearance. Not used for measurements. |
| S-VISUAL | Organizer slide deck, 9 pages, “Participant workflow” | `assets/03_docs/Marcaj_Vineyard_AI_Visual_Journey.pdf` | Illustrative pipeline and mock UI. Not a rule. See [Visual guide](visual-guide.md). |
| S-RISE | Riseholme COCO vineyard set, opened 2026-09-25 | https://doi.org/10.5281/zenodo.19234906 | Classes, counts, CC BY 4.0, zip size |
| S-AGRIDS | AGRIDS YOLO vineyard set, opened 2026-09-25 | https://doi.org/10.5281/zenodo.15211733 | CC BY-NC-ND 4.0, altitudes |
| S-WASTE | DroneWaste, opened 2026-09-25 | https://doi.org/10.5281/zenodo.17045559 | Landfill boxes, CC BY 4.0 |
| S-UAVV | UAVVaste, opened 2026-09-25 | https://doi.org/10.5281/zenodo.8214061 and Kraft et al., Remote Sensing 2021, 13, 965 | Aerial litter boxes |
| S-UOP | UOPNOA record and Pedrayes et al., Remote Sensing 2021, 13, 2292 | https://doi.org/10.5281/zenodo.4648002 | Plot masks, 0.25 m/px, CC BY 4.0 |
| S-BARROS | Barros et al. vineyard orthomosaics | arXiv:2108.01200 and https://github.com/Cybonic/DL_vineyard_segmentation_study | GSD and semantic vine masks |
| S-ESCA | EscaYard, opened 2026-09-25 | https://doi.org/10.5281/zenodo.10362567 | Trunk points, not canopy polygons |
| S-CAD | Public cadastral lookup, tested 2026-09-26 | `cadastro/moldova-cadastru-api.md`, `cadastro/md_parcel.py`; FNDG WFS `geodata.gov.md` layer `terenuri`; RBI WMS `map.cadastru.md` layer `cad_terenuri` | Parcel id, rings, admin unit, Sireț samples |
| S-SICBI | SICBI concept note, AGCC, May 2025 | https://www.gov.md/sites/default/files/media/documents/sedinte-de-guvern/2025-05/NU-76-AGCC-2025.pdf | Teren is part of a cadastral sector; the cadastral number is the unique id |
| S-ICAERUS | Marengo & Sirsat YOLOv9 vine segmentation inputs/outputs, opened 2026-09-26 | https://doi.org/10.5281/zenodo.14605848 | Orthomosaics + 5 m cells; outputs from YOLO txt; CC BY-NC 4.0 |
| S-ICAERUS-RAW | Mavic 3M raw imagery record, opened 2026-09-26 | https://doi.org/10.5281/zenodo.14604638 | RGB 1.4 cm, multispectral 4.8 cm, 30 m AGL, flights perpendicular to the rows |
| S-MASK | Polygon measurements on the local ICAERUS export, 2026-09-26 | `assets/AI_model/OUTPUT/multi_vines` (1,615 GeoJSON) and `INPUT/YOLODataset/labels` (85 files) | Areas, nearest-neighbour gaps, row grouping, erosion area loss. Write-up: [Mask adaptation](mask-adaptation.md) |
| S-OPENAGRI | OpenAgri Viewer vineyard YOLO set, opened 2026-09-26 | https://doi.org/10.5281/zenodo.19698544 | Ground-level cluster / disease / trunk+foliage YOLO; CC BY 4.0 |
| S-AGHI | Aghi et al. Semantic Segmentation Vineyard Rows, opened 2026-09-26 | https://doi.org/10.5281/zenodo.4601472 and arXiv:2107.00700 | 500 ground-level RGB + binary row masks; CC BY 4.0 |
| S-UAVINE | UAVINE hyperspectral/RGB vineyard imagery, opened 2026-09-26 | https://github.com/aelsaer/uavine | Unlabeled UAV imagery; README states BSD-3-Clause on the images |
| S-PSIROUKIS | ICAERUS UAV RGB/MS/thermal vineyard images, opened 2026-09-26 | https://doi.org/10.5281/zenodo.18678620 | Unlabeled 30 m (folder text also 70 m) imagery; CC BY 4.0 |
| S-PADUA | Pádua et al. individual grapevine UAV analysis, opened 2026-09-26 | https://doi.org/10.3390/rs12010139 | Method paper; no public label download stated |
| S-KERKECH | Kerkech et al. UAV vine disease segmentation, opened 2026-09-26 | arXiv:1912.05281 | Semantic shadow/ground/healthy/symptom; no public dataset URL |
| S-3D2CUT | 3D2cut Single Guyot, opened 2026-09-26 | https://doi.org/10.34777/azf6-tm83 (Zenodo record 7679898) | Ground smartphone vines + JSON structure; CC BY-NC-SA 4.0 |
| S-VINESET | Mendes et al. VineSet trunk detection, opened 2026-09-26 | https://doi.org/10.3390/agriculture11020131 | Ground-level Pascal VOC trunk boxes; not nadir canopy |
| S-AGRIDS-SW | LCAS AGRIDS map platform, opened 2026-09-26 | https://github.com/LCAS/AGRIDS | Block/row/vine map database, not image labels |

External names mentioned by the brief and still not fetched: OpenAerialMap, SAM, YOLO. Add a source row when one of them is actually opened.

How to add a fact: see [How to extend](README.md#how-to-extend) on the index.
