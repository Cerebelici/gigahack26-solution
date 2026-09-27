# Geobelic — Vineyard AI Field Challenge (Sireț3)

> **Deeptech GigaHack 2026** · Challenge Provider: **Marcaj** · Tekwill, Chișinău  

---

## 1. Project Overview

Geobelic transforms the **Sireț3** unannotated UAV RGB orthomosaic (~145 ha in Moldova, 311 GeoTIFF tiles in `EPSG:32635` at 0.025 m/px) into:
1. **Marcaj Pre-Annotations:** Compliant **CVAT for images 1.1** XML (`annotations.xml`) and upload-ready ZIP packages containing individual vine canopies, row axes with continuity classification, and inter-row ground polygons. Rows, inter-rows and blocks are rebuilt on the whole map, so a row crossing several tiles keeps one `row_id` and its pieces meet at the tile edges.
2. **Inspection & Cleanup Route:** An obstacle-avoiding walking route (`route.geojson`) starting and finishing at the organizer-supplied origin, strictly walking on permitted passages and inter-row ground.
3. **Block & Row Metrics:** Detailed geospatial measurements (`measurements.csv`) in horizontal 2D metres ($m$), square metres ($m^2$), and hectares ($ha$).

---

## 2. Environment Setup & Installation

Ensure you have **Python 3.10+** (Python 3.11–3.14 supported).

```bash
# 1. Clone the repository
git clone https://github.com/Cerebelici/Geobelic.git
cd geobelic

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install pinned dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 3. Model Weights & Architecture

* **Model Architecture:** **YOLO26L-Seg** with native end-to-end `Segment26` prediction head.
* **Pretrained Base:** Ultralytics YOLO26 Large segmentation weights (`yolo26l-seg.pt`).
* **Fine-Tuned Checkpoint:** [`weights/best.pt`](weights/best.pt) (60.1 MB, fine-tuned on the unified aerial vineyard dataset and Sireț3 ground truth examples).
* **Vineyard regions:** [`weights/block_unet.pt`](weights/block_unet.pt), a small UNet that paints plantings on a 0.40 m/px mosaic. Run it with `scripts/group_vineyard_blocks.py --skip-train`. How it is trained is in [`knowledge/blocks.md`](knowledge/blocks.md).
* **Inference Hardware:** Optimized for Apple Silicon MPS (`mps`), NVIDIA CUDA (`cuda`), or multi-core CPU.

---

## 4. Challenge Generation & Marcaj ZIP Creation

The primary challenge script [`scripts/generate_from_file1.py`](scripts/generate_from_file1.py) reads the vineyard tile mapping from [`file1.txt`](file1.txt), runs inference on the 142 vineyard tiles, rebuilds rows, inter-rows and blocks **on the whole map** (see §5), cuts them back to tiles, and writes the Marcaj XML/ZIPs, the whole-map GeoJSON layers, `measurements.csv` and `route.geojson`.

### Command to Generate Everything:

```bash
.venv/bin/python scripts/generate_from_file1.py \
  --file1 file1.txt \
  --weights weights/best.pt \
  --output annotations_challenge.xml \
  --output-parts-dir exports/parts \
  --create-zips
```

Canopy inference is cached in `exports/cache/canopies.json`. Add `--reuse-cache` to re-run only the whole-map post-processing (about 50 s including the route) without the model.

#### What This Command Produces:
1. **Master CVAT 1.1 XML:** [`annotations_challenge.xml`](annotations_challenge.xml) with all 311 challenge tiles (142 vineyard tiles with annotations, the rest as empty `<image>` elements).
2. **Per-Part CVAT XMLs (`exports/parts/`)** and **upload ZIPs (`exports/zips/`)**, one per supplied part, each with `annotations.xml` at the root and the original tiles under `images/`, Deflate-compressed (89.5 / 89.5 / 88.6 / 89.6 / 9.9 MiB).
3. **Whole-map layers for the web app (`exports/unified/`, EPSG:32635):**

   | File | One feature per | Key properties |
   |---|---|---|
   | `blocks.geojson` | block (outline of its rows and inter-rows) | `vineyard_id`, `row_count`, `total_row_length_m`, `canopy_count`, `canopy_area_m2` (union), `interrow_area_m2`, `block_area_m2`, `gap_count` |
   | `rows.geojson` | **physical row, whole length across tiles** | `row_id`, `vineyard_id`, `length_m`, `row_structure`, `gap_count`, `max_gap_m`, `vine_count`, `canopy_count`, `tiles` |
   | `interrows.geojson` | inter-row, whole length across tiles | `interrow_id`, `vineyard_id`, `between_rows`, `interrow_cover`, `area_m2` |
   | `canopies.geojson` | canopy polygon | `vineyard_id`, `tile`, `area_m2` |
   | `targets.geojson` | inspection target (row gap ≥ 5 m) | `target_id`, `vineyard_id`, `row_id`, `gap_m` |

   The Marcaj XML keeps one polyline per row **per tile** (annotation rule 3), so the web app can either read these layers directly or group the XML pieces by `row_id`: both give the same physical rows.
4. **`measurements.csv`**: one line per row (`level=row`), one per block (`level=block`) and a `total` line; lengths in m, areas in m² and ha.
5. **`route.geojson`**: one `LineString` from and back to the start point, with `length_m`, `targets_visited` and `coverage_pct`.

---

## 5. Pipeline Details & Quality Guarantees

1. **Canopy Polygon Segmentation (`vineyard`):**
   - Morphological opening ($3 \times 3$ ellipse) severs single-pixel foliage bridges.
   - Distance-transform watershed splits touching older vines at typical in-row planting distances (1.0–1.5 m).
   - Douglas-Peucker simplification (tol=1.0 px) produces a median of 12 vertices, matching manual annotations.
   - **IoU Deduplication (NMS):** spatial grid-indexed suppression removes double/triple polygons on the same plant ($\text{IoU} > 0.35$).
   - Area filtering keeps crowns in $[300, 15000]\text{ px}^2$ ($[0.19, 9.38]\text{ m}^2$).
2. **Per-tile row segments:** canopy centroids on each tile are clustered into straight row segments (dominant azimuth, gap-tolerant collinear merge). These are only candidates: a tile sees at most 51.2 m of a row.
3. **Whole-map unification ([`src/spatial/unify.py`](src/spatial/unify.py)):** a tile is 51.2 m, rows are up to ~290 m, so one physical row arrives as several segments.
   - **Link across tile edges:** segments on the same or a neighbouring tile (8-neighbourhood) are chained end to end when the shorter segment's vines lie within 0.5 m of the longer segment's vine line extended across the gap (≤ 30 m). Linking uses the vines, not the per-tile line, whose angle is snapped to whole degrees. Each segment end links once, so a chain is one row.
   - **Refit:** each physical row is refitted from all its vines in map space: two points when straight, extra vertices where it bends by more than 0.2 m. The axis runs from the first to the last vine (+0.5 m).
   - **Clean-up:** collinear rows are merged; a second, parallel "row" within 1.3 m of a denser one is dropped (weeds or canopy edges beside a row); rows without a parallel neighbour are dropped (a vineyard needs at least three rows); every detected canopy is re-attached to the row it stands on.
   - **Roads split rows and blocks:** a row is cut where its axis crosses an authorised passage (1–15 m of passage between vines), even if the detector found plants on the track.
   - **Blocks from rows:** rows are one block when they are parallel neighbours ≤ 5.5 m apart with no passage between them; land enclosed by passages is a hard boundary. A block keeps the `file1.txt` id most of its rows carry; a second block claiming the same id (for example the part of V08 south of the track) gets a new id (`V35`, `V36`, ...). Groups of one or two rows join the nearest block, or are dropped as noise.
   - **Numbering:** `row_id` = `<vineyard_id>-R<nn>`, numbered across the block.
   - **Cut back to tiles:** each row is clipped at tile edges. Every piece carries the same `row_id`, and neighbouring pieces meet at the same point on the edge. `row_structure` is judged per tile (`disrupted` when ≥ 5 m of a gap lies in that tile).
4. **Inter-Row Areas (`interrow_area`):** built on the whole map between neighbouring rows of a block, over the stretch where both rows exist ("if one row is shorter, end at the shorter one"), with long sides 0.30 m off each axis. A row facing two shorter rows in line gets one inter-row per neighbour. Clipped at tile edges: most pieces are 4-point, and pieces cut by an edge or following a bent row have more points. **Ground cover (`interrow_cover`):** Excess Green ($2G - R - B$) per tile piece: `bare_soil` (<25%), `mixed` (25–75%), `vegetation` (>75%).
5. **Walking route ([`src/routing/solver.py`](src/routing/solver.py)):** graph over the passage polygons plus the centre line of every whole-map inter-row. Inter-row ends join a passage through the nearest point on its edge. Targets snap only to nodes reachable from the start, so the route never jumps off the network. Tour: nearest neighbour, then time-capped 2-opt. **Coverage vs compliance:** more than 2% of the route off passages and inter-rows scores 0, and inter-rows stop at the row ends while the passages start a few metres further out. The default hop limit (3.5 m) gives 1.72% off-network and reaches 38% of the gap targets. A 12 m limit reaches 74% but walks 5.4% off-network.

---

## 6. Validation & Testing

```bash
# Validate master XML (geometry, duplicates, attribute values)
.venv/bin/python scripts/validate_annotations.py annotations_challenge.xml

# Check that rows crossing a tile edge keep one row_id
.venv/bin/python scripts/audit_boundary.py annotations_challenge.xml

# Unit tests (includes tests/test_unify.py: cross-tile rows, road splits, inter-rows)
.venv/bin/python -m unittest discover tests
```

---

## 7. Measured Performance Benchmark

* **Hardware:** Apple M5 Pro (18-core, unified memory, Apple Silicon MPS).
* **Full run (142 vineyard tiles of 311):** inference 110 s, whole-map unification and outputs about 20 s, route about 26 s, ZIP packaging included: **161 s wall-clock** (measured 2026-09-27).
* **Offline Execution:** 100% local processing; no external API, paid service or LLM.

Measured on this run (2026-09-27):

| | Value |
|---|---|
| Blocks (distinct `vineyard_id` with rows) | 54 |
| Physical rows (distinct `row_id`) | 778, drawn as 1,669 per-tile polylines |
| Rows crossing a tile edge with one `row_id` | 97.9% of 882 edge crossings (`audit_boundary.py`; most remaining flags pair two neighbouring rows) |
| Total row length | 42.9 km |
| Inter-rows | 686 whole-map, 1,537 per-tile polygons |
| Canopies | 23,980 |
| Row-axis F1 on the two organiser example tiles (0.4 m / 80% rule) | 0.90 (`r021_c012`), 0.81 (`r006_c004`) |
| Route | 26.8 km, 1.72% off passages/inter-rows, 0 m in forbidden zones |

---

## 8. Competition Deliverables Summary

| Deliverable | Location | Description |
| :--- | :--- | :--- |
| **Upload ZIP Archives** | `exports/zips/*.zip` | 5 ready-to-upload ZIPs for Marcaj |
| **CVAT XML Master** | `annotations_challenge.xml` | CVAT 1.1 annotations for all 311 tiles |
| **Per-Part CVAT XMLs** | `exports/parts/*.xml` | One CVAT 1.1 XML per supplied part |
| **Whole-map layers** | `exports/unified/*.geojson` | Blocks, full-length rows and inter-rows, canopies, inspection targets (EPSG:32635) for the web app |
| **Trained Weights** | [`weights/best.pt`](weights/best.pt) | Fine-tuned YOLO26L-Seg checkpoint (60.1 MB) |
| **Tile Mapping** | [`file1.txt`](file1.txt) | Vineyard block to tile pairings (33 blocks), used as block names |
| **Walking Route** | `route.geojson` | `LineString` in EPSG:32635 from and back to the start |
| **Measurements** | `measurements.csv` | Lengths and areas by `vineyard_id` / `row_id`, block and total lines |

---

## 9. Licenses & Attribution

* **Sireț3 UAV Imagery:** **CC BY 4.0** — Credit: *3DATA COLLECT / OpenAerialMap*, contributors to the Open Imagery Network.
* **Passages & Restrictions Vector Data:** Contains OpenStreetMap data, © OpenStreetMap contributors, **ODbL**.
* **Code:** MIT License.
