# Training stack for ICAERUS canopy masks

Part of the [Sireț3 knowledge base](README.md). Opened 2026-09-26. This is a tool comparison, not a challenge rule.

Question: with only the ICAERUS orthomosaics and vine polygons, which trainer gives the best mask accuracy. Speed is out of scope.

## What ICAERUS actually is

Zenodo record 14605849, file `AI_model.zip` (3.1 GB). Inputs are six RGB orthomosaics (28 May–4 Sep 2024) and 751 GeoPackage cells of 5 m × 5 m for blocks AB01, AB02, TR01. The vine polygons in `multi_vines` are examples of outputs generated from YOLO text. The record describes them as individual vines or vine rows. They are not a ready Roboflow or YOLO folder. https://zenodo.org/records/14605849

## Numbers from the vendors

These are COCO instance-segmentation figures. They are not a vine bake-off, and the eval setups differ (resolution, end-to-end head).

| Model | Who measured it | Mask score | Input |
|---|---|---|---|
| RF-DETR-Seg 2XLarge | RF-DETR docs, COCO AP 50:95 | 49.9 (AP50 73.1) | 768×768 |
| RF-DETR-Seg XLarge | same table | 48.8 | 624×624 |
| YOLO26x-seg | Ultralytics segment docs, mAP mask 50-95, end-to-end | 47.0 | 640×640 |
| YOLO26l-seg | same table | 45.5 | 640×640 |

RF-DETR table: https://github.com/roboflow/rf-detr (segmentation benchmark, fetched 2026-09-26). YOLO26 table: https://docs.ultralytics.com/tasks/segment

Roboflow’s train guide states that for instance segmentation, RF-DETR Seg offers the best accuracy among the architectures they host. https://docs.roboflow.com/train/train.md

Their segmentation post (22 Jan 2026) says RF-DETR-Seg exceeds YOLO26 segmentation on COCO, and that the same checkpoints fine-tune on the Roboflow platform or with the `rfdetr` package. https://blog.roboflow.com/rf-detr-segmentation/

Default train resolutions on the platform match those checkpoints: RF-DETR Seg 2XLarge is 768×768, YOLO-seg sizes they list are 640×640. https://docs.roboflow.com/models/evaluate/training-resolutions-by-model-type.md

## Where to run it

Roboflow Train can launch RF-DETR Segmentation. Semantic segmentation projects cannot use that architecture. Larger sizes can be limited to paid plans; the docs say Medium, Large, and Extra Large detection sizes are paid, and SAM3 training is a paid request. https://docs.roboflow.com/models/train/train-a-model

The same 2XLarge checkpoint trains locally: `RFDETRSeg2XLarge`, dataset in COCO or YOLO segmentation layout. Apple Silicon is a supported device (`device="mps"`). `batch_size="auto"` needs CUDA; on MPS set an integer batch and raise `grad_accum_steps`. Gradient checkpointing is a constructor flag. https://rfdetr.roboflow.com/latest/learn/train/training-parameters/

## Decision

Use Roboflow to turn the orthomosaic polygons into instance chips. Train **RF-DETR Seg 2XLarge** at 768, on the platform if that size is available on the account, otherwise with `rfdetr` on the Mac. YOLO26x-seg is the fallback when 2XLarge does not fit in memory, not the accuracy pick.

Before training, open `multi_vines` and separate polygons about one plant long from polygons that run the length of a row. A 5 m cell is a window, not a plant.
