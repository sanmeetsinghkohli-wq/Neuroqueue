"""Report check.

Deterministic and authoritative: every tumor type, measurement and location in
the draft must trace back to the physician-confirmed fields. No language model
judges the report, so the check can never contradict the confirmed finding.

Any issue blocks sign-off until the draft is regenerated or edited and re-checked.
"""
from __future__ import annotations

import re
from typing import AsyncIterator

from app.config import CLASS_LABELS
from app.services.next_steps import next_steps_for

REQUIRED_LINE = "AI-assisted triage was used."

# "plain" terms restate the confirmed class; "subtype" terms add detail the review never confirmed.
TYPE_TERMS = {
    "glioma": {"plain": ["glioma"], "subtype": ["glioblastoma", "astrocytoma", "oligodendroglioma", "ependymoma"]},
    "meningioma": {"plain": ["meningioma"], "subtype": []},
    "pituitary": {"plain": ["pituitary tumor", "pituitary tumour", "pituitary mass", "pituitary lesion"],
                  "subtype": ["adenoma", "macroadenoma", "microadenoma", "prolactinoma"]},
}
CANONICAL_TERMS = {"glioma": ["glioma"], "meningioma": ["meningioma"], "pituitary": ["pituitary tumor", "pituitary tumour"],
                   "no_tumor": ["no tumor", "no tumour"]}

FORBIDDEN = [
    r"malignan\w*", r"benign", r"cancer\w*", r"prognos\w*", r"survival", r"life expectancy", r"metasta\w*",
    r"who grade", r"grade\s+(?:i{1,3}|iv|[1-4])\b", r"(?:high|low)[- ]grade", r"\bcleared\b", r"all[- ]clear",
    r"nothing to worry", r"definitely", r"confirmed diagnosis", r"\bcured?\b", r"terminal",
]
FORBIDDEN_RE = re.compile("|".join(f"(?:{p})" for p in FORBIDDEN), re.I)

LOCATION_TERMS = [
    "frontal", "temporal", "parietal", "occipital", "cerebellum", "cerebellar", "brainstem", "brain stem", "pons",
    "medulla", "midbrain", "thalamus", "thalamic", "basal ganglia", "corpus callosum", "ventricle", "ventricular",
    "intraventricular", "sellar", "suprasellar", "parasellar", "cavernous sinus", "optic chiasm", "falx", "parasagittal",
    "convexity", "sphenoid", "tentorium", "tentorial", "cerebellopontine", "posterior fossa", "insula", "insular",
    "hippocampus", "hippocampal", "hypothalamus", "pineal", "skull base", "olfactory groove", "bilateral", "midline",
    "left", "right", "hemisphere",
]
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def find_forbidden(text: str) -> str | None:
    m = FORBIDDEN_RE.search(text)
    return m.group(0) if m else None


def _has(term: str, text: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", text) is not None


def _num_forms(v) -> set[str]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return set()
    out = set()
    for x in (f, f / 10):  # mm and its cm equivalent
        out |= {f"{x:g}", f"{x:.1f}", f"{x:.2f}"}
    return out


def allowed_context(fields: dict, fixed_text: str = "") -> str:
    """Everything the draft is permitted to restate."""
    parts = [fields.get("location") or "", fields.get("notes") or "", fields.get("clinical_concern") or "", fields.get("doctor_text") or "",
             " ".join(next_steps_for(fields.get("final_class", ""))), fixed_text]
    return " ".join(parts).lower()


def _issue(code: str, where: str, quote: str, detail: str) -> dict:
    return {"code": code, "where": where, "quote": quote, "detail": detail}


def check_types(text: str, where: str, fields: dict, ctx: str) -> list[dict]:
    low, final, issues = text.lower(), fields["final_class"], []
    for cls, terms in TYPE_TERMS.items():
        for term in terms["plain"] + terms["subtype"]:
            if not _has(term, low):
                continue
            if cls != final:
                issues.append(_issue("CONTRADICTION", where, term,
                                     f"Mentions '{term}' but the radiologist confirmed {CLASS_LABELS[final]}."))
            elif term in terms["subtype"] and not _has(term, ctx):
                issues.append(_issue("INVENTED_DETAIL", where, term, f"Subtype '{term}' is not in the confirmed fields."))
    if not any(_has(t, low) for t in CANONICAL_TERMS[final]):
        want = CANONICAL_TERMS[final][0]
        issues.append(_issue("MISSING_FIELD", where, want, f"The confirmed finding '{want}' is not stated."))
    return issues


def check_numbers(text: str, where: str, fields: dict, ctx: str) -> list[dict]:
    allowed = set(NUMBER_RE.findall(ctx)) | _num_forms(fields.get("size_mm"))
    issues, seen = [], set()
    for n in NUMBER_RE.findall(text):
        if n not in allowed and n not in seen:
            seen.add(n)
            issues.append(_issue("INVENTED_DETAIL", where, n, f"The number {n} is not in the confirmed fields."))
    size = fields.get("size_mm")
    if size is not None and fields["final_class"] != "no_tumor" and where == "clinical" and not (_num_forms(size) & set(NUMBER_RE.findall(text))):
        issues.append(_issue("MISSING_FIELD", where, f"{size:g} mm", "The confirmed size is not stated in the clinical report."))
    return issues


def _mentions_location(term: str, low: str) -> bool:
    if term == "right":  # "right away" / "right now" are not anatomy
        return re.search(r"(?<![a-z])right(?![a-z])(?!\s+(?:away|now|for))", low) is not None
    return _has(term, low)


def check_locations(text: str, where: str, fields: dict, ctx: str) -> list[dict]:
    low = text.lower()
    return [_issue("INVENTED_DETAIL", where, term, f"Location '{term}' is not in the confirmed fields.")
            for term in LOCATION_TERMS if _mentions_location(term, low) and not _has(term, ctx)]


def check_forbidden(text: str, where: str) -> list[dict]:
    return [_issue("FORBIDDEN_PHRASE", where, m.group(0), "Malignancy, prognosis, grading and 'cleared' language is not allowed.")
            for m in FORBIDDEN_RE.finditer(text)]


def check_required(text: str, where: str) -> list[dict]:
    if REQUIRED_LINE.lower() not in text.lower():
        return [_issue("MISSING_STATEMENT", where, REQUIRED_LINE, f"The line '{REQUIRED_LINE}' must appear.")]
    return []


ROWS = [
    ("TUMOR_TYPE", "Tumor type matches the confirmed review", lambda t, w, f, c: check_types(t, w, f, c)),
    ("MEASUREMENTS", "No numbers beyond the confirmed fields", lambda t, w, f, c: check_numbers(t, w, f, c)),
    ("LOCATION", "No locations beyond the confirmed fields", lambda t, w, f, c: check_locations(t, w, f, c)),
    ("LANGUAGE", "No malignancy, prognosis or 'cleared' language", lambda t, w, f, c: check_forbidden(t, w)),
    ("STATEMENTS", "Required AI-assistance statement present", lambda t, w, f, c: check_required(t, w)),
]


ROW_IDS = ("REVIEW",) + tuple(r[0] for r in ROWS)   # the complete set of checks; none is a language model


def deterministic_rows(clinical: str, summary: str, fields: dict | None, fixed_text: str = "") -> list[dict]:
    if not fields or not fields.get("final_class"):
        return [{"id": "REVIEW", "label": "Radiologist review completed", "status": "fail",
                 "issues": [_issue("NO_REVIEW", "clinical", "", "A completed radiologist review is required before a report can be checked.")]}]
    rows = [{"id": "REVIEW", "label": "Radiologist review completed", "status": "pass", "issues": []}]
    ctx = allowed_context(fields, fixed_text)
    # The deterministic header restates the confirmed finding; the drafted body has to state it too.
    body = clinical
    for line in fixed_text.splitlines():
        if line.strip():
            body = body.replace(line, "")
    for rid, label, fn in ROWS:
        issues = fn(body if rid == "TUMOR_TYPE" else clinical, "clinical", fields, ctx) + fn(summary, "summary", fields, ctx)
        rows.append({"id": rid, "label": label, "status": "fail" if issues else "pass", "issues": issues})
    return rows


async def run_check(clinical: str, summary: str, fields: dict | None, *, fixed_text: str = "") -> AsyncIterator[dict]:
    """Yields one row at a time."""
    for r in deterministic_rows(clinical, summary, fields, fixed_text):
        yield r


def summarise(rows: list[dict]) -> dict:
    issues = [i for r in rows for i in r["issues"]]
    return {"passed": not issues and all(r["status"] != "fail" for r in rows), "rows": rows, "issues": issues}
