# Annotation

Part of the [Sireț3 knowledge base](README.md). Cite [sources](sources.md).

Version 1.0, 25 September 2026. The scoring reference follows these rules exactly. Label and attribute names are **lowercase** and must match character for character. [S-RULES]

## Objects

| Label | CVAT type | What it is | Attributes |
|---|---|---|---|
| `vineyard` | polygon | Canopy of **one** grapevine, top-down. Not a row, not a block. | `vineyard_id` |
| `waste` | rectangle (axis-aligned box) | One piece of litter, or one inseparable cluster. The box area is not the waste area. | `vineyard_id` |
| `row` | polyline | Centre line of one vine row, inside this tile. | `vineyard_id`, `row_id`, `row_structure` |
| `interrow_area` | polygon | Ground between the canopies of two neighbouring rows of the same block. | `vineyard_id`, `interrow_cover` |

Allowed values: [S-RULES] [S-DESC]

- `row_structure`: `regular` · `disrupted` · `unassessable`
- `interrow_cover`: `bare_soil` · `vegetation` · `mixed` · `unassessable`

`unassessable` is a real answer. The challenge description calls it the **exclusion attribute**: it marks a row or an inter-row that cannot be read, and it is scored like any other value. It does not mean the object is left out. A missing object is an error. Use it when the row or the ground cannot be made out (deep shadow, overexposure, weeds taller than the vines, canopy closed over the inter-row). [S-DESC] [S-RULES]

For the grower, `row_structure` shows where vines are missing, and `interrow_cover` shows which inter-rows need mowing or tilling. [S-RULES]

ID strings are chosen by the team (`V03`, `north`, `7` are all legal). Scoring compares grouping, not the strings. Recommended pattern: block `V01`, `V02`, … and row `<vineyard_id>-R<nn>` such as `V03-R017`, numbered across the whole block. [S-RULES]

## Golden rules

1. One canopy polygon = one plant. Never one polygon over a whole row or block.
2. Grapevines only. Fruit trees, shrubs, weeds, grass, crops, and vines on fences, arbours, or houses are not `vineyard`.
3. One polyline per physical row **per tile**, from the first vine to the last vine in that tile (or to the tile edge), **through gaps**. A gap does not create a new `row_id`.
4. Canopies and inter-row polygons never overlap. The inter-row runs from canopy edge to canopy edge, not from axis to axis.
5. The same block and the same physical row keep the same `vineyard_id` and `row_id` on every tile.
6. Every tile has an answer: objects, or **No objects in this frame**. Only submitted jobs are scored. [S-RULES]

## Canopies (`vineyard`)

Trace the leaves, within about 10 cm. Exclude bare soil, the plant’s shadow, weeds, and grass. A plant that is entirely invisible in deep shadow is not drawn. A plant cut by the tile edge is traced up to the edge; the rest is a separate polygon on the neighbouring tile. A missing or dead plant is not drawn; the gap shows up in `row_structure`. [S-RULES]

Young vines: each plant is its own polygon, however small. Leaf clumps under about 0.2 m² that are not part of a plant are not annotated. White protective tubes and stakes are part of the planting: neither canopy nor waste. The rules’ example of this case is rows about 2.7 m apart on tilled soil. [S-RULES]

Older vines with touching canopies: split where the foliage visibly narrows. If there is no narrowing, split at the in-row planting distance, measured from trunks, stakes, or gaps in the same row, **typically 1.0–1.5 m**. [S-RULES]

Not a vineyard: orchard crowns (about 2–4 m wide, round, 4–6 m apart). Vines are under about 1 m wide and planted every 1.0–1.5 m along the row. A tree standing inside a vineyard is not a canopy; vines around it are annotated as usual. Garden vineyards on the village edge are annotated only if the vines stand in **at least three rows**. A single vine or an arbour in a yard is not. [S-RULES]

## Waste (`waste`)

A tight axis-aligned box around clearly visible litter, anywhere on the tile (vineyard and surrounding land). Separate items get separate boxes. Pieces that overlap and cannot be told apart get one box. [S-RULES]

| Waste | Not waste |
|---|---|
| bags, plastic sheets and film, bottles, cans, packaging, tyres, construction debris, heaps of rubbish | vine tubes, stakes, trellis posts and wires, irrigation hoses, stones, bare or pale soil, flowering shrubs, pruning residue and cut branches, vehicles and machinery |

`vineyard_id`: the block the object lies in, or the nearest block within 10 m. Farther than that, leave `vineyard_id` empty. When unsure, leave it out: a false box costs as much as a miss. [S-RULES]

The two example tiles contain **zero** waste objects. There is no `<box>` sample in the example XML. [S-EX]

## Row axes (`row`)

One polyline per physical row per tile. Keep the line within **0.2 m** of the vine centres. A straight row may be two points; add points where a row bends. The outermost rows of a block are included. Gaps do not split the row. The same physical row on two tiles is two polylines with one `row_id`. [S-RULES]

Scoring tolerance is looser than the drawing rule: 0.4 m and 80% mutual coverage. [S-DESC] [S-RULES]

`row_structure` describes **this tile only**. The same row may be `regular` on one tile and `disrupted` on the next. [S-RULES]

| Value | When |
|---|---|
| `regular` | No gap of 5 m or more along the row in this tile. |
| `disrupted` | A visible gap of 5 m or more in this tile: several missing or dead vines, or a tree or obstacle in the row. |
| `unassessable` | The row cannot be made out over most of its length in this tile. |

Rows and inter-row areas stop at the edge of the planting. A dirt road is not part of the block. There is no inter-row outside the outermost rows. [S-RULES]

## Inter-row areas (`interrow_area`)

One polygon per inter-row per tile, cut at the tile edge. Long sides follow canopy edges. Short sides stop where the rows end: headland, roads, and exterior land are excluded. If one row is shorter, end at the shorter one. Cut out trees and buildings that stand in the inter-row. This polygon is the walkable ground the route uses, and its area is scored. [S-RULES]

| `interrow_cover` | When |
|---|---|
| `bare_soil` | Vegetation covers less than about a quarter. |
| `mixed` | About a quarter to three quarters (strips of grass/weeds alternating with soil). |
| `vegetation` | Grass or weeds cover more than about three quarters. |
| `unassessable` | Ground cannot be seen. |

Judge each inter-row on its own, inside this tile. [S-RULES]

## Blocks (`vineyard_id`)

A block is a connected planting. Two plantings are the same block when they touch or are separated by **less than 5 m** of non-vineyard ground. **A road or a track always separates blocks.** Every canopy, row, inter-row, and waste within 10 m carries that block’s id. Distinct `vineyard_id` values are the block count. Distinct `row_id` values are the row count. A row redrawn with a new id on the next tile is counted twice. [S-RULES]

## Worked ID example from the rules (not the scored examples)

Block `V03` crosses `siret3_r021_c012` and `siret3_r021_c013`. Three rows, each drawn on both tiles with the same `row_id`. `V03-R02` has a 7 m gap only on the right tile, so that tile’s polyline is `disrupted` and the left tile’s is `regular`. Result: 1 block, 3 rows, 45 canopies (24 + 21). Naming the right tile `R04`–`R06` would wrongly count 6 rows. [S-RULES]

## Do not put these in Marcaj

Inter-row centre lines. Roads, tracks, the supplied passages, forbidden zones, and the start point. Inspection targets (they belong in the application output). Orchards, trees, shrubs, buildings, fences, non-grape crops. Anything in the black area outside the imagery on edge tiles. [S-RULES]

## Attribute mistakes that change the score

| Mistake | Effect |
|---|---|
| Renumber rows from 1 on every tile | One physical row counts as many. |
| New `vineyard_id` for the same block on each tile | Block count and grouping score drop. |
| Empty `row_structure`, `interrow_cover`, or `vineyard_id` | Wrong answer, or the object belongs to no block. |
| `Regular`, `bare soil`, `grass` | Not an allowed value. Use the exact lowercase token. |
| `interrow_cover` on a row, or `row_structure` on an inter-row | Ignored. |

[S-RULES]

## Pixel annotation vs metres

Annotate in pixels in Marcaj. The platform keeps the georeferencing and scoring converts to metres. Tiles are 2048 × 2048 px, 2.5 cm/px, 51.2 m on the ground, EPSG:32635. [S-RULES]

CVAT image coordinates: origin at the top-left, `x` to the right, `y` downward. Confirmed by the example polylines, which run to `x = 2048` and `y = 0` or `y = 2048`. [S-EX]

## Checklist before submitting a job

From the rules, section 8. [S-RULES]

- No polygon covers more than one plant, and no canopy is drawn on a tree or an orchard crown.
- Every row has one polyline per tile, through its gaps, with the same `row_id` on both sides of a tile edge.
- No inter-row polygon overlaps a canopy or runs past the row ends.
- Every object has `vineyard_id`. Every row has `row_id` and `row_structure`. Every inter-row has `interrow_cover`.
- Every tile is annotated or marked **No objects in this frame**, and every job is submitted.

Related: [Scoring](scoring.md) · [Marcaj](marcaj.md) · [Examples](examples.md) · [Spatial](spatial.md)
