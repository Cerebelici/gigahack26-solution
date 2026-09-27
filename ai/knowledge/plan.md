# Plan

Part of the [Sireț3 knowledge base](README.md).

Weekend sequence recorded 2026-09-26. This file is the clock and the split of work. It is not a scoring rule. Label rules, upload mechanics, the route contract, the repository files, and the weights stay in the linked topic files.

## Onboarding

1. Log in at `marcaj.com/login` with the credentials from the email. The team project already exists, and its labels are configured. [Marcaj](marcaj.md)
2. Read the annotation rules and the Marcaj quick-start in `assets/03_docs/`. Download the 5 tile ZIPs (311 GeoTIFFs), plus `start.geojson`, `passages.geojson`, and `forbidden.geojson`. [Data](data.md) [Spatial](spatial.md)
3. Split roles. One working split: 1–2 people on ML (canopies, rows, inter-rows, waste), 1 on GIS/route, 1 on the web interface. On Saturday everyone annotates.

## Friday night → Saturday midday: pre-annotations (ML)

Build a pipeline that turns tiles into vineyard polygons, row polylines, `interrow_area` polygons, waste boxes, and their attributes. The same physical block and the same physical row keep the same `vineyard_id` and `row_id` across tile edges. [Annotation](annotation.md)

Write the output as CVAT for images 1.1: `annotations.xml` plus `images/` containing the original tiles, names unchanged. The ZIP in `assets/05_examples/` is the template. [Marcaj](marcaj.md) [Examples](examples.md)

Dry run first. Upload the example ZIP to the project, check that it imports, then clear it with **Remove all**. A correct example report is 2 frames and 750 objects. [Marcaj](marcaj.md)

Pre-annotations import only once, and only before Publish. Aim to import and publish by Saturday ~14:00. That leaves Saturday afternoon and Sunday morning for manual correction. [Marcaj](marcaj.md)

## In parallel from the start: route and web

Start the route and the web interface at the same time as the model. Develop both on the example annotations.

- **Route.** Build a graph over `interrow_area` plus passage, staying off vineyard and forbidden. It visits the inspection targets and the waste and returns to the start (5 m). All coordinates are EPSG:32635. [Route](route.md) [Spatial](spatial.md)
- **Web.** A map showing the route with its length, canopies and inter-rows, IDs, counts, and row lengths. [Submission](submission.md)

## Saturday: annotate in Marcaj

1. Upload all 5 parts. The Data card shows 311 files. Then Publish.
2. Split the jobs within the team, correct geometry and attributes, and Submit every job. Only submitted jobs are scored.
3. Give neighbouring tiles to the same person. After publishing, leave the tile set and the labels as they are.

[Marcaj](marcaj.md)

## Sunday morning: finish

- Export the corrected annotations from Marcaj and recompute `route.geojson` and `measurements.csv` from that export. [Submission](submission.md)
- Write the README: install and run steps, pinned dependencies, weights link, processing time and hardware for the full 311-tile set, and any paid APIs. [Submission](submission.md)
- Prepare a 5-minute pitch with a live demo of the web interface, plus 5 minutes of questions. [Challenge](challenge.md)
- 15:00 Sunday 27 September 2026: the repository and the Marcaj project are frozen. [Challenge](challenge.md)

## Where the points are

Canopies 25 · route 25 · rows and attributes 15 · measurements 10 · waste 10 · engineering 15. Match rules and the hidden-tile penalty are in [Scoring](scoring.md).

Related: [Solution](solution.md) · [Marcaj](marcaj.md) · [Submission](submission.md)
