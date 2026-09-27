# Visual guide

Part of the [Sireț3 knowledge base](README.md). Cite [sources](sources.md).

`Marcaj_Vineyard_AI_Visual_Journey.pdf` is an organizer slide deck (9 pages) titled “Participant workflow”. Every figure is marked illustrative, demo, or mockup. It does not change the annotation rules, the score weights, or the repository file contract. [S-VISUAL]

## Keep

The deck repeats the real pipeline: prepare tiles, pre-annotate, correct in Marcaj, measure, route, web app. The last slide repeats the score split already in [Scoring](scoring.md).

The measurement slide restates the rule already in the challenge description: canopy area is the union of canopy polygons, inter-row area comes from polygons, row length comes from axis polylines, and a bounding box is not an area. The numbers on that slide (block `V001`, 4 × 30 m, 139.2 m² canopy, 225 m² inter-row, 18 × 40 m extent) are a toy block. 225 m² equals three 30 m × 2.5 m rectangles. That 2.5 m is the drawing’s corridor width, not the inter-row measurement method. Inter-row polygons still run from canopy edge to canopy edge. [S-VISUAL] [S-DESC] [S-RULES]

The web mockup is a jury-facing sketch, not a schema: layers for canopies, row axes, inspection targets, and the route; a per-row table of row id, length, and block; a visited-target count. `measurements.csv` still has no official columns. [S-VISUAL] [S-DESC]

The route sketch lists the application output as a polyline, a length, and the ids of visited targets. `route.geojson` is still one `LineString` with `length_m`. Target ids stay in the app. [S-VISUAL] [S-DESC]

## Ignore

| Slide wording | Use this instead |
|---|---|
| `interrow_id` as a passage axis | No such attribute. The label is `interrow_area`, a polygon. Do not upload inter-row centre lines. [S-RULES] |
| `cannot assess`; “flag unreadable areas for exclusion” | The token is `unassessable`. The description calls it the exclusion attribute because it is scored like any other value. Leaving the object out is a miss. [S-DESC] [S-RULES] |
| Deliverable 02 is a final annotation export | Organizers export the Marcaj project at the deadline. A team export is for measurements and the UI. [S-MARCAJ] |
| Step 01: split the orthomosaic and assign tile ids | The 311 tiles are already named. Matching is by those file names. Retiling is allowed only for training. [S-DESC] |
| Start `(1, 3)`, route 110 m or ~247 m, area `A001` | Demo coordinates. The real start is `(629504.70, 5220250.75)`. [S-README] |

Related: [Conflicts](conflicts.md) · [Submission](submission.md) · [Annotation](annotation.md)
