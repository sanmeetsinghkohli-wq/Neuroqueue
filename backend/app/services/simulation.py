"""Queue simulation: first-come-first-served vs NeuroQueue ordering.

Scans arrive over a working day (Poisson arrivals) and one or more radiologists
read at a fixed rate. Each simulated scan is a real held-out test-set prediction,
routed by the real verifier. The outcome is how long truly urgent scans (true
tumor) wait before a radiologist opens them.

These are simulated waiting times under stated assumptions, not clinical outcomes.
"""
from __future__ import annotations

import heapq
import random
import statistics

from app.config import CLASSES, load_json_artifact, load_thresholds
from app.services import verifier

DEFAULTS = {"arrivals_per_hour": 9.0, "read_minutes": 6.0, "urgent_fraction": 0.25, "hours": 8.0, "radiologists": 1,
            "replications": 200, "seed": 7}


def _synthetic_pool(seed: int = 0) -> list[dict]:
    """Stand-in predictions for mock mode, clearly labelled as synthetic in the output."""
    rng, pool = random.Random(seed), []
    for _ in range(400):
        true = rng.choice(CLASSES)
        conf = rng.choice([0.99, 0.97, 0.95, 0.9, 0.7, 0.55])
        pred = true if rng.random() < 0.93 else rng.choice(CLASSES)
        rest = (1 - conf) / 3
        pool.append({"true": true, "probs": [conf if c == pred else rest for c in CLASSES]})
    return pool


def _percentile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _one_day(rng: random.Random, tumor: list[dict], clear: list[dict], p: dict, th: dict, policy: str) -> list[dict]:
    t, arrivals, end = 0.0, [], p["hours"] * 60
    while True:
        t += rng.expovariate(p["arrivals_per_hour"] / 60)
        if t >= end:
            break
        case = rng.choice(tumor) if rng.random() < p["urgent_fraction"] else rng.choice(clear)
        v = verifier.verify(dict(zip(CLASSES, case["probs"])), th)
        arrivals.append({"t": t, "true_tumor": case["true"] != "no_tumor", "tier": v["tier"]})

    servers = [0.0] * int(p["radiologists"])  # time each radiologist becomes free
    heapq.heapify(servers)
    waiting, i, out = [], 0, []
    while i < len(arrivals) or waiting:
        free = heapq.heappop(servers)
        if not waiting and i < len(arrivals) and arrivals[i]["t"] > free:
            free = arrivals[i]["t"]
        while i < len(arrivals) and arrivals[i]["t"] <= free:
            waiting.append(arrivals[i])
            i += 1
        if policy == "fcfs":
            nxt = min(waiting, key=lambda a: a["t"])
        else:  # tier first (with wait-time escalation), then longest wait
            def key(a):
                tier = verifier.URGENT if free - a["t"] > th["max_wait_min"] else a["tier"]
                return (verifier.TIER_ORDER[tier], a["t"])
            nxt = min(waiting, key=key)
        waiting.remove(nxt)
        out.append({**nxt, "wait": free - nxt["t"]})
        heapq.heappush(servers, free + p["read_minutes"])
    return out


def run_simulation(params: dict | None = None) -> dict:
    p = {**DEFAULTS, **{k: v for k, v in (params or {}).items() if v is not None}}
    p["replications"] = int(min(max(p["replications"], 10), 1000))
    th = load_thresholds()
    pool = load_json_artifact("test_predictions.json")
    source = "held-out test-set predictions (ml/artifacts/test_predictions.json)"
    if not pool:
        pool, source = _synthetic_pool(), "SYNTHETIC predictions (no trained artifacts found)"
    tumor = [c for c in pool if c["true"] != "no_tumor"]
    clear = [c for c in pool if c["true"] == "no_tumor"]

    results = {}
    for policy in ("fcfs", "neuroqueue"):
        rng = random.Random(p["seed"])  # same arrivals for both policies
        urgent, everyone, routine, tumor_in_routine, n_tumor = [], [], [], 0, 0
        for _ in range(p["replications"]):
            for a in _one_day(rng, tumor, clear, p, th, policy):
                everyone.append(a["wait"])
                if a["true_tumor"]:
                    urgent.append(a["wait"])
                    n_tumor += 1
                    tumor_in_routine += a["tier"] == verifier.ROUTINE
                else:
                    routine.append(a["wait"])
        results[policy] = {
            "urgent_mean_wait_min": round(statistics.fmean(urgent), 1) if urgent else 0,
            "urgent_p90_wait_min": round(_percentile(urgent, 0.9), 1),
            "no_tumor_mean_wait_min": round(statistics.fmean(routine), 1) if routine else 0,
            "no_tumor_p90_wait_min": round(_percentile(routine, 0.9), 1),
            "all_mean_wait_min": round(statistics.fmean(everyone), 1) if everyone else 0,
            "scans_simulated": len(everyone),
            "true_tumor_scans_tiered_routine": int(tumor_in_routine),
            "true_tumor_scans": n_tumor,
        }
    f, n = results["fcfs"], results["neuroqueue"]
    return {
        "policies": results,
        "chart": [
            {"metric": "Urgent: mean wait", "FCFS": f["urgent_mean_wait_min"], "NeuroQueue": n["urgent_mean_wait_min"]},
            {"metric": "Urgent: 90th pct", "FCFS": f["urgent_p90_wait_min"], "NeuroQueue": n["urgent_p90_wait_min"]},
            {"metric": "No tumor: mean wait", "FCFS": f["no_tumor_mean_wait_min"], "NeuroQueue": n["no_tumor_mean_wait_min"]},
            {"metric": "All scans: mean wait", "FCFS": f["all_mean_wait_min"], "NeuroQueue": n["all_mean_wait_min"]},
        ],
        "assumptions": {
            **p, "prediction_source": source,
            "urgent_definition": "scans whose true label is a tumor class",
            "arrival_process": "Poisson arrivals across the working day; reading continues until the queue is empty",
            "reading": "fixed minutes per scan, every scan is read under both policies",
            "max_wait_min": th["max_wait_min"],
        },
        "disclaimer": "Simulated waiting times under the assumptions listed. Not clinical outcomes.",
    }
