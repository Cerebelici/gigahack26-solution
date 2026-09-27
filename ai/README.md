# Geobelic — Vineyard AI Field Challenge (Sireț3)

> **Deeptech GigaHack 2026** · Challenge Provider: **Marcaj** · Tekwill, Chișinău  

---

## 1. Project Overview

Geobelic transforms the **Sireț3** unannotated UAV RGB orthomosaic (~145 ha in Moldova, 311 GeoTIFF tiles in `EPSG:32635` at 0.025 m/px) into:
1. **Marcaj Pre-Annotations:** Compliant **CVAT for images 1.1** XML (`annotations.xml`) and upload-ready ZIP packages containing individual vine canopies, physical straight row axes with continuity classification, and non-overlapping quadrilateral inter-row ground corridors.
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
* **Inference Hardware:** Optimized for Apple Silicon MPS (`mps`), NVIDIA CUDA (`cuda`), or multi-core CPU.

---

## 4. Challenge Generation & Marcaj ZIP Creation

The primary challenge script [`scripts/generate_from_file1.py`](scripts/generate_from_file1.py) reads the vineyard tile mapping from [`file1.txt`](file1.txt), runs high-resolution inference on the 142 vineyard tiles, assigns block IDs (`V01`–`V34`), stitches rows across tile borders, derives quadrilateral interrow corridors, and creates compliant CVAT 1.1 XML and ZIP packages.

### Command to Generate All XMLs and Upload ZIPs:

```bash
.venv/bin/python scripts/generate_from_file1.py \
  --file1 file1.txt \
  --weights weights/best.pt \
  --output annotations_challenge.xml \
  --output-parts-dir exports/parts \
  --create-zips
```

#### What This Command Produces:
1. **Master CVAT 1.1 XML:** [`annotations_challenge.xml`](annotations_challenge.xml) containing all 311 challenge tiles in alphabetical order (142 parsed tiles with full annotations + 169 non-vineyard tiles as empty `<image>` elements).
2. **Per-Part CVAT XMLs (`exports/parts/`):**
   - `annotations_siret3_challenge_tiles_part1of5.xml` (74 tiles)
   - `annotations_siret3_challenge_tiles_part2of5.xml` (71 tiles)
   - `annotations_siret3_challenge_tiles_part3of5.xml` (78 tiles)
   - `annotations_siret3_challenge_tiles_part4of5.xml` (76 tiles)
   - `annotations_siret3_challenge_tiles_part5of5.xml` (12 tiles)
3. **Upload ZIP Archives (`exports/zips/`):**
   Ready to upload directly to Marcaj. Each archive contains `annotations.xml` at the root and image files under `images/`, compressed with Deflate to strictly adhere to Marcaj's **$\le 90\text{ MB}$ limit**:
   - `siret3_challenge_tiles_part1of5.zip` (89.5 MB)
   - `siret3_challenge_tiles_part2of5.zip` (89.5 MB)
   - `siret3_challenge_tiles_part3of5.zip` (88.6 MB)
   - `siret3_challenge_tiles_part4of5.zip` (89.6 MB)
   - `siret3_challenge_tiles_part5of5.zip` (9.9 MB)

---

## 5. Pipeline Details & Quality Guarantees

1. **Canopy Polygon Segmentation (`vineyard`):**
   - Morphological opening ($3 \times 3$ ellipse) severs single-pixel foliage bridges.
   - Distance-transform watershed splits touching older vines at typical in-row planting distances (1.0–1.5 m).
   - Douglas-Peucker simplification (tol=1.0 px) decimation produces a median of 12 vertices matching manual annotations.
   - **IoU Deduplication (NMS):** Spatial grid-indexed suppression eliminates double/triple polygon predictions on the same plant ($\text{IoU} > 0.35$).
   - Area filtering strictly preserves crowns in $[300, 15000]\text{ px}^2$ ($[0.19, 9.38]\text{ m}^2$).
2. **Row Polyline Extraction (`row`):**
   - Fits straight 2-point polylines per physical row.
   - **Planting-Bounded Limits:** Rows terminate at the actual first and last vine in the row (with an agronomic headland margin $\le 1.5\text{ m}$), preventing polylines from extending across roads, cleared fields, or black nodata boundaries.
   - **Continuity Assessment (`row_structure`):** Gaps $\ge 5\text{ m}$ ($200\text{ px}$) trigger `disrupted` and generate inspection targets; otherwise `regular`.
   - **Global Cross-Tile Stitching (`row_id`):** Group collinear segments across adjacent tile boundaries within $0.40\text{ m}$ tolerance, assigning persistent sequential IDs across each block (e.g. `V01-R01`, `V01-R02`...).
3. **Quadrilateral Inter-Row Corridors (`interrow_area`):**
   - Formed between adjacent rows, bounded by straight margins ($12.0\text{ px} = 0.30\text{ m}$) from row axes.
   - Follows rule *"If one row is shorter, end at the shorter one. Short sides stop where the rows end."*
   - **100% 4-point quadrilaterals** strictly bounded within tile and planting borders.
   - **Ground Cover (`interrow_cover`):** Excess Green index ($2G - R - B$) classifies ground as `bare_soil` (<25%), `mixed` (25–75%), or `vegetation` (>75%).

---

## 6. Validation & Testing

Run comprehensive validation on any CVAT XML file:

```bash
# Validate master XML
.venv/bin/python scripts/validate_annotations.py annotations_challenge.xml

# Validate all per-part XMLs
for f in exports/parts/*.xml; do
  .venv/bin/python scripts/validate_annotations.py "$f"
done
```

Run automated unit test suite:

```bash
.venv/bin/python -m unittest discover tests
```

---

## 7. Measured Performance Benchmark

* **Hardware:** Apple M5 Pro (18-core, unified memory, Apple Silicon MPS).
* **Per-Tile Inference & Post-processing:** $\approx 0.73\text{ seconds}$ per $2048 \times 2048$ tile.
* **Full Challenge Execution (142 vineyard tiles):** **$103.8\text{ seconds}$** total wall-clock time.
* **XML Validation Status:** **100% PASS** (0 invalid geometries, 0 self-intersections, 0 duplicate canopies, 100% 2-pt rows, 100% 4-pt quadrilaterals).
* **Offline Execution:** 100% local processing; zero external API or cloud dependencies.

---

## 8. Competition Deliverables Summary

| Deliverable | Location | Description |
| :--- | :--- | :--- |
| **Upload ZIP Archives** | `exports/zips/*.zip` | 5 ready-to-upload ZIPs ($\le 90\text{ MB}$ each) for Marcaj |
| **CVAT XML Master** | `annotations_challenge.xml` | Complete CVAT 1.1 annotations XML for all 311 tiles |
| **Per-Part CVAT XMLs** | `exports/parts/*.xml` | Chunked CVAT 1.1 XMLs per challenge part folder |
| **Trained Weights** | [`weights/best.pt`](weights/best.pt) | Fine-tuned YOLO26L-Seg model checkpoint (60.1 MB) |
| **Tile Mapping** | [`file1.txt`](file1.txt) | Ground-truth vineyard block to tile pairings (33 blocks) |
| **Walking Route** | `route.geojson` | Valid LineString in `EPSG:32635` visiting all gaps & waste |
| **Measurements** | `measurements.csv` | Agronomic lengths and areas by `vineyard_id` / `row_id` |

---

## 9. Licenses & Attribution

* **Sireț3 UAV Imagery:** **CC BY 4.0** — Credit: *3DATA COLLECT / OpenAerialMap*, contributors to the Open Imagery Network.
* **Passages & Restrictions Vector Data:** Contains OpenStreetMap data, © OpenStreetMap contributors, **ODbL**.
* **Code:** MIT License.
