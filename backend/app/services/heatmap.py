"""Occlusion-sensitivity heatmap.

Slide a neutral patch across the image and record how far the predicted-class
probability drops at each position. Large drops mark the regions the classifier
relied on. This shows model attention, not tumor boundaries.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageFilter

from app.config import CLASSES
from app.services.classifier import IMG, open_image, preprocess


def occlusion_map(classifier, data: bytes, class_name: str, patch: int = 40, stride: int = 23) -> np.ndarray:
    base = preprocess(open_image(data))
    k = CLASSES.index(class_name)
    positions = [(y, x) for y in range(0, IMG - patch + 1, stride) for x in range(0, IMG - patch + 1, stride)]
    batch = np.repeat(base[None], len(positions) + 1, axis=0)
    for i, (y, x) in enumerate(positions, start=1):
        batch[i, :, y:y + patch, x:x + patch] = 0.0  # 0 == dataset mean after normalisation
    probs = classifier.probs_batch(batch)[:, k]
    heat, count = np.zeros((IMG, IMG), np.float32), np.zeros((IMG, IMG), np.float32)
    for (y, x), p in zip(positions, probs[1:]):
        heat[y:y + patch, x:x + patch] += max(0.0, float(probs[0] - p))
        count[y:y + patch, x:x + patch] += 1
    heat /= np.maximum(count, 1)
    return heat / heat.max() if heat.max() > 1e-6 else heat


def _colour(h: np.ndarray) -> np.ndarray:
    """Transparent -> amber -> red ramp."""
    r = np.clip(1.6 * h + 0.35, 0, 1)
    g = np.clip(1.1 - 1.3 * h, 0, 1) * 0.75
    b = np.clip(0.25 - h, 0, 1) * 0.3
    return np.stack([r, g, b], axis=2)


def overlay_png(classifier, data: bytes, class_name: str) -> bytes:
    heat = occlusion_map(classifier, data, class_name)
    img = open_image(data)
    w, h = img.size
    scale = 512 / max(w, h)
    img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.BILINEAR)
    hm_img = Image.fromarray((heat * 255).astype(np.uint8)).resize(img.size, Image.BICUBIC).filter(ImageFilter.GaussianBlur(max(img.size) / 28))
    hm = np.asarray(hm_img, dtype=np.float32) / 255.0
    hm = hm / hm.max() if hm.max() > 1e-6 else hm
    alpha = (np.clip(hm - 0.15, 0, 1) * 0.75)[..., None]
    out = np.asarray(img, dtype=np.float32) / 255.0 * (1 - alpha) + _colour(hm) * alpha
    buf = io.BytesIO()
    Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8)).save(buf, format="PNG", optimize=True)
    return buf.getvalue()
