# Mask adaptation for ICAERUS and Riseholme

Part of the [Sireț3 knowledge base](README.md). Cite [sources](sources.md).

Opened 2026-09-26. This is an interpretation of three organizer hints against the scoring rules and the local ICAERUS export. It is not a challenge rule.

The hints are **domain adaptation**, **morphological operation**, and **erosion of the segmentation mask**. Together they describe how to prepare ICAERUS and Riseholme so a model predicts the objects whose areas, lengths, and counts are scored on Sireț3.

## What each hint means here

**Domain adaptation.** ICAERUS and Riseholme are other vineyards. The model has to land on Sireț3, which has no training labels beyond two unscored example tiles. The shift that moves the measurements is the pixel size, then the colour of soil and canopy, then the meaning of a polygon. [S-DESC] [S-ICAERUS-RAW] [S-RISE]

**Morphological operation.** A binary canopy mask is cleaned with the standard set: opening drops specks, closing fills holes inside a vine, dilation joins pieces of one row, erosion shrinks a boundary. Pádua et al. use that sequence to go from a vegetation mask to vine rows and then to one plant. [S-PADUA]

**Erosion of the segmentation mask.** In that sequence, erosion is the step that turns a row strip into its centre line. Pádua: clusters are dilated along the row, then eroded to image S, the row central lines. Plants are ticks along S at the in-row spacing, then thickened back so each plant keeps its own pixels and the plants stay unconnected. Area is counted on that restored vegetation, as pixel count times GSD squared. [S-PADUA]

The leaf polygon and the eroded mask are different objects. Canopy area and inter-row area use the leaf edge. Row length uses the centre line. [S-RULES] [S-DESC]

## Scale

| Site | Pixel size | What a 1 m vine is |
|---|---|---|
| ICAERUS RGB, DJI Mavic 3M, 30 m AGL | 1.4 cm | about 71 px |
| Sireț3 tiles | 2.5 cm | 40 px |

ICAERUS orthophotos were built in webODM with orthophoto resolution 1.4. The raw-imagery record states the same 1.4 cm RGB and 4.8 cm multispectral, flights at 30 m above ground, perpendicular to the rows, dates 28 May through 4 Sep 2024, Reynolds blocks AB01, AB02, TR01. [S-ICAERUS-RAW]

Sireț3 tiles are 2048 × 2048 px, 0.025 m/px, 51.2 m on a side. [S-RULES]

The official Riseholme COCO record does not state GSD or altitude. Read the pixel size from the frames before resampling. A Kaggle card that mentions 12 m, 20 m, and 30 m is the CC BY-NC export and is not the authority for the CC BY 4.0 COCO set. [S-RISE]

Training at native ICAERUS resolution teaches a plant that is 1.8 times larger in pixels than the same plant on a Sireț3 tile. Area, length, and the 1.0–1.5 m split are all metric, so both sources have to be resampled to 0.025 m/px before they are mixed.

ICAERUS training chips are the 5 m × 5 m cells. A Sireț3 tile is 51.2 m and includes roads, empty ground, and block edges. Empty tiles are penalised when false canopy covers them. Windows for the joint set should be large enough to show the row spacing, about 2.5–2.7 m on the example tile. [S-DESC] [S-EX]

## What the local ICAERUS masks actually are

Measured 2026-09-26 from `assets/AI_model`. [S-MASK]

`OUTPUT/multi_vines` is the model’s own segmentation, written out from YOLO text, not the Labelme drawings. 1,615 GeoJSON files, 24,552 polygons, EPSG:32629. One sample cell spans about 5.5 m.

| Quantity | p10 | median | p90 |
|---|---:|---:|---:|
| Polygon area | 0.072 m² | 0.194 m² | 0.402 m² |
| Long side of the box | 0.38 m | 0.65 m | 0.99 m |
| Distance to the nearest other polygon | 0.17 m | 0.41 m | 0.83 m |

No polygon is longer than 3 m. Grouping polygons whose 0.35 m buffers touch (so pieces within 0.70 m join) produces clusters with a median of 7 members. Those clusters sit 2.53 m apart at the median (p10 2.15 m, p90 2.92 m). That is row spacing. The example tile’s axes are about 2.65 m apart. [S-EX]

So each ICAERUS polygon is a piece of a row, and the pieces chain into the row. Sireț3 wants one polygon per plant, with in-row spacing typically 1.0–1.5 m, and a split at that distance when foliage does not narrow. [S-RULES]

The Labelme subset in `INPUT/YOLODataset/labels` is 85 images and 1,093 polygons. If each image is the 5 m cell, the median polygon is 0.089 m² and the median nearest neighbour is 0.39 m. That metre conversion assumes the image is 5 m across. The GeoJSON figures above do not need that assumption.

Overlap: on a sample of predicted cells, the union of polygons is 78.5% of the sum of their areas, so the pieces overlap.

## Erosion and the 15% area tolerance

Round shrink of 1,676 predicted polygons, same day: [S-MASK]

| Shrink | Polygons deleted | Area kept |
|---|---:|---:|
| 2 cm | 0% | 80% |
| 4 cm | 0% | 63% |
| 6 cm | 0.5% | 47% |
| 10 cm | 10% | 24% |

Canopy area and inter-row area score `max(0, 1 − relative_error / 0.15)`. An error of 15% scores 0. Row length uses 10%. [S-DESC]

The drawing rule traces leaves within about 10 cm and excludes shadow, weeds, and grass. A 10 cm shrink matches that sentence and, on these narrow canopies, throws away three quarters of the area. The 10 cm figure is the tracing tolerance. It is not a kernel radius for the polygon that gets measured. [S-RULES]

Pádua’s order is the one that keeps both numbers: erode to the centre line, place the plants, thicken back onto the vegetation mask, measure area on the thickened mask. [S-PADUA]

A 2 cm shrink still loses 20% of the area. Use it only when the mask is fat by about that much (shadow halo). Calibrate the radius on the two example tiles so class IoU rises and the area error stays inside 15%.

## How the prepared mask becomes each measurement

| Measurement | Mask step |
|---|---|
| Canopy class IoU (60% of the 25% canopy score) | Leaf pixels. Shadow, tubes, stakes, and grass stay out. |
| Instance F1 at IoU ≥ 0.5 (40% of that 25%) | One polygon per plant. Merge the 0.4 m pieces, then split at 1.0–1.5 m. |
| Canopy area, 2%, tolerance 15% | Union of those leaf polygons. The eroded centre line is not this area. |
| Inter-row area, 2%, tolerance 15% | Ground between canopy edges of neighbouring rows, stopping at the row ends. |
| Row length, 2%, tolerance 10% | Centre line from erosion of the row strip, then simplified. Example rows are two-point polylines. A wiggly skeleton runs long. |
| Row count and `row_structure` | One id per physical row. A gap of 5 m or more along the axis is `disrupted`. Erosion that deletes a small real vine invents that gap. |
| Block count | Plantings separated by a road, or by 5 m of non-vineyard. That rule is metric, not a kernel size. |
| Route, 25% | The route has to stay on inter-row and passages. More than 2% of the length off that corridor scores 0 for the criterion. A fat canopy shrinks the corridor. |

Young vines stay, however small. Clumps under about 0.2 m² that are not a plant are dropped. An opening sized to delete every polygon under 0.2 m² would delete real ICAERUS vines: the predicted median area is 0.194 m². [S-RULES] [S-MASK]

## Class map for the joint set

| Source | Use as |
|---|---|
| ICAERUS `vine` | Canopy pixels. Then one plant per 1.0–1.5 m along the row. |
| Riseholme `vineyard` | Canopy pixels. The record calls it canopy and does not say one plant. |
| Riseholme `vine_row` | The strip that is eroded to an axis. Not a canopy class. |
| Riseholme `trunk` | The seed for the plant split, and a check that the axis passes through vine centres (drawing rule: within 0.2 m). |
| Riseholme `pole` | Left out. A post is not a vine and not waste. |
| Riseholme March 2025 | Trunks and axes only. Those frames are dormant. Canopy colour from them would fight the leaf class. |

Riseholme official COCO is CC BY 4.0. ICAERUS `AI_model` is CC BY-NC 4.0. The brief allows open sets whose licences were checked and listed. [S-RISE] [S-ICAERUS]

## Preparation checklist

One joint set, one pixel size, one meaning of a polygon. Do these in order. The Labelme polygons and the Riseholme COCO annotations are the labels. `OUTPUT/multi_vines` is a previous model’s output, so it stays out of the training labels.

### 1. Take the right files

1. ICAERUS: RGB orthomosaics for Reynolds AB01, AB02, TR01, and the Labelme vine polygons (the YOLO text converted from those drawings). Six dates, 28 May–4 Sep 2024. Pixel size 1.4 cm.
2. Riseholme: the Zenodo COCO set (CC BY 4.0), classes `pole`, `trunk`, `vine_row`, `vineyard`. Read the pixel size from the frames. The record does not state it.
3. Hold the two Sireț3 example tiles out as the check. They are not training bulk.

### 2. Put both on the Sireț3 pixel size

4. Resample every ICAERUS orthomosaic from 1.4 cm to 0.025 m/px. Scale factor 1.4/2.5.
5. Resample every Riseholme frame to 0.025 m/px using the pixel size read in step 2. Scale the COCO polygons by the same factor.
6. Work in metres from here on. A 1 m vine is 40 px in both sets, as on a Sireț3 tile.

### 3. Map both label sets onto one class

7. ICAERUS `vine` becomes canopy pixels.
8. Riseholme `vineyard` becomes canopy pixels.
9. Riseholme `vine_row` becomes the row strip used to build the axis. It is not a canopy instance.
10. Riseholme `trunk` becomes the plant-centre seed.
11. Riseholme `pole` is dropped.
12. Riseholme March 2025 frames keep trunks and row axes only. Their canopy masks are dropped, because the vines are dormant.

### 4. Turn pieces into one plant polygon

13. Rasterize the canopy at 0.025 m/px.
14. Close along the row so pieces within about 0.7 m join into a strip. ICAERUS pieces sit about 0.41 m apart and already chain into rows about 2.5 m apart.
15. Open with a small disk to drop specks that are not plants. Leave real vines in, including ones under 0.2 m². The ICAERUS median vine is 0.19 m².
16. Erode the strip to a one-pixel centre line. Simplify that line to a polyline. That line is the row axis. It is not the canopy polygon.
17. Walk the line at 1.0–1.5 m. Where a Riseholme trunk exists, snap the tick to the trunk. Skip a tick that lands on bare ground. A break of 5 m or more stays a gap and does not start a new row.
18. Thicken each tick back onto the uneroded canopy, and keep neighbouring plants from reconnecting. Those polygons are the instance labels. Area is their union.

### 5. Recolor Riseholme soil toward Sireț3

19. Dilate the canopy polygon by about 10 cm. Pixels inside stay untouched, so the leaves stay green.
20. On the pixels outside, transfer LAB *a* and *b* toward Sireț3 soil. Tan target from `siret3_r021_c012`: RGB 150, 138, 116. Grey-brown target from `siret3_r006_c004`: RGB 138, 128, 119. Keep luminance.
21. Write two extra Riseholme copies, one per target. Keep the original grass frames as well. Sireț3 still has grass inter-rows.
22. Leave ICAERUS colours as they are. That soil is already bare.

### 6. Cut one window size and stack the sets

23. Cut 1024 × 1024 windows (25.6 m at 0.025 m/px) with overlap, from the resampled orthomosaics and frames. A 5 m ICAERUS cell is too small. The window has to show several rows.
24. Include windows with no vines, taken from roads and headlands inside the same orthomosaics. Empty Sireț3 tiles are penalised if the model paints canopy on them.
25. Give both sources the same layout: RGB uint8 image, one YOLO-seg class `vine`, one polygon per plant. Same image size, same class id, same metres-per-pixel.
26. Split train and val by vineyard block and by date, so the same row does not sit in both. Keep Riseholme’s official test split out of training.
27. Balance the loader so ICAERUS, original Riseholme, and the two recolored Riseholme copies each appear. The larger source must not drown the other.

### 7. Check before training

28. On a handful of windows, confirm plant spacing is about 1.0–1.5 m, row spacing is about 2.5 m, and the polygon follows the leaves rather than the centre line.
29. Run the same check on the two Sireț3 example tiles after a short training pass: canopy area within 15%, and one polygon per plant.

## Riseholme grass to Sireț3 tan soil

Riseholme inter-rows are grass. The two Sireț3 example tiles are mostly bare soil. Measured 2026-09-26 on the example GeoTIFFs, pixels with low excess green: [S-EX]

| Tile | Soil RGB | What it looks like |
|---|---|---|
| `siret3_r021_c012` | 150, 138, 116 | Warm tan. Red above green, blue well below. The yellow soil. |
| `siret3_r006_c004` | 138, 128, 119 | Greyer brown. This tile also has grass strips (`mixed`). |

Leaf pixels on both tiles keep green above red and a much lower blue. A hue swap of every green pixel paints the vines the same tan as the soil, and the canopy class learns the wrong colour.

Recolor the complement of the canopy polygon. Dilate that polygon by about 10 cm first so the leaf edge stays green. On the remaining pixels, transfer only the colour channels (LAB a and b) toward the tan above, and keep luminance so shadows and texture stay. Reinhard transfer on those two channels is enough. A second copy can target the greyer soil.

Train on the original Riseholme frames and on the recolored copies. Sireț3 still has `vegetation` and `mixed` inter-rows, so the grass version stays in the set. The recolored images are for the canopy model. `interrow_cover` is read on the real Sireț3 tile, where grass is still green.

ICAERUS soil is already bare. This recolor is for Riseholme.

Related: [Scoring](scoring.md) · [Annotation](annotation.md) · [Training stack](training-stack.md) · [Research](research.md)
