"""Checks for the box line and the tile windows. NMS is torchvision.ops.nms."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import torch
from torchvision.ops import nms

from waste.predict import merge_windows, window_origins
from waste.prepare import yolo_row


class LibraryUseTest(unittest.TestCase):
    def test_coco_box_uses_ultralytics_normalization(self):
        self.assertEqual(yolo_row([10, 20, 30, 40], 100, 200), "0 0.25 0.2 0.3 0.2")

    def test_box_past_the_edge_is_clipped(self):
        self.assertEqual(yolo_row([90, 0, 30, 10], 100, 100), "0 0.95 0.05 0.1 0.1")

    def test_zero_area_box_is_dropped(self):
        self.assertIsNone(yolo_row([0, 0, 0, 10], 100, 100))

    def test_tile_windows_cover_2048(self):
        xs = window_origins(2048, 640, 512)
        self.assertEqual(xs, [0, 512, 1024, 1408])
        covered = torch.zeros(2048, 2048)
        for y in xs:
            for x in xs:
                covered[y : y + 640, x : x + 640] = 1
        self.assertEqual(int(covered.min()), 1)

    def test_merge_uses_torchvision_nms(self):
        found = [(0, 0, 10, 10, 0.4), (1, 1, 11, 11, 0.9), (100, 100, 110, 110, 0.5)]
        kept = merge_windows(found, 0.5)
        scores = [box[4] for box in kept]
        self.assertEqual(scores, [0.9, 0.5])
        reference = nms(
            torch.tensor([box[:4] for box in found], dtype=torch.float32),
            torch.tensor([box[4] for box in found], dtype=torch.float32),
            0.5,
        )
        self.assertEqual([found[i] for i in reference.tolist()], kept)


if __name__ == "__main__":
    unittest.main()
