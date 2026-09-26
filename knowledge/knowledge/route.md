# Route

Part of the [Sireț3 knowledge base](../KNOWLEDGE_BASE.md). Cite [sources](sources.md).

Inspection targets and the walking route are application outputs. They are not Marcaj labels. [S-RULES]

Targets are locations that need inspection (visible row gaps, possibly missing planting) and detected waste. Each inspection location needs an id, coordinates, and links to `vineyard_id` / `row_id`. [S-DESC]

The route: [S-DESC] [S-RULES]

- Starts and ends at the supplied point (5 m).
- Walks on inter-row polygons and authorised passages.
- Does not cross canopies, fences, or forbidden zones.
- Visits every reachable target.
- Prefers a shorter length.
- A hidden target counts as visited within 2 m.
- Efficiency is scored only once coverage is at least 90%.
- More than 2% of length off the allowed surfaces scores 0 for the whole route criterion.

Roads separate blocks, so the passage polygons are the intended way to move between blocks and along headlands. Inter-row polygons stop at the row ends, so the route has to leave them through a passage to reach the next block or to return to the start. [S-RULES] [S-DESC]

Related: [Scoring](scoring.md) · [Spatial](spatial.md) · [Submission](submission.md) · [Annotation](annotation.md)
