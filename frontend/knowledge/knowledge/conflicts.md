# Conflicts

Part of the [Sireț3 knowledge base](../KNOWLEDGE_BASE.md). Cite [sources](sources.md).

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

Operational traps already stated by the organizers, repeated because they are easy to miss: publishing early; unsubmitted jobs; renamed tiles; IDs restarted on each tile; annotating Sireț3 outside Marcaj; false canopies on empty tiles; a route that cuts through canopies or forbidden ground. [S-DESC] [S-MARCAJ] [S-RULES]

Related: [Spatial](spatial.md) · [Marcaj](marcaj.md) · [Submission](submission.md)
