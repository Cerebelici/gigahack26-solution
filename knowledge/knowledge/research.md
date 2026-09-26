# Research

Part of the [Sireț3 knowledge base](../KNOWLEDGE_BASE.md). Cite [sources](sources.md).

Each path is a question to close, not a result. Status starts at `not started`. When a path produces a number, write it under Findings and point at the script, dataset licence, and date. Do not paste unverified dataset URLs into the fact files.

| ID | Question | Why it matters | Where to look | Status | Findings |
|---|---|---|---|---|---|
| R1 | Can a canopy instance model trained on Riseholme transfer to 2.5 cm Sireț3 tiles? | 25% of the score. Riseholme is the only dataset the brief says has canopy and row classes. | Riseholme paper and licence; a few local tiles including `r021_c012` and `r006_c004` as a visual check only (they are not a test set). | licence checked, transfer not tested | Official COCO set is CC BY 4.0, 3.3 GB. Classes are `pole`, `trunk`, `vine_row`, `vineyard`. The record does not say a `vineyard` polygon is one plant, and it does not state GSD. See findings. |
| R2 | Does a row-first method (line detection, then split every 1.0–1.5 m) beat instance segmentation on touching canopies? | Rules require a split even when foliage does not narrow. | Annotation rules §2.2; classical Hough / skeleton baselines. | not started | |
| R3 | How should plants cut by a tile edge be paired so they are not double-counted in the area union? | Canopy area is the union. Edge pieces are separate polygons. | Rules §2.4; grid formula in [Spatial](spatial.md). | not started | |
| R4 | What color and texture separates vine canopy, vine tube, shadow, and weed at 2.5 cm? | Tubes and stakes are neither canopy nor waste. Shadows are not canopy. | Example previews; rules §2 and §3. | not started | |
| R5 | Which waste detector has a low false-positive rate on soil, tubes, and stones? | False boxes cost the same as misses. IoU threshold is only 0.3, but the box must be tight. | DroneWaste licence; rules §3. | licence checked, detector not tested | DroneWaste is CC BY 4.0 but labels landfill dumps. UAVVaste is the closer open litter set (CC BY 4.0, low-altitude boxes). Neither is vineyard soil. See findings. |
| R6 | Can `row_structure` and `interrow_cover` be rules on geometry and color instead of a classifier? | 5% of the score. Thresholds are explicit: 5 m gap; 25% and 75% cover. | Rules §4.3 and §5.2. | not started | |
| R7 | How to cluster canopies into blocks given the 5 m gap rule and the “road always splits” rule? | 2% + 2% + 2% grouping, and every object needs an id. | `passages.geojson`; rules §6. | not started | |
| R8 | What graph lets a route stay inside inter-rows ∪ passages and still reach the start? | Entire 25% route score can be 0. | `passages.geojson`, `forbidden.geojson`, `start.geojson`. | not started | |
| R9 | Is the organizer ZIP accepted by Marcaj, or must parts 1–4 be split below 90×10⁶ bytes? | Publishing is blocked if the upload fails. | Marcaj draft project; byte sizes in [Spatial](spatial.md). | not started | |
| R10 | What `measurements.csv` columns does the jury need to see? | Required file, schema unstated. | Challenge description “Counts and measurements”; Slack if a template appears. | not started | |
| R11 | UOPNOA: useful for block masks, or a distraction because it is not plant-level? | Brief warns it is not canopy ground truth. | UOPNOA licence and label spec. | closed: skip for canopy | CC BY 4.0, 33,699 tiles, 0.25 m/px. Class `VI` is a SIGPAC plot mask. Not plant-level. See findings. |
| R12 | Source mosaic at 2.40 cm vs tiles at 2.50 cm: train on source crops or on the supplied tiles only? | Domain shift and CRS (4326 vs 32635). | [Spatial](spatial.md). | not started | |

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

Related: [Solution](solution.md) · [Data](data.md) · [Scoring](scoring.md)
