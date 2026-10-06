"""Deterministic triage verifier.

The only input is the trained MRI classifier's calibrated probabilities (plus the
wait time). No language model takes part in classification or tiering.

Rules are evaluated in a fixed order and the first match decides the tier:

  1. waited longer than max_wait_min          -> URGENT   ESCALATED_WAIT
  2. top_prob < min_conf                      -> REVIEW   LOW_CONFIDENCE
  3. margin_top2 < min_margin                 -> REVIEW   CLOSE_CALL
  4. image does not look like training data   -> REVIEW   OUT_OF_DISTRIBUTION
  5. confident tumor class                    -> URGENT   CONFIDENT_TUMOR
  6. confident no_tumor                       -> ROUTINE  CONFIDENT_NO_TUMOR
     (no_tumor below the routine bar          -> REVIEW   ROUTINE_BAR_NOT_MET)

When in doubt the answer is REVIEW, never ROUTINE. ROUTINE means "read last",
never "cleared": no tier removes a scan from the radiologist's worklist.
"""
from __future__ import annotations

URGENT, REVIEW, ROUTINE = "URGENT", "REVIEW", "ROUTINE"
TIER_ORDER = {URGENT: 0, REVIEW: 1, ROUTINE: 2}
TUMOR_CLASSES = ("glioma", "meningioma", "pituitary")
NO_TUMOR = "no_tumor"

REASON_TEXT = {
    "ESCALATED_WAIT": "Waited past the maximum wait time",
    "LOW_CONFIDENCE": "Model confidence is low",
    "CLOSE_CALL": "Close call between two classes",
    "OUT_OF_DISTRIBUTION": "Image looks unlike the training scans",
    "ROUTINE_BAR_NOT_MET": "No-tumor confidence below the routine bar",
    "CONFIDENT_TUMOR": "Confident tumor-class prediction",
    "CONFIDENT_NO_TUMOR": "Confident no-tumor prediction",
}


def rank(probs: dict[str, float]) -> tuple[str, float, float]:
    ordered = sorted(probs.items(), key=lambda kv: (-kv[1], kv[0]))
    (top, p1), (_, p2) = ordered[0], ordered[1]
    return top, float(p1), round(float(p1 - p2), 6)  # rounding keeps exact-threshold margins stable


def verify(probs: dict[str, float], thresholds: dict, *, waited_min: float = 0.0, out_of_distribution: bool = False) -> dict:
    top, p1, margin = rank(probs)
    th = thresholds
    flags: list[str] = []
    if p1 < th["min_conf"]:
        flags.append("LOW_CONFIDENCE")
    if margin < th["min_margin"]:
        flags.append("CLOSE_CALL")
    if out_of_distribution:
        flags.append("OUT_OF_DISTRIBUTION")
    if not flags and top == NO_TUMOR and p1 < th.get("routine_conf", th["min_conf"]):
        flags.append("ROUTINE_BAR_NOT_MET")

    if waited_min > th["max_wait_min"]:
        tier, reason = URGENT, "ESCALATED_WAIT"
    elif flags:
        tier, reason = REVIEW, flags[0]
    elif top in TUMOR_CLASSES:
        tier, reason = URGENT, "CONFIDENT_TUMOR"
    else:
        tier, reason = ROUTINE, "CONFIDENT_NO_TUMOR"

    reasons = [reason] + [f for f in flags if f != reason]
    return {"tier": tier, "reason": reason, "reasons": reasons, "notes": [], "top_class": top,
            "top_prob": round(p1, 4), "margin_top2": round(margin, 4), "provisional": False}


def queue_key(scan: dict) -> tuple:
    """Sort key: tier first, then longest wait first. Untiered scans go last."""
    return (TIER_ORDER.get(scan.get("tier") or "", 3), scan.get("uploaded_at") or "")
