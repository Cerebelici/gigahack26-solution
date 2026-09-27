# Rows and inter-rows

Part of the [Sireț3 knowledge base](README.md). Cite [sources](sources.md).

How our pipeline builds `row` polylines, `interrow_area` polygons and block ids (`vineyard_id`) from the canopy detections. This is **our method**, not a rule. The rules it follows are in [Annotation](annotation.md). The decision is logged in [Solution](solution.md). Code: `src/spatial/unify.py`, called from `scripts/generate_from_file1.py`.

## The problem it solves

A tile is 51.2 m. Rows on Sireț3 run up to about 290 m, so one physical row crosses up to 8 tiles. When each tile is processed on its own:

- each tile fits its own line through the vines. The per-tile angle is snapped to whole degrees, which moves a 51 m line end by up to about 0.45 m. The two pieces of one row do not meet at the tile edge.
- rows get numbered per tile, so one physical row can carry several `row_id` values. The rules count each distinct `row_id` as a row. [S-RULES]

The fix: build rows, inter-rows and blocks **once on the whole map** (EPSG:32635), then cut them back to tiles. Marcaj still needs one polyline per row **per tile**, so the XML keeps per-tile pieces. The pieces share one `row_id` and end at the same point on the tile edge. [S-RULES]

## Pipeline order

| # | Step | Function | What it does |
|---|---|---|---|
| 1 | Canopies | `run_canopy_inference` | YOLO polygons per tile, split and deduplicated. Cached in `exports/cache/canopies.json`. |
| 2 | Tile segments | `extract_tile_segments` | Per tile: canopy centroids → straight row segments (`row_extractor.py`), plus a first block guess from `file1.txt`. Converted to map coordinates. |
| 3 | Link | `link_segments` | Chains segments across tile edges into physical rows. |
| 4 | Refit | `build_physical_rows` | One axis per chain, fitted from all its vines in map space. |
| 5 | Merge | `merge_collinear_rows` | Joins rows that lie on one line (missed links, duplicate segments). |
| 6 | Road split | `split_rows_at_passages` | Cuts a row where it crosses an authorised passage. |
| 7 | Clean-up | `suppress_parallel_duplicates`, `drop_isolated_rows` | Drops weed "rows" beside a real row and lone false rows. |
| 8 | Re-attach | `reattach_canopies` | Gives every detected canopy to the row it stands on, then refits. |
| 9 | Blocks | `regroup_blocks` | Blocks = connected neighbouring rows with no passage between. |
| 10 | Number | `number_rows` | `row_id` = `<vineyard_id>-R<nn>`, across the block. |
| 11 | Inter-rows | `build_interrows` | Whole-map strips between neighbouring rows. |
| 12 | Cut to tiles | `cut_rows_to_tiles`, `cut_polygons_to_tiles` | Per-tile pixel geometry for the XML; per-tile `row_structure` and `interrow_cover`. |

Optional, off by default: `split_at_clearings` (`--split-clearings`), see [Known limits](#known-limits).

## Rows

### 3. Linking across tile edges

Candidates: segments on the same tile or one of its 8 neighbours whose directions differ by at most **8°**.

- The test uses the **vines**, not the per-tile line: the longer segment's vine line (PCA fit) is extended across the gap. The shorter segment's vines must lie on average within **0.5 m** of it, plus 1 cm per metre of gap. Rows are about 2.5–2.7 m apart [S-EX], so the neighbouring row is far outside that.
- Gap along the row between the two vine sets: from −1.5 m (small overlap) to **30 m**. A row keeps its id through gaps. [S-RULES]
- The gap must not cross a passage for more than 2 m.
- Each end of a segment links once, cheapest first (lateral offset + 0.01 × gap). A chain is therefore a simple path along one row.

### 4. Refit

For each chain, all vines go into one fit (`fit_row_polyline`):

- Principal direction of the vines, then a line fit across it. Vines more than max(**0.6 m**, 3 × median residual) off the axis are dropped as outliers (two passes).
- **Straight** rows get 2 points. A row longer than 40 m with at least 8 vines, whose 90th-percentile residual exceeds **0.2 m**, gets knots every **20 m** (local fits), simplified at 5 cm. The rules allow extra points where a row bends. [S-RULES]
- The axis runs from the first vine to the last vine, **+0.5 m** at each end.

### 5–8. Merge, road split, clean-up, re-attach

- **Collinear merge:** two rows are one when the shorter's vines are on average within **0.4 m** of the longer's axis, the gap is ≤ 30 m and no passage is crossed. Angle limit 3°, or 12° when either row is shorter than 15 m (short rows have a noisy direction).
- **Road split:** a road or track always separates blocks. [S-RULES] A row is cut where its axis crosses a passage polygon for **1–15 m** with vines on both sides. Vines on the passage are dropped: the detector finds plants on some tracks. Overlaps at a row end, or long stretches where a buffered road runs along a row, are left alone: the OSM buffers are not exact. [S-GEO]
- **Parallel duplicates:** a parallel row within **1.3 m** of a denser row, with at least half its vines in that band, is weeds or canopy edges beside the real row. The one with fewer vines per metre is dropped.
- **Isolated rows:** a row with no parallel neighbour 0.8–5 m away (≥ 2 m overlap along the row) is dropped. A vineyard needs at least three rows. [S-RULES]
- Rows shorter than **1.5 m** are dropped.
- **Re-attach:** the per-tile clustering hands over only the canopies it put into rows. Every canopy centroid within **0.5 m** of a row axis (or up to 1.5 m past its end) is given to that row, and the row is refitted.

### 9–10. Blocks and numbering

A block is a connected planting. [S-RULES] Rows are joined when:

- they are parallel (≤ 10°), overlap along the row by ≥ 2 m, and are ≤ **5.5 m** apart;
- a line between them, sampled at 5 places along the overlap, does not cross a passage for more than 1 m;
- they lie in the same **road-enclosed parcel**. The holes of the passage polygons are land enclosed by passages; a block never spans two of them.

Groups of one or two rows join the nearest block within 5.5 m, or are dropped as noise.

Names: each block keeps the `file1.txt` id carried by most of its row length. When a second block claims the same id, it gets the next free number (`V35`, `V36`, …). Only the grouping is scored, not the strings. [S-RULES]

`row_id` = `<vineyard_id>-R<nn>`, sorted across the block (east first, or north when the rows run east–west). Three digits when a block has 100 rows or more.

### 12. Per-tile pieces and `row_structure`

- Each row is clipped at tile edges. A piece is kept when it is at least **1 m** long and at least one vine of that row lies on it, so a row passing a tile corner inside a gap is not drawn there.
- `row_structure` is judged **per tile**. [S-RULES] A piece is `disrupted` when at least **5 m** of one gap (consecutive vines ≥ 5 m apart) lies inside that tile; otherwise `regular`.
- Each gap of 5 m or more becomes one inspection target at the gap centre, on the row axis (`targets.geojson`). See [Route](route.md).

## Inter-rows

Built per block on the whole map (`build_interrows`), in a block frame: *s* along the rows, *t* across.

- **Row pitch** of the block: median distance to the nearest overlapping neighbour.
- **Neighbours:** for each row A, the rows B on its +t side that overlap A by ≥ **3 m** along the rows and lie **0.5–1.6 pitches** away.
- **Stretch:** only where both rows exist ("if one row is shorter, end at the shorter one"). [S-RULES] The nearest neighbour claims its stretch first. A row facing two shorter rows in line gets one inter-row per neighbour, with no overlap.
- **Long sides** sit **0.30 m** off each axis toward the other row (at most a quarter of the gap between the rows), standing in for the canopy edge. The sides follow bent rows.
- Polygons under 1 m² are dropped. Id: `<vineyard_id>-I<nnn>`.
- **Cut to tiles:** clipped at the tile edge, pieces under 0.25 m² dropped. Most pieces have 4 points; a piece cut by a tile edge or following a bend has more. The example XML also has 5-point inter-rows. [S-EX]
- **`interrow_cover`** per tile piece, from Excess Green (2G − R − B > 20) inside the polygon: vegetation share < 25% `bare_soil`, 25–75% `mixed`, > 75% `vegetation`. The whole-map inter-row takes the cover with the most area. `unassessable` is not produced.

## Measured results

MEASURED on the full run of 2026-09-27 (`annotations_challenge.xml`, `exports/unified/`):

| | Value |
|---|---|
| Per-tile segments → chains → physical rows | 1,872 → 1,004 → 778 |
| Chains that cross a tile edge | 354 |
| Row pieces in the XML | 1,669 |
| Edge crossings with one `row_id` (`scripts/audit_boundary.py`) | 97.9% of 882. Most remaining flags pair two neighbouring rows. |
| Blocks with rows | 54 (`file1.txt` has 33) |
| Inter-rows | 686 whole-map, 1,537 per-tile pieces |
| Row-axis F1 against the organiser examples (each line ≥ 80% within 0.4 m of the other) | 0.90 on `r021_c012`, 0.81 on `r006_c004` |
| Inter-row IoU against the examples | 0.91 on `r021_c012`, 0.84 on `r006_c004` |
| Axis offset on matched example rows | typically 0.01–0.05 m |

## Known limits

- **Disrupted is over-predicted:** 47% of row pieces are `disrupted`, against 5 of 26 rows in the `r006_c004` reference. The gaps are vines the model misses. The rate was the same before unification.
- **Tracks missing from `passages.geojson` are not detected.** Example: the tree-lined track across V02. `--split-clearings` cuts rows where a gap of 6 m or more lines up with gaps or row ends in both neighbouring rows. It is off by default: in sparse blocks random gaps line up, and on the full run it made 490 cuts and 103 blocks.
- **Blocks without detected rows:** V13 (25 canopies on 5 tiles) and V15 get no rows; their canopies keep the `file1.txt` id. They need manual work in Marcaj.
- **Weeds beside a row** can pull its axis 0.6–0.8 m off (two rows on `r021_c012`). Tightening the outlier limit to 0.35 m made `r006_c004` worse, so it stays at 0.6 m.

## Where the output goes

| Output | What |
|---|---|
| `annotations_challenge.xml`, `exports/parts/`, `exports/zips/` | Per-tile pieces for Marcaj |
| `exports/unified/rows.geojson`, `interrows.geojson`, `blocks.geojson`, `canopies.geojson`, `targets.geojson` | Whole-map objects for the web app, EPSG:32635 |
| `measurements.csv` | Per row, per block and total, from the whole-map objects |
| `route.geojson` | The route walks the whole-map inter-rows plus the passages. See [Route](route.md). |

Re-run only this post-processing (no model, about 1 minute with the route):

```bash
.venv/bin/python scripts/generate_from_file1.py --reuse-cache \
  --output annotations_challenge.xml --output-parts-dir exports/parts --create-zips
```

Tests: `tests/test_unify.py` (rows across a tile edge, pieces meeting at the edge, per-tile gaps, road splits, duplicate suppression, inter-rows).

Related: [Annotation](annotation.md) · [Spatial](spatial.md) · [Route](route.md) · [Solution](solution.md) · [Examples](examples.md)
