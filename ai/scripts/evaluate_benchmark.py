"""
Benchmark and evaluate trained segmentation models against Sireț3 ground truth annotations.
Compares Precision, Recall, F1 (both pixel-level and object-level) and canopy area distributions.
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple
import cv2
import numpy as np
from shapely.geometry import Polygon

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shapely.validation import make_valid
from src.pipeline import VineyardPipeline, extract_polygons


def parse_ground_truth(xml_path: str) -> Dict[str, List[Polygon]]:
    """Parse vineyard canopy polygons from CVAT 1.1 annotations XML."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    gt_by_image: Dict[str, List[Polygon]] = {}

    for img in root.findall("image"):
        name = img.get("name")
        polys = []
        for p in img.findall("polygon"):
            if p.get("label") == "vineyard":
                pts_str = p.get("points")
                coords = [
                    [float(c) for c in pt.split(",")]
                    for pt in pts_str.split(";")
                    if "," in pt
                ]
                if len(coords) >= 3:
                    poly = Polygon(coords)
                    if not poly.is_valid:
                        poly = make_valid(poly)
                    for valid_p in extract_polygons(poly):
                        if not valid_p.is_empty and valid_p.area > 0:
                            polys.append(valid_p)
        gt_by_image[name] = polys

    return gt_by_image


def rasterize_polygons(polygons: List[Polygon], height: int = 2048, width: int = 2048) -> np.ndarray:
    """Rasterize a list of polygons into a binary mask uint8(0 or 1)."""
    mask = np.zeros((height, width), dtype=np.uint8)
    for p in polygons:
        try:
            pts = np.array(p.exterior.coords, dtype=np.int32)
            cv2.fillPoly(mask, [pts], 1)
        except Exception:
            continue
    return mask


def compute_pixel_metrics(gt_mask: np.ndarray, pred_mask: np.ndarray) -> Dict[str, float]:
    """Compute pixel-level Precision, Recall, F1, and IoU."""
    tp = np.logical_and(gt_mask == 1, pred_mask == 1).sum()
    fp = np.logical_and(gt_mask == 0, pred_mask == 1).sum()
    fn = np.logical_and(gt_mask == 1, pred_mask == 0).sum()

    precision = float(tp) / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = float(tp) / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    iou = float(tp) / (tp + fp + fn) if (tp + fp + fn) > 0 else 0.0

    return {
        "pixel_precision": precision,
        "pixel_recall": recall,
        "pixel_f1": f1,
        "pixel_iou": iou,
        "tp_pixels": int(tp),
        "fp_pixels": int(fp),
        "fn_pixels": int(fn),
    }


def compute_object_metrics(
    gt_polys: List[Polygon], pred_polys: List[Polygon], iou_thresh: float = 0.5
) -> Dict[str, float]:
    """Compute object-level Precision, Recall, F1 using spatial bounding box + intersection."""
    if not gt_polys and not pred_polys:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "tp": 0, "fp": 0, "fn": 0}
    if not gt_polys:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "tp": 0, "fp": len(pred_polys), "fn": 0}
    if not pred_polys:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "tp": 0, "fp": 0, "fn": len(gt_polys)}

    # Collect candidate pairs
    candidate_pairs = []
    for p_idx, p_poly in enumerate(pred_polys):
        p_bounds = p_poly.bounds
        for g_idx, g_poly in enumerate(gt_polys):
            g_bounds = g_poly.bounds
            # Quick bounding box overlap check
            if (
                p_bounds[2] < g_bounds[0]
                or p_bounds[0] > g_bounds[2]
                or p_bounds[3] < g_bounds[1]
                or p_bounds[1] > g_bounds[3]
            ):
                continue
            try:
                inter_area = p_poly.intersection(g_poly).area
                if inter_area <= 0:
                    continue
                union_area = p_poly.area + g_poly.area - inter_area
                iou = inter_area / union_area if union_area > 0 else 0.0
                if iou >= iou_thresh:
                    candidate_pairs.append((iou, p_idx, g_idx))
            except Exception:
                continue

    # Sorted greedy bipartite matching (highest IoU first)
    candidate_pairs.sort(key=lambda x: x[0], reverse=True)
    matched_pred = set()
    matched_gt = set()
    for iou, p_idx, g_idx in candidate_pairs:
        if p_idx not in matched_pred and g_idx not in matched_gt:
            matched_pred.add(p_idx)
            matched_gt.add(g_idx)

    tp = len(matched_pred)
    fp = len(pred_polys) - tp
    fn = len(gt_polys) - len(matched_gt)

    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2.0 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

    return {
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def area_statistics(polygons: List[Polygon], gsd: float = 0.025) -> Dict[str, float]:
    """Compute distribution statistics for a list of polygons (both in px² and m²)."""
    if not polygons:
        return {
            "count": 0,
            "min_px": 0.0,
            "q25_px": 0.0,
            "median_px": 0.0,
            "mean_px": 0.0,
            "q75_px": 0.0,
            "max_px": 0.0,
            "total_px": 0.0,
            "total_m2": 0.0,
            "mean_m2": 0.0,
        }
    areas = np.array([p.area for p in polygons])
    px_to_m2 = gsd * gsd
    return {
        "count": len(areas),
        "min_px": float(np.min(areas)),
        "q25_px": float(np.percentile(areas, 25)),
        "median_px": float(np.median(areas)),
        "mean_px": float(np.mean(areas)),
        "q75_px": float(np.percentile(areas, 75)),
        "max_px": float(np.max(areas)),
        "total_px": float(np.sum(areas)),
        "total_m2": float(np.sum(areas) * px_to_m2),
        "mean_m2": float(np.mean(areas) * px_to_m2),
    }


def evaluate(
    weights_path: str,
    gt_xml_path: str = "assets/05_examples/siret3_examples_cvat/annotations.xml",
    images_dir: str = "assets/05_examples/siret3_examples_cvat/images",
    conf: float = 0.28,
    imgsz: int = 2048,
):
    print("=" * 75)
    print("Benchmark & Evaluation on Sireț3 Ground Truth Tiles")
    print(f"Weights:     {weights_path}")
    print(f"Ground Truth:{gt_xml_path}")
    print(f"Images Dir:  {images_dir}")
    print(f"Confidence:  {conf} | ImgSz: {imgsz}")
    print("=" * 75)

    gt_by_image = parse_ground_truth(gt_xml_path)
    pipeline = VineyardPipeline(model_weights_path=weights_path)

    images_path = Path(images_dir)
    tile_files = sorted(
        [f for f in images_path.iterdir() if f.suffix.lower() in [".tif", ".tiff", ".jpg", ".jpeg", ".png"]]
    )

    all_gt_masks = []
    all_pred_masks = []
    total_gt_polys = 0
    total_pred_polys = 0

    results_summary = []

    for tile_file in tile_files:
        tile_name = tile_file.name
        gt_polys = gt_by_image.get(tile_name, [])
        tile_ann, _ = pipeline.process_tile(str(tile_file), confidence=conf, imgsz=imgsz)
        pred_polys = [Polygon(c.points) for c in tile_ann.canopies if len(c.points) >= 3]

        total_gt_polys += len(gt_polys)
        total_pred_polys += len(pred_polys)

        gt_mask = rasterize_polygons(gt_polys)
        pred_mask = rasterize_polygons(pred_polys)
        all_gt_masks.append(gt_mask)
        all_pred_masks.append(pred_mask)

        pixel_metrics = compute_pixel_metrics(gt_mask, pred_mask)
        obj_m50 = compute_object_metrics(gt_polys, pred_polys, iou_thresh=0.50)
        obj_m25 = compute_object_metrics(gt_polys, pred_polys, iou_thresh=0.25)
        gt_stats = area_statistics(gt_polys)
        pred_stats = area_statistics(pred_polys)

        results_summary.append({
            "tile": tile_name,
            "gt_count": len(gt_polys),
            "pred_count": len(pred_polys),
            "pixel_metrics": pixel_metrics,
            "obj_m50": obj_m50,
            "obj_m25": obj_m25,
            "gt_stats": gt_stats,
            "pred_stats": pred_stats,
        })

        print(f"\n--- Tile: {tile_name} ---")
        print(f"Canopy Count: GT={len(gt_polys)} | Pred={len(pred_polys)}")
        print(
            f"Pixel Metrics:  Prec={pixel_metrics['pixel_precision']*100:.2f}% | "
            f"Rec={pixel_metrics['pixel_recall']*100:.2f}% | "
            f"F1={pixel_metrics['pixel_f1']*100:.2f}% | "
            f"IoU={pixel_metrics['pixel_iou']*100:.2f}%"
        )
        print(
            f"Object (IoU@0.25): Prec={obj_m25['precision']*100:.2f}% | "
            f"Rec={obj_m25['recall']*100:.2f}% | "
            f"F1={obj_m25['f1']*100:.2f}%"
        )
        print(
            f"Object (IoU@0.50): Prec={obj_m50['precision']*100:.2f}% | "
            f"Rec={obj_m50['recall']*100:.2f}% | "
            f"F1={obj_m50['f1']*100:.2f}%"
        )
        print("Canopy Area (px²):")
        print(
            f"  GT:   median={gt_stats['median_px']:.1f}, mean={gt_stats['mean_px']:.1f}, "
            f"min={gt_stats['min_px']:.1f}, max={gt_stats['max_px']:.1f}, total={gt_stats['total_px']:.0f} ({gt_stats['total_m2']:.1f} m²)"
        )
        print(
            f"  Pred: median={pred_stats['median_px']:.1f}, mean={pred_stats['mean_px']:.1f}, "
            f"min={pred_stats['min_px']:.1f}, max={pred_stats['max_px']:.1f}, total={pred_stats['total_px']:.0f} ({pred_stats['total_m2']:.1f} m²)"
        )

    # Combined aggregate metrics
    cat_gt = np.concatenate(all_gt_masks, axis=0)
    cat_pred = np.concatenate(all_pred_masks, axis=0)
    overall_pixel = compute_pixel_metrics(cat_gt, cat_pred)

    print("\n" + "=" * 75)
    print("OVERALL COMBINED GROUND TRUTH BENCHMARK")
    print(f"Total Tiles:        {len(tile_files)}")
    print(f"Total GT Canopies:  {total_gt_polys}")
    print(f"Total Pred Canopies:{total_pred_polys}")
    print(f"Pixel Precision:    {overall_pixel['pixel_precision']*100:.2f}%")
    print(f"Pixel Recall:       {overall_pixel['pixel_recall']*100:.2f}%")
    print(f"Pixel F1-Score:     {overall_pixel['pixel_f1']*100:.2f}%")
    print(f"Pixel IoU:          {overall_pixel['pixel_iou']*100:.2f}%")
    print("=" * 75)

    return results_summary, overall_pixel


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate YOLO on Sireț3 ground truth.")
    parser.add_argument("--weights", type=str, default="weights/best.pt")
    parser.add_argument("--gt-xml", type=str, default="assets/05_examples/siret3_examples_cvat/annotations.xml")
    parser.add_argument("--images-dir", type=str, default="assets/05_examples/siret3_examples_cvat/images")
    parser.add_argument("--conf", type=float, default=0.28)
    parser.add_argument("--imgsz", type=int, default=2048)
    args = parser.parse_args()

    evaluate(
        weights_path=args.weights,
        gt_xml_path=args.gt_xml,
        images_dir=args.images_dir,
        conf=args.conf,
        imgsz=args.imgsz,
    )
