"""Tumor-type classifier providers.

OnnxClassifier serves the calibrated EfficientNet-B0 exported by `python -m ml.train`.
MockClassifier is deterministic and needs no model file (mock mode, tests).
Both return the same schema, enforced by tests/test_contracts.py.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import numpy as np
from PIL import Image

from app.config import ARTIFACTS_DIR, CLASSES, get_settings, load_json_artifact, load_thresholds

IMG = 224
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def open_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img.convert("RGB")


def preprocess(img: Image.Image) -> np.ndarray:
    a = np.asarray(img.resize((IMG, IMG), Image.BILINEAR), dtype=np.float32) / 255.0
    return ((a - MEAN) / STD).transpose(2, 0, 1)


def colourfulness(img: Image.Image) -> float:
    """MRI slices are grayscale. A strongly coloured image is not a brain MRI."""
    a = np.asarray(img.resize((64, 64)), dtype=np.float32)
    return float(np.abs(a - a.mean(axis=2, keepdims=True)).mean())


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def _result(probs: np.ndarray, model: str, version: str, energy: float | None, ood: bool, ood_why: str | None) -> dict:
    p = {c: round(float(v), 5) for c, v in zip(CLASSES, probs)}  # index -> class, straight from the model output
    return {"probs": p, "model": model, "model_version": version, "energy": energy, "ood": {"flag": ood, "reason": ood_why}}


def verify_class_mapping() -> None:
    """The served model must use exactly the class order it was trained with."""
    labels = load_json_artifact("labels.json")
    if not labels:
        raise RuntimeError("ml/artifacts/labels.json is missing; cannot verify the model's class mapping.")
    trained = [labels["index_to_class"][str(i)] for i in range(len(labels["index_to_class"]))]
    if trained != CLASSES:
        raise RuntimeError(f"Class mapping mismatch: model was trained with {trained}, API is configured with {CLASSES}.")


class OnnxClassifier:
    name = "efficientnet_b0-onnx"

    def __init__(self, path: Path) -> None:
        import hashlib

        import onnxruntime as ort

        verify_class_mapping()
        self.version = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        self.sess = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        th = load_thresholds()
        self.T = float(th.get("temperature") or 1.0)
        self.energy_min = th.get("ood_energy_min")

    def probs_batch(self, batch: np.ndarray) -> np.ndarray:
        out = []
        for i in range(0, len(batch), 32):
            out.append(self.sess.run(None, {"input": batch[i:i + 32].astype(np.float32)})[0])
        return _softmax(np.concatenate(out) / self.T)

    def predict(self, data: bytes, filename: str = "") -> dict:
        img = open_image(data)
        logits = self.sess.run(None, {"input": preprocess(img)[None]})[0] / self.T
        z = logits[0] - logits[0].max()
        energy = float(self.T * (logits[0].max() + np.log(np.exp(z).sum())))
        ood, why = False, None
        if colourfulness(img) > 12:
            ood, why = True, "Image is strongly coloured; brain MRI slices are grayscale."
        elif self.energy_min is not None and energy < self.energy_min:
            ood, why = True, "Model activation is weaker than on 99.5% of validation scans."
        return _result(_softmax(logits)[0], self.name, self.version, round(energy, 4), ood, why)


class MockClassifier:
    """Deterministic stand-in. A class name in the filename decides the answer;
    'uncertain' gives a close call; anything else is derived from the image hash."""

    name = "mock-classifier"
    version = "mock"

    def _probs(self, data: bytes, filename: str) -> np.ndarray:
        f = filename.lower()
        if "uncertain" in f:
            return np.array([0.52, 0.41, 0.04, 0.03])
        for i, c in enumerate(CLASSES):
            if c in f or c.replace("_", "") in f:
                p = np.full(4, 0.01)
                p[i] = 0.97
                return p
        h = hashlib.sha256(data).digest()
        p = np.full(4, 0.02)
        p[h[0] % 4] = 0.94
        return p

    def probs_batch(self, batch: np.ndarray) -> np.ndarray:
        # Brightness-weighted so the occlusion heatmap still has structure in mock mode.
        m = batch.mean(axis=(1, 2, 3))
        p = np.clip(0.5 + 0.4 * (m - m.min()) / (np.ptp(m) + 1e-6), 0, 1)
        return np.stack([p, (1 - p) / 3, (1 - p) / 3, (1 - p) / 3], axis=1)

    def predict(self, data: bytes, filename: str = "") -> dict:
        img = open_image(data)  # still rejects non-images
        ood = colourfulness(img) > 12
        return _result(self._probs(data, filename), self.name, self.version, None, ood, "Image is strongly coloured." if ood else None)


_instance = None


def get_classifier():
    global _instance
    if _instance is None:
        model = ARTIFACTS_DIR / "model.onnx"
        if get_settings().mock_mode or not model.exists():
            _instance = MockClassifier()
        else:
            _instance = OnnxClassifier(model)
    return _instance


def set_classifier(c) -> None:
    global _instance
    _instance = c
