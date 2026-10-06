"""Dataset indexing, perceptual-hash de-duplication and stratified splits.

Expects a folder-per-class layout anywhere under the data root, e.g.

    ml/data/raw/Training/glioma/*.jpg
    ml/data/raw/Testing/notumor/*.jpg

Every folder whose name maps to one of the four classes is merged, de-duplicated
(so the same slice can never sit in both train and test) and re-split.
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

CLASSES = ["glioma", "meningioma", "pituitary", "no_tumor"]
TUMOR_CLASSES = ["glioma", "meningioma", "pituitary"]
FOLDER_ALIASES = {
    "glioma": "glioma", "glioma_tumor": "glioma",
    "meningioma": "meningioma", "meningioma_tumor": "meningioma",
    "pituitary": "pituitary", "pituitary_tumor": "pituitary",
    "notumor": "no_tumor", "no_tumor": "no_tumor", "no tumor": "no_tumor", "normal": "no_tumor",
}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
IMG_SIZE = 224
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)


def dhash(path: Path, size: int = 8) -> str:
    """64-bit difference hash. Robust to re-encoding and resizing."""
    img = Image.open(path).convert("L").resize((size + 1, size), Image.BILINEAR)
    a = np.asarray(img, dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    return "".join("1" if b else "0" for b in bits)


def index_dataset(root: Path) -> list[dict]:
    items = []
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() not in IMAGE_EXT:
            continue
        label = FOLDER_ALIASES.get(p.parent.name.lower())
        if label:
            items.append({"path": str(p), "label": label})
    return items


def dedupe(items: list[dict]) -> tuple[list[dict], dict]:
    """Keep one image per perceptual hash. Groups whose members carry
    conflicting labels are dropped entirely (label noise)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    unreadable = 0
    for it in items:
        try:
            groups[dhash(Path(it["path"]))].append(it)
        except Exception:
            unreadable += 1
    kept, removed, conflicts = [], 0, 0
    for g in groups.values():
        if len({x["label"] for x in g}) > 1:
            conflicts += len(g)
            continue
        kept.append(g[0])
        removed += len(g) - 1
    report = {
        "total_indexed": len(items),
        "unreadable": unreadable,
        "duplicates_removed": removed,
        "label_conflicts_removed": conflicts,
        "kept": len(kept),
    }
    return kept, report


def stratified_split(items: list[dict], seed: int, val: float = 0.15, test: float = 0.15) -> dict:
    rng = random.Random(seed)
    by_class: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_class[it["label"]].append(it)
    splits = {"train": [], "val": [], "test": []}
    for label in CLASSES:
        rows = sorted(by_class[label], key=lambda r: r["path"])
        rng.shuffle(rows)
        n_test, n_val = round(len(rows) * test), round(len(rows) * val)
        splits["test"] += rows[:n_test]
        splits["val"] += rows[n_test:n_test + n_val]
        splits["train"] += rows[n_test + n_val:]
    return splits


def build_splits(root: Path, out: Path, seed: int = 42) -> dict:
    items = index_dataset(root)
    if not items:
        raise SystemExit(f"No class folders found under {root}. Expected folders named {sorted(set(FOLDER_ALIASES))}.")
    kept, report = dedupe(items)
    splits = stratified_split(kept, seed)
    report["splits"] = {k: {c: sum(1 for r in v if r["label"] == c) for c in CLASSES} for k, v in splits.items()}
    report["seed"] = seed
    out.mkdir(parents=True, exist_ok=True)
    (out / "splits.json").write_text(json.dumps(splits, indent=1))
    (out / "dedupe_report.json").write_text(json.dumps(report, indent=2))
    return {"splits": splits, "report": report}


if __name__ == "__main__":
    here = Path(__file__).parent
    r = build_splits(here / "data" / "raw", here / "artifacts")
    print(json.dumps(r["report"], indent=2))
