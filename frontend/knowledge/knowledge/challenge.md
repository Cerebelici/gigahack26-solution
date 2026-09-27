# Challenge

Part of the [Sireț3 knowledge base](../KNOWLEDGE_BASE.md). Cite [sources](sources.md).

Deeptech GigaHack 2026, 25–27 September 2026, Tekwill, Chișinău. The challenge provider is **Marcaj** (rules, annotation platform, scoring, support). GigaHack hosts the event. Mode is online and offline. Prize is **MDL 30,000** cash for one winning team. [S-DESC]

**Problem.** Vineyard operators need a map of planting, row structure, visible waste, and places that need a walk-through. Aerial imagery alone does not give measured areas or a walking plan. Moldova’s agriculture ministry estimates 2026 vineyard maintenance at MDL 52,000–80,000 per hectare (including depreciation). A hypothetical 20 ha holding is therefore MDL 1.04–1.60 million per year. The stated benefit is less preparation and walking time while still covering the planting, including subsidy-compliance audits. The brief’s example: cutting a route from 6 km to 4.2 km is 30% less distance, or 27 minutes at 4 km/h. [S-DESC]

**Task.** Turn Sireț3 — an open, unannotated RGB orthomosaic from Moldova — into an annotated vineyard map and a walking route that a person can use. The deliverable is a neural-network model, Marcaj annotations, measurements, a route, and a working web interface. Teams may train on other open labelled vineyard data, mix ML with classical vision, then import pre-annotations into Marcaj and correct them there. [S-DESC]

**Deadline.** 15:00 Sunday 27 September 2026, Chișinău time, for both the repository link and the Marcaj project. At that time projects are frozen and organizers export the annotations. [S-DESC] [S-MARCAJ]

**Pitch.** 5 minutes plus 5 minutes of questions. Show the working web interface: map, objects, IDs, measurements, route. A laptop demo is accepted; the deployed URL goes in the README. [S-DESC]

**Support.** Challenge channel in the GigaHack Slack, Marcaj team, 09:00–23:00. Pinned clarifications apply to every team. [S-DESC] [S-MARCAJ]

**Admission (all required, or the entry is not scored for the prize).** [S-DESC]

- A working web interface.
- A published Marcaj project whose jobs are submitted.
- Correct formats and georeferencing.

Tie-break: walking-route score, then canopy segmentation, then jury vote. [S-DESC]

Related: [Submission](submission.md) · [Scoring](scoring.md) · [Marcaj](marcaj.md)
