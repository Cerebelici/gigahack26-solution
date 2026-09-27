"""Train BlockUNet on teacher labels cut from the coarse mosaic."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from torch import nn

from src.blocks.model import BlockUNet


def collect_chips(
    rgb: np.ndarray,
    target: np.ndarray,
    valid: np.ndarray,
    chip: int = 128,
    stride: int = 64,
    min_valid: float = 0.45,
) -> tuple[np.ndarray, np.ndarray]:
    images = []
    masks = []
    height, width = valid.shape
    if height < chip or width < chip:
        raise ValueError(f"mosaic {width}x{height} is smaller than chip {chip}")
    ys = _starts(height, chip, stride)
    xs = _starts(width, chip, stride)
    for y in ys:
        for x in xs:
            window = valid[y : y + chip, x : x + chip]
            if float(window.mean()) < min_valid:
                continue
            images.append(rgb[y : y + chip, x : x + chip])
            masks.append(target[y : y + chip, x : x + chip])
    if not images:
        raise ValueError("no training chips: the mosaic has too little valid ground")
    return np.stack(images), np.stack(masks).astype(np.float32)


def train_block_model(
    rgb: np.ndarray,
    target: np.ndarray,
    valid: np.ndarray,
    weights_path: Path,
    epochs: int = 6,
    chip: int = 128,
    stride: int = 64,
    batch_size: int = 8,
    device: str = "cpu",
    seed: int = 0,
) -> dict:
    torch.manual_seed(seed)
    images, masks = collect_chips(rgb, target, valid, chip=chip, stride=stride)
    order = np.random.default_rng(seed).permutation(len(images))
    images, masks = images[order], masks[order]
    split = max(1, int(len(images) * 0.85))
    if split >= len(images):
        split = len(images) - 1 if len(images) > 1 else 1
    train_x, val_x = images[:split], images[split:]
    train_y, val_y = masks[:split], masks[split:]
    print(f"  chips train={len(train_x)} val={len(val_x)} device={device}")

    model = BlockUNet().to(device)
    batch_size = max(1, min(batch_size, len(train_x)))
    positive = float(train_y.mean())
    pos_weight = torch.tensor([min(8.0, (1.0 - positive) / max(positive, 1e-3))], device=device)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

    best_dice = -1.0
    best_state = None
    for epoch in range(1, epochs + 1):
        model.train()
        total = 0.0
        seen = 0
        perm = np.random.default_rng(seed + epoch).permutation(len(train_x))
        for start in range(0, len(perm) - batch_size + 1, batch_size):
            batch = perm[start : start + batch_size]
            logits = model(_batch_tensor(train_x[batch], device))
            loss = loss_fn(logits, _mask_tensor(train_y[batch], device))
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            total += float(loss.item()) * len(batch)
            seen += len(batch)
        dice = _dice(model, val_x, val_y, device) if len(val_x) else float("nan")
        print(f"  epoch {epoch}/{epochs} loss={total / max(seen, 1):.4f} val_dice={dice:.3f}")
        if len(val_x) and dice >= best_dice:
            best_dice = dice
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

    if best_state is None:
        best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": best_state, "chip": chip, "val_dice": best_dice}, weights_path)
    print(f"  weights {weights_path} val_dice={best_dice:.3f}")
    return {"val_dice": best_dice, "chips": int(len(images))}


def load_model(weights_path: Path, device: str) -> tuple[BlockUNet, int]:
    blob = torch.load(weights_path, map_location=device, weights_only=False)
    model = BlockUNet()
    model.load_state_dict(blob["state_dict"])
    model.to(device).eval()
    return model, int(blob.get("chip", 128))


def predict_proba(
    model: BlockUNet,
    rgb: np.ndarray,
    chip: int,
    device: str,
    stride: int | None = None,
    batch_size: int = 8,
) -> np.ndarray:
    stride = chip // 2 if stride is None else stride
    height, width = rgb.shape[:2]
    accumulator = np.zeros((height, width), dtype=np.float32)
    weight = np.zeros((height, width), dtype=np.float32)
    ys = _starts(height, chip, stride)
    xs = _starts(width, chip, stride)
    windows = [(y, x) for y in ys for x in xs]
    model.eval()
    with torch.no_grad():
        for start in range(0, len(windows), batch_size):
            batch = windows[start : start + batch_size]
            crops = np.stack([rgb[y : y + chip, x : x + chip] for y, x in batch])
            logits = model(_batch_tensor(crops, device))
            probs = torch.sigmoid(logits)[:, 0].cpu().numpy()
            for (y, x), prob in zip(batch, probs):
                accumulator[y : y + chip, x : x + chip] += prob
                weight[y : y + chip, x : x + chip] += 1.0
    return accumulator / np.maximum(weight, 1.0)


def pick_device(requested: str) -> str:
    if requested and requested != "auto":
        return requested
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _starts(length: int, chip: int, stride: int) -> list[int]:
    if length < chip:
        raise ValueError(f"length {length} < chip {chip}")
    starts = list(range(0, length - chip + 1, stride))
    last = length - chip
    if starts[-1] != last:
        starts.append(last)
    return starts


def _batch_tensor(images: np.ndarray, device: str) -> torch.Tensor:
    array = images.astype(np.float32) / 255.0
    if array.ndim == 3:
        array = array[None, ...]
    tensor = torch.from_numpy(np.moveaxis(array, -1, 1))
    return tensor.to(device)


def _mask_tensor(masks: np.ndarray, device: str) -> torch.Tensor:
    array = masks.astype(np.float32)
    if array.ndim == 2:
        array = array[None, None]
    elif array.ndim == 3:
        array = array[:, None]
    return torch.from_numpy(array).to(device)


def _dice(model: BlockUNet, images: np.ndarray, masks: np.ndarray, device: str) -> float:
    if len(images) == 0:
        return float("nan")
    model.eval()
    inter = 0.0
    total = 0.0
    with torch.no_grad():
        for start in range(0, len(images), 8):
            logits = model(_batch_tensor(images[start : start + 8], device))
            pred = torch.sigmoid(logits)[:, 0] >= 0.5
            truth = torch.from_numpy(masks[start : start + 8]).to(device) >= 0.5
            inter += float((pred & truth).sum())
            total += float(pred.sum() + truth.sum())
    return (2.0 * inter) / (total + 1e-6)
