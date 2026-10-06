"""The patient version of a report.

Same source of truth as the doctor report (the doctor's confirmed review), but
built as a separate document in plain language. It is not the doctor report with
parts hidden: it has its own structure and wording.

What keeps the medical meaning unchanged:
  - the result is the doctor-approved finding, never raw model output;
  - the explanation of each finding is a fixed, hand-written text (below);
  - treatment, medicines, next steps, follow-up and warning signs are the
    doctor's own words, shown exactly as written - nothing is paraphrased, so a
    dose or an instruction can never be altered;
  - anything the doctor did not record is stated as not recorded, never guessed.

Never included: class probabilities, triage tier, model internals, the doctor's
private clinical notes, or the clinical report text.
"""
from __future__ import annotations

from app.config import CLASS_LABELS

# Hand-written plain-language explanations. Fixed text, reviewed once, never generated.
PLAIN = {
    "glioma": "A glioma is a growth that starts in the supporting cells of the brain. This report tells you what was seen on the scan. "
              "It does not say what kind of glioma it is or how it will behave; your doctor may arrange more tests to find that out.",
    "meningioma": "A meningioma is a growth that starts in the thin layers of tissue that cover the brain. This report tells you what was seen on the scan. "
                  "Your doctor will explain whether it needs treatment or only regular check-ups.",
    "pituitary": "A pituitary tumor is a growth in the pituitary gland, a small gland at the base of the brain that helps control the body's hormones. "
                 "This report tells you what was seen on the scan. Your doctor may arrange hormone or eye tests to learn more.",
    "no_tumor": "No tumor was seen on the scan images that were reviewed. If you still have symptoms, your doctor will talk with you about what to check next.",
}
NOT_RECORDED = "Your doctor has not recorded this in the report. Please ask them about it at your next visit."

MED_FIELDS = (("purpose", "What it is for"), ("how_to_take", "How to take it"), ("when_to_take", "When to take it"),
              ("duration", "For how long"), ("instructions", "Important instructions"))


def _clean(v) -> str:
    return (v or "").strip()


def medicines(review: dict) -> list[dict]:
    out = []
    for m in review.get("medications") or []:
        if _clean(m.get("name")):
            out.append({"name": _clean(m["name"]), "details": [{"label": label, "value": _clean(m.get(key)) or "Not provided"} for key, label in MED_FIELDS]})
    return out


def build_patient_report(scan: dict, report: dict) -> dict:
    rev = scan.get("review") or {}
    final = rev.get("final_class")
    label = CLASS_LABELS.get(final, "Not provided")
    meds = medicines(rev)
    size, location = rev.get("size_mm"), _clean(rev.get("location"))
    facts = []
    if final and final != "no_tumor":
        facts.append(f"Size: {size:g} mm" if size is not None else "Size: not recorded")
        facts.append(f"Where: {location}" if location else "Where: not recorded")

    sections = [
        {"id": "visit", "title": "Your Visit Summary",
         "text": f"You had this examination: {scan.get('exam_type') or 'MRI Brain'}."
                 + (f" The reason given was: {_clean(scan.get('clinical_concern'))}." if _clean(scan.get("clinical_concern")) else " The reason for the examination was not recorded.")},
        {"id": "found", "title": "What the Doctor Found", "text": report.get("patient_summary") or "", "facts": facts},
        {"id": "result", "title": "Your Result", "headline": label, "text": PLAIN.get(final, "")},
        {"id": "tests", "title": "Your Test",
         "text": "An MRI scan takes detailed pictures of the inside of the head without using X-rays. A computer program helped to sort your scan and "
                 "suggest a first reading. Your doctor then looked at the images and decided on the result written in this report."},
        {"id": "treatment", "title": "Your Treatment", "text": _clean(rev.get("treatment_plan")) or NOT_RECORDED, "from_doctor": bool(_clean(rev.get("treatment_plan")))},
        {"id": "medicines", "title": "Medicines", "medicines": meds, "text": "" if meds else "No medicines are listed in this report."},
        {"id": "next", "title": "What You Should Do Next",
         "text": _clean(rev.get("patient_instructions")) or "Talk through this report with your doctor. They will tell you what happens next.",
         "from_doctor": bool(_clean(rev.get("patient_instructions")))},
        {"id": "follow_up", "title": "Follow-Up", "text": _clean(rev.get("follow_up")) or NOT_RECORDED, "from_doctor": bool(_clean(rev.get("follow_up")))},
        {"id": "notes", "title": "Important Notes",
         "items": ["This report was reviewed and approved by your doctor.",
                   "Bring this report with you to your appointments.",
                   "Write down any questions you have so you can ask your doctor.",
                   "Do not start, stop or change any medicine because of this report without speaking to your doctor."]},
        {"id": "help", "title": "When to Seek Further Medical Help",
         "text": _clean(rev.get("warning_signs")) or "Your doctor did not list specific warning signs in this report. If you feel suddenly unwell or are worried, "
                                                     "contact your doctor, or your local emergency service in an emergency.",
         "from_doctor": bool(_clean(rev.get("warning_signs")))},
    ]
    return {"title": "Your MRI Report", "report_no": report.get("report_no"), "status": "Approved and finalized", "approved_finding": label,
            "exam_type": scan.get("exam_type") or "MRI Brain", "exam_date": scan.get("uploaded_at"), "doctor": report.get("signed_by_name"),
            "signed_at": report.get("signed_at"), "sections": sections}


def doctor_free_text(review: dict) -> str:
    """Everything the doctor typed, for the report check's allowed context."""
    parts = [_clean(review.get(k)) for k in ("symptoms", "history", "treatment_plan", "follow_up", "patient_instructions", "warning_signs")]
    for m in review.get("medications") or []:
        parts += [_clean(v) for v in m.values() if isinstance(v, str)]
    return " ".join(p for p in parts if p)
