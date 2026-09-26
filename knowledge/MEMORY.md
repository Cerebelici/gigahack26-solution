# MEMORY.md — Vineyard AI Field Challenge (GigaHack 2026)

> **Single Source of Truth Reference:** For full deep-dive documentation, empirical measurements, research paths (R1–R12), and open decisions (D1–D6), see [KNOWLEDGE_BASE.md](KNOWLEDGE_BASE.md). Facts live in `knowledge/`.

## 1. Project Overview & Objective
- **Problem Statement:** Turn **Sireț3** (unannotated UAV RGB orthomosaic in Moldova, study area ~81.5 ha across 311 GeoTIFF tiles at **0.025 m/px / 2.5 cm/px**) into an annotated vineyard map and an optimized walking inspection/cleanup route.
- **Economic Context:** Vineyard maintenance in Moldova costs 52,000–80,000 MDL/ha (~1.04–1.60M MDL for 20 ha). Optimizing walking route by 30% saves significant field labor/time during area audits for government subsidies.
- **Prize & Deadline:** 30,000 MDL cash prize. **Submission Deadline:** Sunday, 27 September 2026, 15:00 Chișinău time (repository + frozen Marcaj project).

---

## 2. Coordinate System & Georeferencing Standards (CRITICAL)
- **Mandatory CRS:** `EPSG:32635` (`WGS 84 / UTM zone 35N`, unit: metres).
- **Tile Geometry:**
  - Tile dimensions: 2048 × 2048 px.
  - Ground Sample Distance (GSD): **0.025 m/px (2.5 cm/px)**. *(Note: Challenge brief PDF mentioned 3.52 cm/px, but measured GeoTIFF tags confirm resampled tiles are exactly 0.025 m/px).*
  - Ground tile footprint: 51.2 m × 51.2 m.
- **Grid Mapping Formulas:**
  - Tile upper-left corner:
    $$X_{ul} = 628992.0 + c \times 51.2$$
    $$Y_{ul} = 5221222.4 - r \times 51.2$$
  - Pixel corner `(px, py)` to EPSG:32635 map coordinates:
    $$E = X_{ul} + px \times 0.025$$
    $$N = Y_{ul} - py \times 0.025$$
- **Start / Finish Point:**
  - EPSG:32635 coordinates: `(629504.70, 5220250.75)` (WGS84: 47.1230335°N, 28.7073776°E).
  - Location: Dirt-road junction at northwest corner of vineyard block, inside tile `siret3_r018_c010.tif`.
- **Measurement Standards:**
  - All exports strictly in horizontal 2D `EPSG:32635` (no terrain/elevation correction).
  - Row lengths: metres ($m$).
  - Areas: square metres ($m^2$) and hectares ($ha$).

---

## 3. Annotation Schema & Conventions
Pre-annotations must be exported to **CVAT for images 1.1** (`annotations.xml`) inside the Marcaj upload zip.

| Target Class | CVAT XML Tag | Label Name | Attributes & Permitted Values | Definition / Special Rules |
| :--- | :--- | :--- | :--- | :--- |
| **Grapevine Canopy** | `<polygon>` | `vineyard` | `vineyard_id` (string/int) | Top-down canopy of **one** vine plant. Never one polygon over an entire row. Split touching canopies at foliage narrowing or in-row spacing (1.0–1.5 m). Exclude shadows, weeds, and bare soil. |
| **Waste** | `<box>` | `waste` | `vineyard_id` (string/int) | Axis-aligned bounding box around visible litter. Clustered inseparable litter = 1 box. Tubes, stakes, and trellis are NOT waste. If >10m from vineyard, leave `vineyard_id` empty. |
| **Vine-Row Axis** | `<polyline>` | `row` | `vineyard_id`, `row_id`, `row_structure` ∈ {`regular`, `disrupted`, `unassessable`} | Centerline along physical row axis within 0.2 m of vine centers. Gaps do NOT split row into new `row_id`. `disrupted` if gap ≥ 5 m. |
| **Inter-Row Area** | `<polygon>` | `interrow_area` | `vineyard_id`, `interrow_cover` ∈ {`bare_soil`, `vegetation`, `mixed`, `unassessable`} | Ground between adjacent canopy rows within a block. Must not overlap canopy polygons. Stops where rows end. `bare_soil` (<25% veg), `mixed` (25–75% veg), `vegetation` (>75% veg). |
| **Inspection Target** | Derived | `inspection` | `vineyard_id`, `row_id`, `type` | Gaps in rows (≥5m), missing plants, plus waste targets. (Used for routing / application output, NOT uploaded to Marcaj). |

> **CVAT Format Note:** CVAT 1.1 `<annotations><version>1.1</version>`. Uses `points="x1,y1;x2,y2..."` for polygons/polylines, and `<box xtl="..." ytl="..." xbr="..." ybr="...">` for waste rectangles.

---

## 4. Input Assets & Local Locations
- **Local Assets Path:** `/Users/chirill/Downloads/assets_for_participants` (or local `data/` folder):
  - `01_tiles/`: 311 GeoTIFF tiles (`siret3_rNNN_cNNN.tif`), 5 zip parts.
  - `02_route/`: `start.geojson`, `passages.geojson`, `forbidden.geojson`, `study_area.geojson`.
  - `03_docs/`: Challenge description, annotation rules, Marcaj quick start.
  - `04_source/`: Full source orthomosaic (`siret3_source_orthomosaic_EPSG4326.tif`, for training only).
  - `05_examples/`: `siret3_examples_cvat.zip` (`r021_c012` and `r006_c004` worked examples).

---

## 5. Scoring System Breakdown (100 Points Total)

| Weight | Criterion | Scoring Rules & Edge Cases |
| :---: | :--- | :--- |
| **25%** | **Canopy Segmentation** | $0.6 \times \text{IoU} + 0.4 \times F_1$ (one-to-one matched at IoU $\ge 0.5$). False canopies on non-vineyard tiles penalized by $0.5 \times$ area share. |
| **10%** | **Waste Detection** | Bounding box $F_1$ (one-to-one matched at IoU $\ge 0.3$). False positives and misses cost equally. |
| **15%** | **Axes & Attributes** | **8%** row-axis $F_1$ (matched if $\ge 80\%$ within $0.4\text{ m}$ mutual buffer).<br>**5%** `row_structure` & `interrow_cover` mean accuracy & macro-$F_1$.<br>**2%** grouping by `vineyard_id`. |
| **10%** | **Counts & Measurements** | **2%** each for: block count, row count, canopy area, inter-row area, total row length.<br>Formula: $\max(0, 1 - \frac{\text{rel\_err}}{\text{tol}})$. Tolerance: **15%** for counts & areas, **10%** for length. |
| **25%** | **Walking Route** | **15%** target coverage (visited if within $2\text{ m}$).<br>**10%** efficiency $L_{ref} / L$ (awarded only when coverage $\ge 90\%$).<br>**CRITICAL:** Route scores **0** if $>2\%$ of length is off allowed network (passages + inter-rows) or fails to return to start within $5\text{ m}$. |
| **15%** | **Engineering** | Architecture (5), Robustness (4), Scalability (3), Measured Performance (3). Evaluated on reproducible demo and benchmark runtime. |

---

## 6. System Architecture & Technical Pipeline

```
[311 GeoTIFF Tiles (0.025 m/px)]
       │
       ▼
┌────────────────────────────────────────────────────────┐
│ 1. AI Inference & Feature Extraction                   │
│    - Canopy Segmentation (YOLOv8-seg / SAM / classical)│
│    - Waste Detection (YOLOv8-det / RT-DETR)            │
│    - Row Polyline Extraction (Classical CV + PCA/Hough)│
│    - Block Clustering (DBSCAN / Spatial Union / Roads) │
│    - Row & Inter-row Attribute Classifiers             │
└────────────────────────────────────────────────────────┘
       │
       ├──────────────────────────────────────────┐
       ▼                                          ▼
┌───────────────────────────┐         ┌───────────────────────────────┐
│ 2. Marcaj Upload ZIPs     │         │ 3. Spatial Processing Engine  │
│    - annotations.xml      │         │    - Inter-row polygon derive │
│    - images/ (311 tiles)  │         │    - Gap & Inspection targets │
│    - Part 1 to 5 (<90MB)  │         │    - Area / Length metrics    │
│    (Manual team polishing)│         └───────────────────────────────┘
└───────────────────────────┘                         │
                                                      ▼
                                      ┌───────────────────────────────┐
                                      │ 4. Route Optimization (TSP)   │
                                      │    - Network graph on通路     │
                                      │    - Avoid canopies/forbidden │
                                      │    - Start/end: 629504.70,    │
                                      │                 5220250.75    │
                                      └───────────────────────────────┘
                                                      │
                                                      ▼
                                      ┌───────────────────────────────┐
                                      │ 5. Outputs & Web Dashboard    │
                                      │    - route.geojson            │
                                      │    - measurements.csv         │
                                      │    - Interactive Web Map (UI) │
                                      └───────────────────────────────┘
```

### Marcaj Rules
1. **Packaging:** Five upload ZIPs (`team_upload_partX.zip` each $\le 90$ MB), containing `annotations.xml` and original `images/*.tif` unchanged.
2. **One-Shot Import:** Pre-annotations imported **BEFORE** publishing project. Total tile count must equal **311 files**.
3. **Consistent IDs:** Ensure `vineyard_id` and `row_id` are consistent across tile boundaries.

---

## 7. Deliverables Checklist for Submission

- [ ] **`route.geojson`**: Valid GeoJSON `LineString`, EPSG:32635, starts and returns to `(629504.70, 5220250.75)` within 5m, includes `length_m`.
- [ ] **`measurements.csv`**: Structured metrics per block/row (areas in $m^2$ and $ha$, lengths in $m$, unique block/row counts).
- [ ] **`README.md`**:
  - Exact reproduction instructions from raw tiles to final outputs.
  - Pinned dependencies (or Dockerfile).
  - Link/instructions to fetch model weights.
  - Processing runtime for the 311 tiles and benchmark hardware spec.
  - List of any external paid APIs / LLMs used.
  - Live link to the web interface demo.
- [ ] **Codebase**: AI models, spatial post-processing, routing engine, and web interface.
- [ ] **Marcaj Project**: All 63 jobs reviewed, corrected, and submitted before 15:00 Sunday.
- [ ] **Pitch Deck / Demo Plan**: 5-minute presentation + 5-minute Q&A.
- [ ] **Pitch Deck / Demo Plan**: 5-minute presentation + 5-minute Q&A demonstrating interactive map, metrics, ID consistency, and routing.