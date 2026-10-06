from app.services import verifier
from app.services.verifier import REVIEW, ROUTINE, URGENT, queue_key, verify


def probs(top: str, p: float, second: str | None = None, p2: float | None = None) -> dict:
    classes = ["glioma", "meningioma", "pituitary", "no_tumor"]
    out = {c: 0.0 for c in classes}
    out[top] = p
    rest = [c for c in classes if c != top]
    if second:
        out[second] = p2
        rest.remove(second)
        left = 1 - p - p2
    else:
        left = 1 - p
    for c in rest:
        out[c] = left / len(rest)
    return out


def test_confident_tumor_is_urgent(th):
    for cls in verifier.TUMOR_CLASSES:
        r = verify(probs(cls, 0.97), th)
        assert (r["tier"], r["reason"]) == (URGENT, "CONFIDENT_TUMOR")


def test_confident_no_tumor_is_routine(th):
    r = verify(probs("no_tumor", 0.97), th)
    assert (r["tier"], r["reason"]) == (ROUTINE, "CONFIDENT_NO_TUMOR")


def test_low_confidence_goes_to_review(th):
    r = verify(probs("glioma", 0.84), th)
    assert (r["tier"], r["reason"]) == (REVIEW, "LOW_CONFIDENCE")


def test_close_call_goes_to_review(th):
    r = verify(probs("glioma", 0.87, "meningioma", 0.12), {**th, "min_margin": 0.80})
    assert (r["tier"], r["reason"]) == (REVIEW, "CLOSE_CALL")


def test_threshold_edges_are_inclusive_of_the_threshold(th):
    assert verify(probs("glioma", 0.85), th)["tier"] == URGENT       # == min_conf passes
    assert verify(probs("glioma", 0.8499), th)["tier"] == REVIEW
    edge = {"glioma": 0.575, "meningioma": 0.425, "pituitary": 0.0, "no_tumor": 0.0}                 # margin exactly 0.15
    assert verify(edge, {**th, "min_conf": 0.5})["tier"] == URGENT


def test_rule_order_wait_beats_everything(th):
    r = verify(probs("glioma", 0.40, "meningioma", 0.35), th, waited_min=61)
    assert (r["tier"], r["reason"]) == (URGENT, "ESCALATED_WAIT")
    assert {"LOW_CONFIDENCE", "CLOSE_CALL"} <= set(r["reasons"])


def test_rule_order_low_confidence_before_close_call_before_out_of_distribution(th):
    r = verify(probs("glioma", 0.50, "meningioma", 0.45), th, out_of_distribution=True)
    assert r["reason"] == "LOW_CONFIDENCE"
    assert r["reasons"] == ["LOW_CONFIDENCE", "CLOSE_CALL", "OUT_OF_DISTRIBUTION"]
    r = verify(probs("glioma", 0.90, "meningioma", 0.09), {**th, "min_margin": 0.85})
    assert r["reason"] == "CLOSE_CALL"


def test_the_verifier_takes_no_second_model_input():
    import inspect
    assert set(inspect.signature(verify).parameters) == {"probs", "thresholds", "waited_min", "out_of_distribution"}
    assert not any("QWEN" in k or "OPINION" in k or "DISAGREE" in k for k in verifier.REASON_TEXT)


def test_escalation_exactly_at_max_wait_does_not_trigger(th):
    assert verify(probs("no_tumor", 0.99), th, waited_min=60)["tier"] == ROUTINE
    assert verify(probs("no_tumor", 0.99), th, waited_min=60.1)["tier"] == URGENT


def test_no_tumor_between_min_conf_and_routine_bar_is_review(th):
    r = verify(probs("no_tumor", 0.87), th)
    assert (r["tier"], r["reason"]) == (REVIEW, "ROUTINE_BAR_NOT_MET")


def test_out_of_distribution_goes_to_review(th):
    r = verify(probs("no_tumor", 0.99), th, out_of_distribution=True)
    assert (r["tier"], r["reason"]) == (REVIEW, "OUT_OF_DISTRIBUTION")


def test_queue_order_tier_then_longest_wait():
    scans = [
        {"id": "routine-old", "tier": ROUTINE, "uploaded_at": "2026-01-01T08:00:00+00:00"},
        {"id": "urgent-new", "tier": URGENT, "uploaded_at": "2026-01-01T09:30:00+00:00"},
        {"id": "pending", "tier": None, "uploaded_at": "2026-01-01T07:00:00+00:00"},
        {"id": "review", "tier": REVIEW, "uploaded_at": "2026-01-01T09:00:00+00:00"},
        {"id": "urgent-old", "tier": URGENT, "uploaded_at": "2026-01-01T08:30:00+00:00"},
    ]
    assert [s["id"] for s in sorted(scans, key=queue_key)] == ["urgent-old", "urgent-new", "review", "routine-old", "pending"]


def test_no_tier_or_reason_means_cleared():
    names = [verifier.URGENT, verifier.REVIEW, verifier.ROUTINE, *verifier.REASON_TEXT, *verifier.REASON_TEXT.values()]
    assert not any("clear" in n.lower() or "normal" in n.lower() for n in names)
