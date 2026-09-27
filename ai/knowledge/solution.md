# Solution

Part of the [Sireț3 knowledge base](README.md). Cite [sources](sources.md).

Everything in this file is **ours**. It is not a rule. Leave a dated note when a decision changes. Do not delete rejected options; move them to the log.

## Current decision

The waste detector is chosen. No route solver or web stack is chosen. The weekend clock is in [Plan](plan.md): ML pre-annotations Friday night through Saturday midday, route and web in parallel on the example annotations, import and publish by Saturday ~14:00, everyone annotates on Saturday, Sunday morning export and pitch. 2026-09-26.

## Product skeleton (fill in)

| Piece | Choice | Why | Status |
|---|---|---|---|
| Vineyard regions | `BlockUNet`, weights `weights/block_unet.pt`. Vine pixels on a 0.40 m/px mosaic, then 5 m gaps and passages. | Groups tiles into plantings before canopy inference. Not a scored canopy. See [Blocks](blocks.md). | chosen |
| Canopy instances | | | open |
| Waste boxes | YOLO26n detection. Weights `waste/best.pt`, trained on UAVVaste, one class `waste`. A box is kept only when confidence is at least **0.90**. | Below that, the model boxes vines, leaves, and bare soil. A false box costs the same as a miss. | chosen |
| Row axes | | | open |
| Inter-row polygons | Whole-map strips between neighbouring rows of a block, 0.30 m off each axis, cut at tile edges | Continuous across tiles; the route walks them | chosen |
| `row_structure` / `interrow_cover` | | | open |
| Block and row IDs across tiles | Whole-map unification (`src/spatial/unify.py`): link per-tile segments across tile edges by their vines, refit each physical row in map space, cut at passages, blocks = connected parallel rows with no passage between. `file1.txt` names the blocks. | Tile-by-tile stitching by a block-wide offset merged or split rows on long blocks. Marcaj needs one polyline per row per tile, so rows are cut back to tiles after the whole-map build. | chosen |
| Route graph and solver | | | open |
| Web map | | | open |
| Measurement export | | | open |
| Marcaj ZIP writer | | | open |
| Cadastral overlay | Not chosen. Candidate: cached parcel polygons on the web map and extra CSV columns. | Legal holding ≠ scored canopy area. See [Cadastru](cadastru.md). | open |

## Pipeline (intended order, not a design)

1. Read the 311 tiles with a GeoTIFF reader that understands JPEG-in-TIFF YCbCr (GDAL/rasterio). Do not treat them as plain JPEG.
2. Predict canopies, waste, and row geometry in pixel space.
3. Stitch IDs in map space with the grid formula in [Spatial](spatial.md).
4. Derive inter-row polygons from canopy edges and row axes. Classify cover and structure.
5. Write CVAT 1.1 ZIPs that contain the **original** TIFF bytes.
6. Import, publish, correct, submit in Marcaj.
7. Export annotations, compute measurements in EPSG:32635, build inspection targets, solve the route, write `route.geojson` and `measurements.csv`, show them on the web map.

The retired root summary named YOLOv8-seg, SAM, classical vision, RT-DETR, DBSCAN, and a TSP solver as a sketch. None of those is chosen.

## Open decisions

| ID | Question | Blocks |
|---|---|---|
| D1 | Segment canopies directly, or detect row lines first and then split plants along the row? | 25% of the score is canopy IoU + instance F1 |
| D2 | Which open weights are legal and close enough to 2.5 cm nadir vines? | Licence must be checked and listed |
| D3 | How are empty tiles detected so we do not paint false canopies? | Hidden non-vineyard tiles are penalised by coverage |
| D4 | Geometric inter-rows from axes, or a second segmentation? | Inter-rows must not overlap canopies and must stop at row ends |
| D5 | What is the walk graph: inter-row centre lines plus passage skeleton? | Route is 25% and fails entirely if >2% is off-network |
| D6 | CSV columns | Jury-facing; not specified |
| D7 | Show cadastral parcels on the map and in the CSV, or leave them out of the weekend build? | Not scored. Useful in the pitch. Must not replace blocks, areas, or the route. [Cadastru](cadastru.md) |

## Decision log

| Date | Decision | Reason | Supersedes |
|---|---|---|---|
| 2026-09-25 | Capture challenge context in this file before choosing a model. | Assets and PDFs had no single index. | — |
| 2026-09-25 | Split the single knowledge base into subdomain files under `knowledge/`. | One file mixed rules, measurements, and open decisions. | The monolithic `KNOWLEDGE_BASE.md` body. |
| 2026-09-25 | Remove the root `KNOWLEDGE_BASE.md` and `MEMORY.md`. The index is `knowledge/README.md`. | The two root files repeated the topic files. | Those two files. |
| 2026-09-26 | Follow the weekend sequence in [Plan](plan.md). | The topic files had the rules and no clock. | — |
| 2026-09-26 | Record cadastru as an optional product layer, not a scored label. | A point returns the teren. The start point is in a gap. Parcel outlines are not blocks. | — |
| 2026-09-27 | Rows, inter-rows and blocks are built on the whole map, then cut to tiles (`src/spatial/unify.py`). | One physical row came out as several tile rows with different ids and offsets at tile edges. 97.9% of edge crossings now keep one `row_id`. | `GlobalRowStitcher` in the generator |
| 2026-09-27 | Blocks come from connected rows plus passages, not only `file1.txt`. 54 blocks. | The rules say a road always separates blocks (V08 north and south of its track, V02 either side of its road). | `file1.txt` as the block list |
| 2026-09-27 | Route hop limit 3.5 m (1.72% off-network, 38% of gap targets). | More than 2% off passages and inter-rows scores 0 for the route; 12 m reached 74% but was 5.4% off. | — |
| 2026-09-26 | Waste detector is YOLO26n at `waste/best.pt`. Export a box only if confidence ≥ 0.90. | Trained on UAVVaste. On Sireț3 tiles it marks vines, leaves, and bare soil. Precision matters more than recall because a false box costs the same as a miss. | — |
| 2026-09-27 | Vineyard regions use `weights/block_unet.pt`. | A planting is found from 2.7 m row spacing, then split on passages and on gaps of 5 m. The weight is the teacher-fit checkpoint, not a canopy model. | — |

Related: [Plan](plan.md) · [Research](research.md) · [Scoring](scoring.md) · [Cadastru](cadastru.md)
