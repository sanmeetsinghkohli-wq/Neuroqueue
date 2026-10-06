"""Reproducible NeuroQueue training pipeline.

    python -m ml.train                 # full pipeline
    python -m ml.train --epochs 3      # quick run

Steps: dedupe + split -> fine-tune EfficientNet-B0 -> temperature scaling on
validation -> threshold grid-search on validation -> evaluation on the held-out
test set -> ONNX export -> 20-scan demo set drawn only from test.

Thresholds are tuned on validation only. The test set is touched exactly once,
after every tunable number is frozen.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms

from ml.data import CLASSES, IMG_SIZE, MEAN, STD, TUMOR_CLASSES, build_splits

HERE = Path(__file__).parent
ART = HERE / "artifacts"
NO_TUMOR = CLASSES.index("no_tumor")


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


class MRI(Dataset):
    def __init__(self, rows, tf):
        self.rows, self.tf = rows, tf

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        return self.tf(Image.open(r["path"]).convert("RGB")), CLASSES.index(r["label"])


EVAL_TF = transforms.Compose([
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(MEAN, STD),
])
TRAIN_TF = transforms.Compose([
    transforms.RandomResizedCrop(IMG_SIZE, scale=(0.8, 1.0), ratio=(0.9, 1.1)),
    transforms.RandomHorizontalFlip(),
    transforms.RandomRotation(10),
    transforms.ColorJitter(brightness=0.15, contrast=0.15),
    transforms.ToTensor(),
    transforms.Normalize(MEAN, STD),
])


def build_model() -> nn.Module:
    m = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.IMAGENET1K_V1)
    m.classifier[1] = nn.Linear(m.classifier[1].in_features, len(CLASSES))
    return m


@torch.no_grad()
def collect_logits(model, loader, device):
    model.eval()
    out, ys = [], []
    for x, y in loader:
        out.append(model(x.to(device)).float().cpu())
        ys.append(y)
    return torch.cat(out), torch.cat(ys)


def fit_temperature(logits: torch.Tensor, y: torch.Tensor) -> float:
    log_t = torch.zeros(1, requires_grad=True)
    opt = torch.optim.LBFGS([log_t], lr=0.1, max_iter=200)
    nll = nn.CrossEntropyLoss()

    def closure():
        opt.zero_grad()
        loss = nll(logits / log_t.exp(), y)
        loss.backward()
        return loss

    opt.step(closure)
    return float(log_t.exp().item())


def reliability(probs: np.ndarray, y: np.ndarray, bins: int = 10):
    conf, pred = probs.max(1), probs.argmax(1)
    edges = np.linspace(0, 1, bins + 1)
    rows, ece = [], 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.sum() == 0:
            rows.append({"bin": f"{lo:.1f}-{hi:.1f}", "confidence": None, "accuracy": None, "count": 0})
            continue
        acc, c = float((pred[m] == y[m]).mean()), float(conf[m].mean())
        ece += abs(acc - c) * m.mean()
        rows.append({"bin": f"{lo:.1f}-{hi:.1f}", "confidence": round(c, 4), "accuracy": round(acc, 4), "count": int(m.sum())})
    return rows, float(ece)


def route(probs: np.ndarray, min_conf: float, min_margin: float, routine_conf: float) -> np.ndarray:
    """The verifier used for tuning. 0=URGENT 1=REVIEW 2=ROUTINE.
    Mirrors backend/app/services/verifier.py (minus wait time)."""
    s = np.sort(probs, 1)
    p1, margin, top = s[:, -1], s[:, -1] - s[:, -2], probs.argmax(1)
    tier = np.where(top == NO_TUMOR, 2, 0)
    tier = np.where((top == NO_TUMOR) & (p1 < routine_conf), 1, tier)
    tier = np.where((p1 < min_conf) | (margin < min_margin), 1, tier)
    return tier


def routing_stats(probs: np.ndarray, y: np.ndarray, th: dict) -> dict:
    tier = route(probs, th["min_conf"], th["min_margin"], th["routine_conf"])
    pred, is_tumor = probs.argmax(1), y != NO_TUMOR
    wrong = pred != y
    missed = is_tumor & (tier == 2)  # a true tumor sent to "read last"
    return {
        "review_fraction": float((tier == 1).mean()),
        "tumor_recall_not_routine": float(1 - missed.sum() / max(1, is_tumor.sum())),
        "tumors_sent_to_routine": int(missed.sum()),
        "misclassified": int(wrong.sum()),
        "errors_caught_by_verifier": int((wrong & (tier != 2)).sum()),
        "errors_reaching_routine": int((wrong & (tier == 2)).sum()),
        "tier_counts": {"URGENT": int((tier == 0).sum()), "REVIEW": int((tier == 1).sum()), "ROUTINE": int((tier == 2).sum())},
    }


def tune_thresholds(probs: np.ndarray, y: np.ndarray, review_cap: float) -> tuple[dict, list]:
    """Maximise tumor recall (no true tumor in ROUTINE), then errors caught,
    then the smallest Review load - subject to review_fraction <= review_cap."""
    sweep, best, best_key = [], None, None
    for mc in np.round(np.arange(0.50, 0.991, 0.02), 2):
        for mm in np.round(np.arange(0.0, 0.61, 0.05), 2):
            for rc in (mc, min(0.995, mc + 0.05), min(0.995, mc + 0.10)):
                th = {"min_conf": float(mc), "min_margin": float(mm), "routine_conf": float(round(rc, 3))}
                st = routing_stats(probs, y, th)
                sweep.append({**th, **{k: st[k] for k in ("review_fraction", "tumor_recall_not_routine", "errors_caught_by_verifier", "misclassified")}})
                if st["review_fraction"] > review_cap:
                    continue
                # Among equally safe settings prefer the more conservative (higher) thresholds.
                key = (st["tumor_recall_not_routine"], st["errors_caught_by_verifier"], round(-st["review_fraction"], 2), mc, mm)
                if best_key is None or key > best_key:
                    best, best_key = th, key
    if best is None:
        raise SystemExit("No threshold setting satisfies the review cap; raise --review-cap.")
    return best, sweep


def per_class(cm: np.ndarray) -> dict:
    out = {}
    for i, c in enumerate(CLASSES):
        tp = cm[i, i]
        out[c] = {
            "precision": round(float(tp / max(1, cm[:, i].sum())), 4),
            "recall": round(float(tp / max(1, cm[i].sum())), 4),
            "support": int(cm[i].sum()),
        }
    return out


def softmax(logits: torch.Tensor, t: float) -> np.ndarray:
    return torch.softmax(logits / t, 1).numpy()


def energy(logits: torch.Tensor, t: float) -> np.ndarray:
    return (t * torch.logsumexp(logits / t, 1)).numpy()


def save_plots(rel, ece, cm):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(4.5, 4.5))
    xs = [r["confidence"] for r in rel if r["count"]]
    ys = [r["accuracy"] for r in rel if r["count"]]
    ax.plot([0, 1], [0, 1], "--", color="#94a3b8", label="perfect")
    ax.plot(xs, ys, "o-", color="#0e7490", label=f"model (ECE {ece:.3f})")
    ax.set(xlabel="confidence", ylabel="accuracy", title="Reliability (test, calibrated)", xlim=(0, 1), ylim=(0, 1))
    ax.legend()
    fig.tight_layout()
    fig.savefig(ART / "reliability.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(5, 4.5))
    ax.imshow(cm, cmap="Blues")
    ax.set(xticks=range(4), yticks=range(4), xticklabels=CLASSES, yticklabels=CLASSES, xlabel="predicted", ylabel="true", title="Confusion matrix (test)")
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    for i in range(4):
        for j in range(4):
            ax.text(j, i, int(cm[i, j]), ha="center", va="center", color="white" if cm[i, j] > cm.max() / 2 else "black")
    fig.tight_layout()
    fig.savefig(ART / "confusion_matrix.png", dpi=140)
    plt.close(fig)


def pick_demo(test_rows, probs, y, th, seed, n=20):
    """20 held-out scans: confident tumors, confident no-tumor, at least one that
    lands in REVIEW and at least one the model gets wrong."""
    rng = random.Random(seed)
    tier = route(probs, th["min_conf"], th["min_margin"], th["routine_conf"])
    pred = probs.argmax(1)
    idx = list(range(len(y)))
    rng.shuffle(idx)
    chosen: list[int] = []

    def take(cond, k):
        for i in idx:
            if len([c for c in chosen if cond(c)]) >= k:
                break
            if i not in chosen and cond(i):
                chosen.append(i)

    take(lambda i: pred[i] != y[i], 1)                       # a wrong prediction
    take(lambda i: tier[i] == 1 and pred[i] == y[i], 2)      # uncertain -> REVIEW
    for c in range(3):
        take(lambda i, c=c: tier[i] == 0 and y[i] == c and pred[i] == c, 3)
    take(lambda i: tier[i] == 2 and y[i] == NO_TUMOR, n)     # fill with routine
    chosen = chosen[:n]
    rng.shuffle(chosen)                                      # arrival order is random

    demo = ART / "demo"
    if demo.exists():
        shutil.rmtree(demo)
    demo.mkdir(parents=True)
    manifest = []
    for k, i in enumerate(chosen):
        src = Path(test_rows[i]["path"])
        name = f"demo_{k + 1:02d}{src.suffix.lower()}"
        shutil.copy(src, demo / name)
        manifest.append({
            "file": name, "true_label": CLASSES[y[i]], "predicted": CLASSES[pred[i]],
            "top_prob": round(float(probs[i].max()), 4), "expected_tier": ["URGENT", "REVIEW", "ROUTINE"][tier[i]],
            "model_correct": bool(pred[i] == y[i]),
        })
    (demo / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE / "data" / "raw"))
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--review-cap", type=float, default=0.10, help="max fraction of scans the verifier may send to REVIEW")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    seed_everything(args.seed)
    ART.mkdir(exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    t0 = time.time()

    built = build_splits(Path(args.data), ART, args.seed)
    splits, dd = built["splits"], built["report"]
    print("dedupe:", json.dumps(dd))

    g = torch.Generator().manual_seed(args.seed)
    dl = lambda rows, tf, sh: DataLoader(MRI(rows, tf), batch_size=args.batch, shuffle=sh, num_workers=args.workers,
                                         pin_memory=device == "cuda", generator=g if sh else None, persistent_workers=args.workers > 0)
    train_dl, val_dl, test_dl = dl(splits["train"], TRAIN_TF, True), dl(splits["val"], EVAL_TF, False), dl(splits["test"], EVAL_TF, False)

    model = build_model().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=args.epochs * len(train_dl))
    loss_fn = nn.CrossEntropyLoss()
    scaler = torch.amp.GradScaler(enabled=device == "cuda")

    best_acc, history = 0.0, []
    for ep in range(args.epochs):
        model.train()
        run, n = 0.0, 0
        for x, y in train_dl:
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            opt.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device, enabled=device == "cuda"):
                loss = loss_fn(model(x), y)
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            sched.step()
            run, n = run + loss.item() * len(y), n + len(y)
        vl, vy = collect_logits(model, val_dl, device)
        acc = float((vl.argmax(1) == vy).float().mean())
        history.append({"epoch": ep + 1, "train_loss": round(run / n, 4), "val_acc": round(acc, 4)})
        print(history[-1], flush=True)
        if acc >= best_acc:
            best_acc = acc
            torch.save(model.state_dict(), ART / "model.pt")

    model.load_state_dict(torch.load(ART / "model.pt", map_location=device))

    # ---- calibration + thresholds: VALIDATION ONLY ----
    vl, vy = collect_logits(model, val_dl, device)
    T = fit_temperature(vl, vy)
    vprobs = softmax(vl, T)
    _, ece_val_before = reliability(softmax(vl, 1.0), vy.numpy())
    _, ece_val_after = reliability(vprobs, vy.numpy())
    th, sweep = tune_thresholds(vprobs, vy.numpy(), args.review_cap)
    ood_energy_min = float(np.percentile(energy(vl, T), 0.5))
    thresholds = {
        **th, "temperature": round(T, 4), "max_wait_min": 60, "ood_energy_min": round(ood_energy_min, 4),
        "review_cap": args.review_cap, "tuned_on": "validation", "seed": args.seed,
        "validation": routing_stats(vprobs, vy.numpy(), th),
    }
    (ART / "thresholds.json").write_text(json.dumps(thresholds, indent=2))
    (ART / "threshold_sweep.json").write_text(json.dumps(sweep))
    print("thresholds:", json.dumps(thresholds))

    # ---- evaluation: held-out TEST, touched once ----
    tl, ty = collect_logits(model, test_dl, device)
    tprobs, y = softmax(tl, T), ty.numpy()
    pred = tprobs.argmax(1)
    cm = np.zeros((4, 4), dtype=int)
    for a, b in zip(y, pred):
        cm[a, b] += 1
    rel, ece = reliability(tprobs, y)
    _, ece_uncal = reliability(softmax(tl, 1.0), y)
    is_tumor, pred_tumor = y != NO_TUMOR, pred != NO_TUMOR
    metrics = {
        "dataset": {"name": "Brain Tumor MRI Dataset (Kaggle, M. Nickparvar)", "license": "CC0-1.0", **dd},
        "model": {"backbone": "efficientnet_b0", "input": IMG_SIZE, "epochs": args.epochs, "device": device,
                  "best_val_acc": round(best_acc, 4), "train_seconds": round(time.time() - t0)},
        "test": {
            "n": int(len(y)), "accuracy": round(float((pred == y).mean()), 4),
            "per_class": per_class(cm), "classes": CLASSES, "confusion_matrix": cm.tolist(),
            "tumor_vs_no_tumor": {
                "tumor_recall": round(float((pred_tumor & is_tumor).sum() / max(1, is_tumor.sum())), 4),
                "no_tumor_recall": round(float((~pred_tumor & ~is_tumor).sum() / max(1, (~is_tumor).sum())), 4),
            },
            "calibration": {"temperature": round(T, 4), "ece": round(ece, 4), "ece_uncalibrated": round(ece_uncal, 4),
                            "ece_val_before": round(ece_val_before, 4), "ece_val_after": round(ece_val_after, 4), "reliability": rel},
            "verifier": routing_stats(tprobs, y, th),
        },
        "history": history,
    }
    (ART / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (ART / "test_predictions.json").write_text(json.dumps(
        [{"true": CLASSES[a], "probs": [round(float(p), 5) for p in pr]} for a, pr in zip(y, tprobs)]))
    (ART / "train_config.json").write_text(json.dumps({**vars(args), "classes": CLASSES, "tumor_classes": TUMOR_CLASSES,
                                                       "torch": torch.__version__, "device": device}, indent=2))
    (ART / "labels.json").write_text(json.dumps({"index_to_class": {str(i): c for i, c in enumerate(CLASSES)}}, indent=2))
    save_plots(rel, ece, cm)

    # ---- ONNX export for CPU serving ----
    model.eval().cpu()
    torch.onnx.export(model, torch.zeros(1, 3, IMG_SIZE, IMG_SIZE), str(ART / "model.onnx"), input_names=["input"],
                      output_names=["logits"], dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}}, opset_version=17, dynamo=False)

    manifest = pick_demo(splits["test"], tprobs, y, th, args.seed)
    print("demo:", sum(m["expected_tier"] == "REVIEW" for m in manifest), "review,", sum(not m["model_correct"] for m in manifest), "wrong")
    print("TEST:", json.dumps({k: metrics["test"][k] for k in ("accuracy", "per_class", "tumor_vs_no_tumor", "verifier")}))
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
