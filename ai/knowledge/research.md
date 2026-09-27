# Research

Part of the [Sireț3 knowledge base](README.md). Cite [sources](sources.md).

Each path is a question to close, not a result. Status starts at `not started`. When a path produces a number, write it under Findings and point at the script, dataset licence, and date. Do not paste unverified dataset URLs into the fact files.

| ID | Question | Why it matters | Where to look | Status | Findings |
|---|---|---|---|---|---|
| R1 | Can a canopy instance model trained on Riseholme transfer to 2.5 cm Sireț3 tiles? | 25% of the score. Riseholme is the only dataset the brief says has canopy and row classes. | Riseholme paper and licence; a few local tiles including `r021_c012` and `r006_c004` as a visual check only (they are not a test set). | licence checked, transfer not tested | Official COCO set is CC BY 4.0, 3.3 GB. Classes are `pole`, `trunk`, `vine_row`, `vineyard`. The record does not say a `vineyard` polygon is one plant, and it does not state GSD. See findings. |
| R2 | Does a row-first method (line detection, then split every 1.0–1.5 m) beat instance segmentation on touching canopies? | Rules require a split even when foliage does not narrow. | Annotation rules §2.2; classical Hough / skeleton baselines. | not started | |
| R3 | How should plants cut by a tile edge be paired so they are not double-counted in the area union? | Canopy area is the union of canopy polygons. Edge pieces are separate polygons. | Challenge description, “Counts and measurements” [S-DESC]; tile-edge rule in [Annotation](annotation.md); grid formula in [Spatial](spatial.md). | not started | |
| R4 | What color and texture separates vine canopy, vine tube, shadow, and weed at 2.5 cm? | Tubes and stakes are neither canopy nor waste. Shadows are not canopy. | Example previews; rules §2 and §3. | not started | |
| R5 | Which waste detector has a low false-positive rate on soil, tubes, and stones? | False boxes cost the same as misses. IoU threshold is only 0.3, but the box must be tight. | DroneWaste licence; rules §3. | licence checked, detector not tested | DroneWaste is CC BY 4.0 but labels landfill dumps. UAVVaste is the closer open litter set (CC BY 4.0, low-altitude boxes). Neither is vineyard soil. See findings. |
| R6 | Can `row_structure` and `interrow_cover` be rules on geometry and color instead of a classifier? | 5% of the score. Thresholds are explicit: 5 m gap; 25% and 75% cover. | Rules §4.3 and §5.2. | not started | |
| R7 | How to cluster canopies into blocks given the 5 m gap rule and the “road always splits” rule? | 2% + 2% + 2% grouping, and every object needs an id. | `passages.geojson`; rules §6. | not started | |
| R8 | What graph lets a route stay inside inter-rows ∪ passages and still reach the start? | Entire 25% route score can be 0. | `passages.geojson`, `forbidden.geojson`, `start.geojson`. | not started | |
| R9 | Is the organizer ZIP accepted by Marcaj, or must parts 1–4 be split below 90×10⁶ bytes? | Publishing is blocked if the upload fails. | Marcaj draft project; byte sizes in [Spatial](spatial.md). | not started | |
| R10 | What `measurements.csv` columns does the jury need to see? | Required file, schema unstated. | Challenge description “Counts and measurements”; Slack if a template appears. | not started | |
| R11 | UOPNOA: useful for block masks, or a distraction because it is not plant-level? | Brief warns it is not canopy ground truth. | UOPNOA licence and label spec. | closed: skip for canopy | CC BY 4.0, 33,699 tiles, 0.25 m/px. Class `VI` is a SIGPAC plot mask. Not plant-level. See findings. |
| R12 | Source mosaic at 2.40 cm vs tiles at 2.50 cm: train on source crops or on the supplied tiles only? | Domain shift and CRS (4326 vs 32635). | [Spatial](spatial.md). | not started | |
| R13 | Which `terenuri` intersect the 311-tile footprint, and do their edges match block splits? | Decides whether a cadastral overlay is one cached GeoJSON or noise. | WFS bbox on FNDG `terenuri`, intersect in EPSG:32635. Two Sireț points and the start are already looked up. [Cadastru](cadastru.md). | not started | Start 47.1230335, 28.7073776 has no parcel (sector `8037114`). Nearby hits: `80371130109` (0.70 ha, 5 corners) and `80371140487` (0.37 ha, 33 corners, jagged). |
| R14 | Which public YOLO (or YOLO-convertible) sets label a vineyard region (block/parcel) versus one plant canopy? | A region detector is not the Marcaj `vineyard` plant class. The two meanings must stay separate. | Zenodo, arXiv, GitHub, publisher PDFs, 2018–2026. | sources opened 2026-09-26 | Yes for block/semantic vine area under CC BY (UOPNOA; Riseholme after COCO→YOLO). No opened licence-clean set states one canopy polygon = one plant. No native YOLO txt of per-plant canopies under CC BY/CC0/MIT. See 2026-09-26 findings. |
| R15 | For ICAERUS polygons, which trainer has the higher published mask accuracy, Roboflow YOLO or RF-DETR Seg? | Canopy score is 60% class overlap and 40% instance match. | Ultralytics segment docs, RF-DETR benchmark, Roboflow train docs, 2026-09-26. | closed: RF-DETR Seg 2XLarge | YOLO26x-seg mask mAP 47.0 at 640. RF-DETR-Seg 2XL COCO mask AP 49.9 at 768. Roboflow’s train guide names RF-DETR Seg as their best instance-segmentation accuracy. Write-up: [Training stack](training-stack.md). |
| R16 | What do the organizer hints (domain adaptation, morphology, erosion) require of an ICAERUS + Riseholme training set? | Canopy area, inter-row area, and row length are measured from the mask edge and from the centre line. | Local `multi_vines` GeoJSON; Pádua et al. 2020; ICAERUS raw-imagery record. | closed 2026-09-26 | ICAERUS pieces sit 0.41 m apart and group into rows 2.53 m apart. A 10 cm erosion keeps 24% of the area. Write-up: [Mask adaptation](mask-adaptation.md). |

## Findings log

**2026-09-25 — labeled sets that match the four Marcaj tasks.** Sources opened that day: [S-RISE] [S-AGRIDS] [S-WASTE] [S-UAVV] [S-UOP] [S-BARROS] [S-ESCA].

| Task | Use | Do not use |
|---|---|---|
| Canopy instances (`vineyard`) | Riseholme COCO, class `vineyard`, plus `trunk` as the plant-level point. [S-RISE] | AGRIDS and the Kaggle YOLO mirror (non-commercial / no-derivatives). [S-AGRIDS] UOPNOA plot masks. [S-UOP] Ground-level bunch sets (WGISD, VINEPICs, Grapevine-Seg). |
| Row axes | Riseholme class `vine_row` is an instance mask. A centre line has to be derived. [S-RISE] | AGRIDS row labels, same licence block. [S-AGRIDS] |
| Waste boxes | UAVVaste: 772 images, 3,718 litter boxes and masks, one class, low altitude. [S-UAVV] | DroneWaste: 4,993 tiles and 5,135 boxes of landfill materials, 20 classes. Legal, wrong scene. [S-WASTE] |
| `row_structure`, `interrow_cover` | No public set uses these values. The thresholds are in the rules (5 m gap; about 25% and 75% vegetation). | — |

Riseholme record, verbatim classes: `pole`, `trunk`, `vine_row`, `vineyard` (canopy). 855 images, 40,215 COCO annotations, three seasons, train/val/test already split. File `riseholme-vineyard.zip`, 3,344,879,865 bytes. Licence on the Zenodo record: CC BY 4.0. The record does not state GSD and does not say one `vineyard` polygon equals one plant. [S-RISE]

Related AGRIDS zip is CC BY-NC-ND 4.0 (`vineyard_segmentation.v11i.yolov11.zip`, 2,224,959,050 bytes). Posts and rows at 12 m, 20 m, 30 m (Lincoln) and 40 m (Oxfordshire). Do not train the prize model on it. [S-AGRIDS]

UOPNOA: CC BY 4.0, `UOPNOA.zip` 3.8 GB, 33,699 images of 256×256 from Spanish PNOA, GSD 0.25 m/px. Class `VI` is vineyard land use from SIGPAC, 1,759 plots. That is a block-scale mask at ten times the Sireț3 pixel size. [S-UOP]

Barros et al. RGB orthomosaics are the closest published GSD: 1.7 cm/px at Esac (120 m AGL) and 1.0 cm/px at Valdoeiro and Quinta de Baixo (60 m). Masks are one semantic class, vine pixels. Only Esac is fully labeled. The GitHub code is MIT. The imagery is not a direct download; the README says to email the author. Imagery licence is not stated. [S-BARROS]

EscaYard is CC BY 4.0 and has RTK trunk locations, not canopy polygons. Flown at 30 m. The orthomosaics are multispectral and large (about 3.4 GB and 1.5 GB). [S-ESCA]

No opened dataset contains one-plant nadir canopy polygons in the Marcaj sense, inter-row polygons, or the attribute vocabularies.

**2026-09-26 — public YOLO / YOLO-convertible vineyard region labels (block vs plant).** Sources opened that day: [S-RISE] [S-AGRIDS] [S-UOP] [S-BARROS] [S-ESCA] [S-ICAERUS] [S-OPENAGRI] [S-AGHI] [S-UAVINE] [S-PSIROUKIS] [S-PADUA] [S-KERKECH] [S-3D2CUT] [S-VINESET] [S-AGRIDS-SW]. Re-checked the 2026-09-25 records on their Zenodo API or HTML pages. Those pages still match the 2026-09-25 facts. Zenodo HTML for Riseholme and EscaYard timed out; the JSON API for those two records loaded.

Two meanings are kept separate.

**Meaning 1 — block / parcel / land-use region** (“this area is vineyard”).

UOPNOA is the only opened licence-clean set whose labels are the planting as a whole. Pedrayes et al. name class `VI` as Vineyard. Masks are SIGPAC plot polygons painted onto PNOA aircraft RGB, 256×256 tiles, GSD 0.25 m/px, 33,699 images, CC BY 4.0. Not plant-level. Format is semantic masks, not YOLO txt. A connected `VI` region can be turned into a YOLO-seg polygon without new drawing. Viewpoint is aerial nadir orthophoto, not UAV at 2.5 cm. [S-UOP]

Barros et al. are the closest published GSD to Sireț3: HD-RGB 1.7 cm/px at Esac (120 m AGL) and 1.0 cm/px at Valdoeiro (60 m) and Quinta de Baixo (60 m; paper also says the Quinta de Baixo survey height was 70 m). Masks are one semantic class: vine-plant pixels vs everything else. Only Esac is fully labeled. GitHub code is MIT. Imagery is by email to tiagobarros@isr.uc.pt. Imagery licence is not stated. Do not train the prize model on it. [S-BARROS]

**Meaning 2 — plant canopy region** (Marcaj `vineyard` = foliage of one grapevine).

Riseholme COCO: 855 UAV RGB images, 40,215 annotations, classes `pole`, `trunk`, `vine_row`, `vineyard` (canopy), instance segmentation, train/val/test already split, file `riseholme-vineyard.zip` 3,344,879,865 bytes, CC BY 4.0. Used by the authors for YOLOv11 instance segmentation. Not native YOLO txt; COCO instance masks convert to YOLO-seg. The record still does not state GSD or altitude. It still does not say one `vineyard` polygon equals one plant. [S-RISE]

AGRIDS: native YOLOv11 zip `vineyard_segmentation.v11i.yolov11.zip` (2,224,959,050 bytes). The record says images are labelled with post and row locations. UAV RGB, Lincoln 12 m / 20 m / 30 m, Oxfordshire 40 m. Licence `cc-by-nc-nd-4.0`. Do not train the prize model on it. [S-AGRIDS]

ICAERUS / Marengo & Sirsat: RGB orthomosaics plus 751 five-metre GeoPackage cells for blocks AB01, AB02, TR01. The page says outputs are vine polygons generated from YOLO txt files, for “segmentation of individual vines or vine rows”. File `AI_model.zip` 3,095,258,752 bytes. Licence `cc-by-nc-4.0`. The record does not state GSD. Do not train the prize model on it. [S-ICAERUS]

EscaYard: CC BY 4.0. UAV multispectral orthomosaics at 30 m (filenames contain `30M0G`) and `trunk_locations_VineyardB7.zip`. Trunk points, not canopy polygons. [S-ESCA]

Pádua et al. (Remote Sensing 2020, 12, 139) describe individual-grapevine detection on UAV RGB. The paper does not give a public label download. [S-PADUA]

Kerkech et al. (arXiv:1912.05281) segment UAV visible/IR pixels as shadow, ground, healthy, symptom. The paper does not give a public dataset URL. [S-KERKECH]

LCAS/AGRIDS on GitHub is a vineyard map database (block, vine-row, vine entities). It is not an image-label set. [S-AGRIDS-SW]

**Row-level masks** (what some sets actually label). Riseholme `vine_row` is an instance mask, not a block and not one plant. [S-RISE] AGRIDS labels posts and rows. [S-AGRIDS] Barros positive pixels are vine plants, which in a row look like a row strip, but the paper calls them vine-plant pixels, not row instances. [S-BARROS]

**Answers.**

Yes: there is at least one licence-clean set whose labels are a vineyard region (block or semantic vine area) and that can be converted to YOLO segmentation. UOPNOA class `VI` is the block/parcel case. Riseholme `vineyard` / `vine_row` instances can be unioned into a vine-area mask and exported to YOLO-seg. [S-UOP] [S-RISE]

No: no opened set states that one mask is the canopy of one grapevine in the Marcaj sense. Riseholme names `vineyard` as canopy and as an instance class, but not as one plant. ICAERUS talks about individual vines but is CC BY-NC. [S-RISE] [S-ICAERUS]

Best YOLO starting point for “paint the vineyard region on a nadir photo”: Riseholme COCO, class `vineyard` (canopy) and/or `vine_row`, converted to YOLO-seg. It is UAV RGB, CC BY 4.0, already used for YOLOv11-seg, and does not need relabeling to get a vine-area polygon. It still may not match 2.5 cm Sireț3: the record does not state GSD, and a `vineyard` instance is canopy, not a SIGPAC-style block. UOPNOA is the cleaner block label but at 0.25 m/px (ten times the tile pixel size) and is aircraft PNOA, not a 2.5 cm UAV tile. [S-RISE] [S-UOP]

No opened set is native YOLO txt with per-plant canopy polygons under a commercial-ok licence (CC BY / CC0 / MIT). The only native YOLO vineyard zip opened is AGRIDS (posts and rows, CC BY-NC-ND 4.0). [S-AGRIDS]

A first-party author also posted a Riseholme YOLO export on Kaggle as CC BY-NC 4.0 (`vineyard_segmentation_paper.yolov11`). That card is not the Zenodo COCO authority. The official Riseholme record remains CC BY 4.0. Do not treat the Kaggle/Roboflow export as the licence for the prize model.

**2026-09-26 — organizer hints on the joint ICAERUS + Riseholme set.** Domain adaptation, morphological cleanup, and erosion are one preparation pipeline, written up in [Mask adaptation](mask-adaptation.md). ICAERUS RGB is 1.4 cm at 30 m. [S-ICAERUS-RAW] Predicted polygons in `multi_vines` have median nearest-neighbour 0.41 m and, once grouped, row spacing 2.53 m. A 10 cm erosion keeps 24% of that area, which misses the 15% area tolerance. [S-MASK] [S-PADUA] [S-DESC]

**Named searches that are not this task.** OpenAgri Viewer YOLO is ground-level along rows (clusters, artificial mildew, side-on `trunk` and `foliage`), not a nadir vineyard-region set. [S-OPENAGRI] Aghi et al. “Semantic Segmentation Vineyard Rows” is 500 ground-level RGB frames with binary row masks, CC BY 4.0, from a robot camera in the row, not UAV nadir. [S-AGHI] 3D2cut is 1,511 smartphone vines on a backdrop sheet, JSON structure, CC BY-NC-SA 4.0. [S-3D2CUT] VineSet is ground-level trunk boxes (Pascal VOC). [S-VINESET] UAVINE is unlabeled hyperspectral/RGB over a Greek vineyard (README: BSD-3-Clause on the images). [S-UAVINE] Psiroukis ICAERUS UAV RGB/MS/thermal at 30 m (folder text also says 70 m) has no region labels; CC BY 4.0. [S-PSIROUKIS] DeepVine/DeepViNE in the search results is a virtual-network paper, not a vineyard set. Comba vineyard-detection papers were not found with a public label download.

Related: [Solution](solution.md) · [Data](data.md) · [Scoring](scoring.md)
