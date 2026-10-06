"""Check the served model end to end against the dataset's own labels.

    python verify_model.py

Runs every held-out test image through exactly the code path the API uses
(file bytes -> preprocessing -> ONNX model -> class mapping) and compares the
result with the dataset folder label. This proves that preprocessing, class
order and calibration in production match training. Needs ml/data and
ml/artifacts/splits.json (i.e. run it on the machine that trained the model).
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from app.config import ARTIFACTS_DIR, CLASSES, load_json_artifact
from app.services.classifier import OnnxClassifier, verify_class_mapping


def main() -> int:
    verify_class_mapping()
    labels = load_json_artifact("labels.json")
    print("class mapping (model output index -> class):", labels["index_to_class"])
    clf = OnnxClassifier(ARTIFACTS_DIR / "model.onnx")
    print("model:", clf.name, clf.version, "| temperature", clf.T)

    test = json.loads((ARTIFACTS_DIR / "splits.json").read_text())["test"]
    hits, per_class, wrong = 0, Counter(), Counter()
    for row in test:
        pred = clf.predict(Path(row["path"]).read_bytes(), Path(row["path"]).name)
        top = max(pred["probs"], key=pred["probs"].get)
        per_class[row["label"]] += 1
        if top == row["label"]:
            hits += 1
        else:
            wrong[row["label"]] += 1
    acc = hits / len(test)
    print(f"held-out test images: {len(test)}  correct: {hits}  accuracy: {acc:.4f}")
    for c in CLASSES:
        print(f"  {c:11} recall {(per_class[c] - wrong[c]) / per_class[c]:.4f}  ({per_class[c]} images)")
    expected = (load_json_artifact("metrics.json") or {}).get("test", {}).get("accuracy")
    print("accuracy recorded at training time:", expected)
    ok = expected is not None and abs(acc - expected) < 0.005
    print("RESULT:", "served model matches training" if ok else "MISMATCH between served model and training")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
