"""Weak vineyard labels from row spacing.

A planting on these tiles is parallel rows about 2.7 m apart (rules: young
rows about 2.7 m, in-row plants 1.0–1.5 m). Orchard crowns are about 4–6 m
apart. The teacher keeps pixels whose luminance or excess-green has a strong
grating near 2.7 m and a weak response at other angles.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter
from scipy.signal import fftconvolve


def row_score(rgb: np.ndarray, valid: np.ndarray, gsd: float) -> tuple[np.ndarray, np.ndarray]:
    """Return (score, peakiness), both float32, zero on invalid pixels."""
    luminance = rgb.astype(np.float32).mean(axis=2)
    red = rgb[:, :, 0].astype(np.float32)
    green = rgb[:, :, 1].astype(np.float32)
    blue = rgb[:, :, 2].astype(np.float32)
    excess_green = 2.0 * green - red - blue

    # Local contrast, not a global scale. Dense dark rows must not hide pale ones.
    angles = np.deg2rad(np.arange(0, 180, 10))
    wavelengths = (2.3, 2.7, 3.1)
    window = max(9, int(round(12.0 / gsd)) | 1)
    per_angle = []
    for channel in (_local_norm(luminance, valid, window), _local_norm(excess_green, valid, window)):
        per_angle.append(_angle_energy(channel, gsd, angles, wavelengths))
    energy = np.maximum(per_angle[0], per_angle[1])

    ordered = np.sort(energy, axis=0)
    peak = ordered[-1]
    second = ordered[-2]
    # One row direction should beat the next angle. Grass and roofs do not.
    peakiness = peak / (second + 1e-6)
    scale = np.percentile(peak[valid], 90) if valid.any() else 1.0
    score = np.clip(peak / (float(scale) + 1e-6), 0, 3).astype(np.float32)
    score[~valid] = 0
    peakiness = peakiness.astype(np.float32)
    peakiness[~valid] = 0
    return score, peakiness


def vine_mask(
    score: np.ndarray,
    peakiness: np.ndarray,
    valid: np.ndarray,
    score_threshold: float = 0.28,
    peakiness_threshold: float = 1.35,
    min_pixels: int = 40,
) -> np.ndarray:
    mask = (score >= score_threshold) & (peakiness >= peakiness_threshold) & valid
    return _drop_specks(mask, min_pixels=min_pixels)


def _local_norm(channel: np.ndarray, valid: np.ndarray, size: int) -> np.ndarray:
    values = channel.astype(np.float32)
    values[~valid] = 0
    mean = uniform_filter(values, size=size)
    second = uniform_filter(values * values, size=size)
    std = np.sqrt(np.maximum(second - mean * mean, 1e-4))
    out = (values - mean) / std
    out[~valid] = 0
    return out.astype(np.float32)


def _angle_energy(
    channel: np.ndarray,
    gsd: float,
    angles: np.ndarray,
    wavelengths: tuple[float, ...],
) -> np.ndarray:
    """Max grating energy over wavelengths, one band per angle. Shape (A,H,W)."""
    bands = []
    for angle in angles:
        best = None
        for wavelength in wavelengths:
            kernel = _grating(wavelength / gsd, float(angle))
            response = fftconvolve(channel, kernel, mode="same")
            energy = uniform_filter(response * response, size=5)
            best = energy if best is None else np.maximum(best, energy)
        bands.append(best.astype(np.float32))
    return np.stack(bands, axis=0)


def _grating(period_px: float, angle: float) -> np.ndarray:
    radius = max(int(np.ceil(period_px * 2.0)), 3)
    axis = np.arange(-radius, radius + 1, dtype=np.float32)
    xx, yy = np.meshgrid(axis, axis)
    across = xx * np.cos(angle) + yy * np.sin(angle)
    window = np.exp(-(xx * xx + yy * yy) / (2.0 * (period_px * 1.15) ** 2))
    kernel = np.cos(2.0 * np.pi * across / period_px) * window
    kernel -= kernel.mean()
    norm = float(np.sqrt((kernel * kernel).sum())) + 1e-6
    return (kernel / norm).astype(np.float32)


def _drop_specks(mask: np.ndarray, min_pixels: int) -> np.ndarray:
    from scipy.ndimage import label

    labels, count = label(mask)
    if count == 0:
        return mask
    counts = np.bincount(labels.ravel())
    keep = counts >= min_pixels
    keep[0] = False
    return keep[labels]
