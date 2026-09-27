"""Check image and a single map of the identified vineyard zones."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import binary_erosion

_PALETTE = (
    (220, 50, 47),
    (38, 166, 91),
    (41, 128, 220),
    (230, 160, 30),
    (155, 70, 210),
    (20, 175, 180),
    (230, 100, 40),
    (90, 90, 210),
    (180, 200, 40),
    (200, 70, 130),
)


def save_preview(
    path: Path,
    rgb: np.ndarray,
    teacher: np.ndarray,
    labels: np.ndarray,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    left = rgb
    middle = rgb.copy()
    middle[teacher] = (0.35 * middle[teacher] + np.array([40, 200, 60])).astype(np.uint8)
    right = rgb.copy()
    ids = [int(i) for i in np.unique(labels) if i != 0]
    for block_id in ids:
        color = _color(block_id)
        selected = labels == block_id
        right[selected] = (0.45 * right[selected] + 0.55 * color).astype(np.uint8)
    # Downscale wide mosaics so the preview stays easy to open.
    scale = max(1, int(np.ceil(max(rgb.shape[:2]) / 1400)))
    panels = [_shrink(panel, scale) for panel in (left, middle, right)]
    gap = np.zeros((panels[0].shape[0], 8, 3), dtype=np.uint8)
    canvas = np.concatenate([panels[0], gap, panels[1], gap, panels[2]], axis=1)
    Image.fromarray(canvas).save(path)


def _shrink(image: np.ndarray, scale: int) -> np.ndarray:
    if scale == 1:
        return image
    height, width = image.shape[:2]
    height = height - height % scale
    width = width - width % scale
    cropped = image[:height, :width]
    return cropped.reshape(height // scale, scale, width // scale, scale, 3).mean(axis=(1, 3)).astype(np.uint8)


def save_zone_map(path: Path, rgb: np.ndarray, labels: np.ndarray) -> None:
    """One image of the whole mosaic with each vineyard block filled, outlined, and named."""
    path.parent.mkdir(parents=True, exist_ok=True)
    base = rgb.astype(np.float32)
    painted = base.copy()
    ids = [int(i) for i in np.unique(labels) if i != 0]
    for block_id in ids:
        color = np.array(_palette(block_id), dtype=np.float32)
        selected = labels == block_id
        painted[selected] = 0.50 * base[selected] + 0.50 * color
        edge = selected & ~binary_erosion(selected, iterations=2, border_value=0)
        painted[edge] = color
    image = Image.fromarray(np.clip(painted, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    font = _font(max(22, rgb.shape[0] // 90))
    for block_id in ids:
        rows, cols = np.nonzero(labels == block_id)
        cy = int(np.median(rows))
        cx = int(np.median(cols))
        name = f"V{block_id:02d}"
        draw.text(
            (cx, cy),
            name,
            fill=(255, 255, 255),
            font=font,
            anchor="mm",
            stroke_width=3,
            stroke_fill=(0, 0, 0),
        )
    image.save(path)


def _palette(block_id: int) -> tuple[int, int, int]:
    if 1 <= block_id <= len(_PALETTE):
        return _PALETTE[block_id - 1]
    rng = np.random.default_rng(block_id * 17)
    return tuple(int(v) for v in rng.integers(40, 230, size=3))


def _color(block_id: int) -> np.ndarray:
    return np.array(_palette(block_id), dtype=np.float32)


def _font(size: int) -> ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()
