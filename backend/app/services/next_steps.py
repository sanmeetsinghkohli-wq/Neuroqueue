"""Hand-written next-step suggestions, keyed by the radiologist-confirmed class.

A fixed rule table, never an LLM: every line is reviewable and none of it is a
treatment decision. Shown in the UI as "For radiologist consideration".
"""
from __future__ import annotations

RULES_VERSION = "2026.1"

NEXT_STEPS: dict[str, list[str]] = {
    "glioma": [
        "Consider contrast-enhanced MRI with multiplanar sequences if not already acquired.",
        "Consider referral to neurosurgery and neuro-oncology for multidisciplinary discussion.",
        "Correlate with clinical history and neurological examination.",
    ],
    "meningioma": [
        "Consider contrast-enhanced MRI to characterise the dural attachment if not already acquired.",
        "Consider neurosurgical referral; interval follow-up imaging may be appropriate depending on symptoms.",
        "Correlate with clinical history and neurological examination.",
    ],
    "pituitary": [
        "Consider a dedicated pituitary protocol MRI with contrast if not already acquired.",
        "Consider endocrinology referral and a pituitary hormone panel.",
        "Consider formal visual field assessment if there are visual symptoms.",
    ],
    "no_tumor": [
        "No tumor-specific follow-up is suggested by this triage result alone.",
        "Correlate with clinical history; further imaging remains at the radiologist's discretion.",
    ],
}


def next_steps_for(final_class: str) -> list[str]:
    return list(NEXT_STEPS.get(final_class, []))
