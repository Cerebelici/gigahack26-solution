# Examples

Part of the [Sireț3 knowledge base](../KNOWLEDGE_BASE.md). Cite [sources](sources.md).

Both tiles are in `05_examples/siret3_examples_cvat.zip` (`annotations.xml` + the two original GeoTIFFs). They are a format template and a visual standard. They are not part of the score. Block ids `V01` and `V02` are local to these files, not a global map of the site. [S-README] [S-EX]

Preview colors (JPG only): row axes red, disrupted rows magenta, canopies green, inter-row areas cyan. [S-README]

| Tile | Block | Rows | Canopies | Inter-rows | Waste |
|---|---|---|---:|---|---:|
| `siret3_r021_c012.tif` | `V01` | 25, all `regular`, ids `V01-R01`…`V01-R25` | 399 polygons, 4–58 points (median 14) | 24, all `bare_soil` (22 quads, 2 with 5 points) | 0 |
| `siret3_r006_c004.tif` | `V02` | 26: 21 `regular`, 5 `disrupted`, ids `V02-R01`…`V02-R26` | 251 polygons, 5–148 points (median 15) | 25: 21 `bare_soil`, 4 `mixed` | 0 |

Every shape in the example XML is `source=manual`, `occluded=0`, `z_order=0`. Every example row polyline has exactly two points. [S-EX]

What the tiles show, in the README’s words: `r021_c012` is young vines on tilled soil, one polygon per plant. `r006_c004` is sparse rows with long gaps, grass strips in the inter-rows, and white vine tubes and stakes that are not waste. [S-README]

**Observation, not a rule.** On `V01`, consecutive axis polylines are parallel and about **2.65 m** apart (perpendicular distance in pixel space × 0.025 m). The rules separately say young-vine rows are about 2.7 m apart. On this tile the rows run diagonally in image space, roughly north-northwest to south-southeast in EPSG:32635. Other blocks on the mosaic may differ. Do not hard-code this azimuth for the whole site. [S-EX] [S-RULES] [S-GEO]

Related: [Annotation](annotation.md) · [Marcaj](marcaj.md) · [Data](data.md)
