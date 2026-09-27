# Conflicts

Part of the [Sireț3 knowledge base](README.md). Cite [sources](sources.md).

Recorded so later edits do not “fix” a file to match a sentence, or the reverse, without noticing.

| Topic | Documents say | Files show | Use this |
|---|---|---|---|
| Source GSD | 3.52 cm/px [S-DESC] | ModelPixelScale ≈ 2.40 cm/px; 43.59% valid pixels × that GSD ≈ 145 ha, which matches the stated area [S-GEO] | Trust the GeoTIFF for geometry. Treat 3.52 cm as an unverified statement. |
| Challenge-tile GSD | 0.025 m/px [S-README] [S-RULES] | ModelPixelScale 0.025, 0.025 [S-GEO] | 2.5 cm. Tiles were resampled when reprojected; they are not the source GSD. |
| Upload size | “under 90 MB” / “at most 90 MB” [S-MARCAJ] [S-RULES]; README also says the five ZIPs are “at most 94 MB” [S-README] | Parts 1–4 are 93.2–94.1 × 10⁶ bytes, which is over 90 decimal MB and under 90 MiB. Part 5 is 10.4 × 10⁶ bytes [S-GEO] | If Marcaj rejects a part, split that ZIP. Do not recompress or rename the TIFFs. |
| Canopy label | Prose says “canopies”; the label is `vineyard` [S-DESC] [S-RULES] | Example polygons are `label="vineyard"` [S-EX] | The XML/Marcaj name is `vineyard`. |
| Editor vs preview colors | Quick-start: green / blue / orange [S-MARCAJ]. README previews: green / red / magenta / cyan [S-README] | Two different renders | Colors are not data. |
| Waste XML | Label type `rectangle` [S-RULES] | No `<box>` in the example [S-EX] | Confirm the box tag on a draft import. |
| `measurements.csv` | Required, described in one sentence [S-DESC] | No template | Scoring of the numbers uses Marcaj. The CSV is what the jury reads. Design columns, then record them in the README. |
| Source `UNITTYPE` | — | GDAL metadata says metre [S-GEO] | CRS is EPSG:4326 degrees. |
| “Exclusion” | The description calls `unassessable` the exclusion attribute, and the visual guide says to flag unreadable areas for exclusion [S-DESC] [S-VISUAL] | The rules still require the object, with value `unassessable` [S-RULES] | Draw the object. `unassessable` is scored like any other value. Dropping it is a miss. |
| Visual-guide `interrow_id` | Slide 03 calls an inter-row a passage axis with `interrow_id` [S-VISUAL] | Label `interrow_area` is a polygon. There is no `interrow_id`. Centre lines are not uploaded [S-RULES] | Ignore the slide attribute. |
| Visual-guide export | Slide 09 lists a final annotation export as a deliverable [S-VISUAL] | Organizers export Marcaj at the deadline. Teams do not upload an annotation file for scoring [S-MARCAJ] | Export only for measurements and the UI. |
| Visual-guide tiling | Slide 01 says to split the orthomosaic and assign tile ids [S-VISUAL] | The 311 tiles are already named. Matching is by file name [S-DESC] | Do not rename or recompress. Retile only for training. |
| Description prose `bare soil` | One sentence in the brief writes “bare soil” with a space [S-DESC] | The attribute table and the rules use `bare_soil` [S-DESC] [S-RULES] | The token is `bare_soil`. |

Operational traps already stated by the organizers, repeated because they are easy to miss: publishing early; unsubmitted jobs; renamed tiles; IDs restarted on each tile; annotating Sireț3 outside Marcaj; false canopies on empty tiles; a route that cuts through canopies or forbidden ground; using **Change** on the Labeling card or **Delete** after upload. [S-DESC] [S-MARCAJ] [S-RULES]

Related: [Spatial](spatial.md) · [Marcaj](marcaj.md) · [Submission](submission.md) · [Visual guide](visual-guide.md)
