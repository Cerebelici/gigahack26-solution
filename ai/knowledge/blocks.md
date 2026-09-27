# Vineyard regions

Part of the [Sireț3 knowledge base](README.md). Cite [sources](sources.md).

How the planting regions are found before canopy inference. This is **ours**. It is not a Marcaj label and not a scored geometry. The scored blocks, after canopies exist, are built in [Rows and inter-rows](rows-and-interrows.md).

**Status:** weights chosen, `weights/block_unet.pt`.
**Updated:** 2026-09-27.

## What it detects

A vineyard region is a connected planting, not one vine. The net paints vine pixels on a coarse mosaic. Roads from `passages.geojson` split those pixels. Regions closer than 5 m of non-vineyard ground merge. Each kept region becomes one folder of tiles for the next model.

A region is not a canopy polygon, not a `vineyard_id` from the row unifier, and not a cadastral teren.

## Weights

| | |
|---|---|
| File | `weights/block_unet.pt` |
| Architecture | `BlockUNet` in `src/blocks/model.py` |
| Input | RGB chip, 128×128, coarse mosaic at 0.40 m/px |
| Output | One logit channel, vine vs not |
| Checkpoint keys | `state_dict`, `chip` = 128, `val_dice` |
| Held-out dice | **0.850** `MEASURED` 2026-09-27 from that file |

The dice is agreement with the teacher mask on held-out chips from the same mosaic. It is not a score against Marcaj canopies.

## How the labels are made

There is no hand-drawn region set. `src/blocks/teacher.py` builds a weak mask from the imagery.

1. Build one mosaic of the Sireț3 tiles at 0.40 m/px, with gray-world colour balance (`src/blocks/mosaic.py`).
2. Score luminance and excess green for a grating near **2.7 m**, the young-row spacing in the annotation rules. Wavelengths tried: 2.3, 2.7, 3.1 m. Angles every 10°.
3. Keep a pixel when that direction beats the next angle (peakiness ≥ 1.35) and the score is at least 0.28. Orchard crowns, about 4–6 m apart, do not pass. Specks under 40 pixels are dropped.

## Training

`src/blocks/train.py`, called from `scripts/group_vineyard_blocks.py`.

- Chips 128×128, stride 64, skip a window if less than 45% of it is valid ground.
- 85% of chips train, the rest validate. Seed 0.
- Loss is binary cross-entropy with a positive weight capped at 8.
- Adam, learning rate 0.001, default 6 epochs.
- The saved file is the epoch with the highest validation dice.

A later run with the same tiles and the same seed rewrites the file. To use the committed weights, pass `--skip-train`.

## Inference

```bash
PYTHONPATH=. .venv/bin/python scripts/group_vineyard_blocks.py --skip-train
```

Default weights path is `weights/block_unet.pt`. A pixel is vine when its probability is at least 0.5. Passages are a hard barrier. Territories smaller than 600 m² are dropped. Ids run from the north-west. The script writes `output/vineyard_blocks/V01/` and the rest: `block.xml`, tiles with everything outside the region set to black, plus `full_map.png`.

Code: `src/blocks/`. Tests for the 5 m gap and the passage split: `tests/test_blocks.py`.

Related: [Annotation](annotation.md) · [Rows and inter-rows](rows-and-interrows.md) · [Solution](solution.md)
