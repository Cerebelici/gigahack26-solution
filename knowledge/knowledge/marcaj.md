# Marcaj

Part of the [Sireț3 knowledge base](../KNOWLEDGE_BASE.md). Cite [sources](sources.md).

Accounts are created from the team list and emailed on Friday evening (“Your Marcaj account”: address, email, generated password). No sign-up. Check spam. Language can be EN / RO / RU. The team project starts in **Draft** with the four labels already configured. Every member can upload, publish, annotate, review, and export. Agree who publishes. [S-MARCAJ] [S-DESC]

## Upload ZIP (CVAT for images 1.1)

```text
team_upload.zip
├── annotations.xml
└── images/
    └── siret3_r021_c012.tif    # supplied file, unchanged, original name
```

- Each ZIP ≤ 90 MB. One ZIP per supplied part is the intended pattern. [S-MARCAJ] [S-RULES]
- JPEG/PNG are rejected: they have no georeferencing. [S-DESC]
- Tiles may be uploaded with no `annotations.xml` if there is no model yet. [S-MARCAJ]
- Pre-annotations import **only before publish**, and only together with the tiles. [S-DESC]
- Until publish, **Remove all** clears the project so a part can be re-imported. [S-MARCAJ]
- After a ZIP imports, read the report. Skipped files or dropped objects mean a renamed tile or a typo in a label or attribute. A note that a class was “added from the label dictionary” is normal when that ZIP has no objects of that label (often `waste`). [S-MARCAJ]
- Upload parts one by one. Wait for each report. The Data card must show **311 files**. Then publish. [S-MARCAJ]
- Publish creates jobs of 5 tiles: **63 jobs** (62 × 5 + one job of 1). [S-MARCAJ]
- After publish: no new pre-annotations, and do not delete, add, or rename tiles, and do not edit labels. [S-DESC] [S-MARCAJ]

## Editor (after publish)

Start labeling assigns the next free job of five tiles. Two people never receive the same job. A job stays with that person until submit. [S-MARCAJ]

| Action | Control |
|---|---|
| Select | Click the shape or the Objects list |
| Attributes | Text for IDs; drop-down for `row_structure` and `interrow_cover` |
| Canopy or inter-row | Polygon `P`, close on the first point |
| Row | Polyline `L`, double-click to finish |
| Waste | Rectangle `R` |
| Edit vertices | Pointer `V` |
| Delete | Delete or bin |
| Undo / redo | Ctrl+Z / Ctrl+Y |
| Zoom | Wheel, or − / + / Fit |
| Hide tags | Tag icon (needed when hundreds of canopies cover the image) |
| Previous / next tile | `D` / `F` (tile saves on step) |
| Pick label | `1`–`9` |
| Empty tile | Tick **No objects in this frame** |
| Submit | On the last tile, Submit (`Enter`) |

Shortcuts do not fire while an attribute field is focused. A job cannot be submitted while any of its tiles has no answer. [S-MARCAJ]

Quick-start screenshot colors in the editor: canopies green, row axes blue, inter-row areas orange. Those are UI colors, not the example-preview colors. [S-MARCAJ]

Submitted jobs show as **In review**. Review is optional. Sending a job back makes it in progress again and **unscored** until resubmit. Near the deadline, fix and resubmit rather than send back. [S-MARCAJ]

**Before 15:00 Sunday:** In progress = 0. Every job is In review or Approved. Nothing sent back and left unsubmitted. Repository link submitted. [S-MARCAJ]

## Three failures that zero out work

1. Publishing before all five parts are in. Missing tiles cannot be pre-annotated afterwards.
2. Jobs left in progress at the deadline. They count as unannotated.
3. Deleting or renaming tiles, editing labels, or deleting the project. Matching is by file name and label name. [S-MARCAJ]

Assign IDs on the whole mosaic **before** cutting annotations per tile. Neighbouring tiles should be corrected by the same person. File names are `siret3_r<row>_c<column>` and the ZIPs are in name order. [S-RULES] [S-MARCAJ]

## Exact `annotations.xml` shape

The example file is CVAT for images 1.1 (`<version>1.1</version>`). Shapes use `source="manual"`, `occluded="0"`, `z_order="0"`. Points are `x,y;x,y` in pixel coordinates. Polygons are not closed by repeating the first point. [S-EX]

Label block to copy (attributes `mutable=False` in the example; the rules’ appendix omits `mutable` and empty defaults — follow the example file, which is a known-good upload): [S-EX] [S-RULES]

```xml
<annotations>
  <version>1.1</version>
  <meta><task><labels>
    <label><name>vineyard</name><type>polygon</type>
      <attributes><attribute><name>vineyard_id</name><input_type>text</input_type></attribute></attributes></label>
    <label><name>waste</name><type>rectangle</type>
      <attributes><attribute><name>vineyard_id</name><input_type>text</input_type></attribute></attributes></label>
    <label><name>row</name><type>polyline</type>
      <attributes>
        <attribute><name>vineyard_id</name><input_type>text</input_type></attribute>
        <attribute><name>row_id</name><input_type>text</input_type></attribute>
        <attribute><name>row_structure</name><input_type>select</input_type>
          <values>regular
disrupted
unassessable</values></attribute>
      </attributes></label>
    <label><name>interrow_area</name><type>polygon</type>
      <attributes>
        <attribute><name>vineyard_id</name><input_type>text</input_type></attribute>
        <attribute><name>interrow_cover</name><input_type>select</input_type>
          <values>bare_soil
vegetation
mixed
unassessable</values></attribute>
      </attributes></label>
  </labels></task></meta>
  <image id="0" name="siret3_r021_c012.tif" width="2048" height="2048">
    <polyline label="row" points="..." occluded="0" z_order="0">
      <attribute name="vineyard_id">V01</attribute>
      <attribute name="row_id">V01-R01</attribute>
      <attribute name="row_structure">regular</attribute>
    </polyline>
    <polygon label="interrow_area" points="..." occluded="0" z_order="0">...</polygon>
    <polygon label="vineyard" points="..." occluded="0" z_order="0">...</polygon>
    <!-- waste: no sample in the example ZIP. CVAT 1.1 rectangles are <box xtl="" ytl="" xbr="" ybr="">.
         Confirm against a Marcaj import before relying on it. -->
  </image>
</annotations>
```

The rules’ own polyline snippet: [S-RULES]

```xml
<polyline label="row" points="112.0,1830.5;1990.4,402.7" occluded="0">
  <attribute name="vineyard_id">V03</attribute>
  <attribute name="row_id">V03-R02</attribute>
  <attribute name="row_structure">disrupted</attribute>
</polyline>
```

Related: [Annotation](annotation.md) · [Conflicts](conflicts.md) · [Spatial](spatial.md) · [Examples](examples.md)
