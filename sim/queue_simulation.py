"""Queue simulation CLI: first-come-first-served vs NeuroQueue ordering.

    python sim/queue_simulation.py
    python sim/queue_simulation.py --arrivals-per-hour 12 --read-minutes 5 --urgent-fraction 0.3

Writes ml/artifacts/simulation.json (served on the Metrics page) and simulation.png.
Every assumption is written into the output. These are simulated waiting times,
not clinical outcomes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import ARTIFACTS_DIR  # noqa: E402
from app.services.simulation import DEFAULTS, run_simulation  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for key, value in DEFAULTS.items():
        ap.add_argument(f"--{key.replace('_', '-')}", type=type(value), default=value)
    result = run_simulation(vars(ap.parse_args()))

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS_DIR / "simulation.json").write_text(json.dumps(result, indent=2))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        labels = [r["metric"] for r in result["chart"]]
        x = range(len(labels))
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar([i - 0.2 for i in x], [r["FCFS"] for r in result["chart"]], 0.4, label="First come, first served", color="#3987e5")
        ax.bar([i + 0.2 for i in x], [r["NeuroQueue"] for r in result["chart"]], 0.4, label="NeuroQueue order", color="#d95926")
        ax.set_xticks(list(x), labels, fontsize=8)
        ax.set_ylabel("minutes waited before read")
        ax.set_title("Simulated wait (not clinical outcomes)")
        ax.legend()
        fig.tight_layout()
        fig.savefig(ARTIFACTS_DIR / "simulation.png", dpi=140)
    except ImportError:
        pass

    print(json.dumps({"policies": result["policies"], "assumptions": result["assumptions"]}, indent=2))
    print(result["disclaimer"])


if __name__ == "__main__":
    main()
