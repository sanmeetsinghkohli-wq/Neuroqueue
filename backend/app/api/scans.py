from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from app import auth
from app.config import CLASS_LABELS, CLASSES, load_thresholds
from app.errors import ApiError
from app.realtime import hub, scan_for_patient
from app.services import pipeline, verifier
from app.services.audit import now_iso
from app.services.next_steps import RULES_VERSION, next_steps_for
from app.services.patient_report import build_patient_report
from app.store import get_store

router = APIRouter(prefix="/api", tags=["scans"])
MAX_BYTES = 15 * 1024 * 1024
ALLOWED = {"JPEG": "image/jpeg", "PNG": "image/png", "BMP": "image/bmp", "TIFF": "image/tiff", "WEBP": "image/webp"}


class JobIn(BaseModel):
    job_id: str | None = None


class MedicationIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    purpose: str | None = Field(default=None, max_length=200)
    how_to_take: str | None = Field(default=None, max_length=200)
    when_to_take: str | None = Field(default=None, max_length=200)
    duration: str | None = Field(default=None, max_length=120)
    instructions: str | None = Field(default=None, max_length=300)


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    decision: str  # confirm | override
    final_class: str | None = None
    override_reason: str | None = Field(default=None, max_length=500)
    size_mm: float | None = Field(default=None, gt=0, le=200)
    location: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)          # clinical notes: doctor report only
    symptoms: str | None = Field(default=None, max_length=1500)
    history: str | None = Field(default=None, max_length=1500)
    treatment_plan: str | None = Field(default=None, max_length=1500)
    medications: list[MedicationIn] = Field(default_factory=list, max_length=20)
    follow_up: str | None = Field(default=None, max_length=800)
    patient_instructions: str | None = Field(default=None, max_length=1500)
    warning_signs: str | None = Field(default=None, max_length=800)


async def load_scan(scan_id: str) -> dict:
    scan = await get_store().get("scans", scan_id)
    if not scan:
        raise ApiError(404, "SCAN_NOT_FOUND", "That scan does not exist.", "It may have been removed. Go back to the queue.")
    return scan


def can_access(scan: dict, user: dict) -> bool:
    """Administrators see every scan. A doctor sees only the scans an administrator assigned to them."""
    if user.get("status") != "approved":
        return False
    return user["role"] == "admin" or (user["role"] == "doctor" and scan.get("assigned_doctor_id") == user["id"])


def require_access(scan: dict, user: dict) -> dict:
    if not can_access(scan, user):
        raise ApiError(403, "NOT_ASSIGNED", "This scan is not assigned to you.", "Only the doctor an administrator assigned can open it.")
    return scan


async def load_doctor(doctor_id: str | None) -> dict:
    """The doctor a scan is being assigned to: must be an approved, verified doctor account."""
    if not doctor_id:
        raise ApiError(422, "DOCTOR_REQUIRED", "Choose the doctor who will read these scans.", "Every scan is assigned to one doctor.")
    doctor = await get_store().get("users", doctor_id)
    if not doctor or doctor["role"] != "doctor":
        raise ApiError(404, "DOCTOR_NOT_FOUND", "That doctor account does not exist.")
    if doctor["status"] != "approved" or not doctor.get("email_verified"):
        raise ApiError(409, "DOCTOR_NOT_APPROVED", "That doctor is not approved yet.", "Approve the doctor's registration first.")
    return doctor


def new_scan(*, filename: str, path: str, content_type: str, uploader: dict, patient: dict | None, patient_name: str | None,
             doctor: dict | None = None, uploaded_at: str | None = None, demo: dict | None = None, exam: dict | None = None) -> dict:
    exam = exam or {}
    return {
        "assigned_doctor_id": doctor["id"] if doctor else None, "assigned_doctor_name": doctor["full_name"] if doctor else None,
        "assigned_at": now_iso() if doctor else None,
        "id": str(uuid.uuid4()), "filename": filename, "storage_path": path, "content_type": content_type, "heatmap_path": None,
        "patient_id": patient["id"] if patient else None, "patient_name": patient["full_name"] if patient else (patient_name or None),
        "uploaded_by": uploader["id"], "uploaded_by_name": uploader["full_name"], "uploaded_at": uploaded_at or now_iso(),
        "status": "pending", "tier": None, "tier_provisional": False, "reasons": [], "notes": [], "prediction": None,
        "ood": None, "verifier": None, "classified_at": None, "escalated_at": None, "review": None,
        "reviewed_at": None, "report_id": None, "signed_at": None, "error": None,
        "is_demo": bool(demo), "demo_true_label": (demo or {}).get("true_label"),
        "exam_type": exam.get("exam_type") or "MRI Brain", "clinical_concern": exam.get("clinical_concern") or None,
        "referring_doctor": exam.get("referring_doctor") or None,
        "patient_age": exam.get("patient_age"), "patient_gender": exam.get("patient_gender") or None,
    }


def sniff_image(data: bytes) -> str:
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        fmt = img.format
    except Exception:
        raise ApiError(422, "NOT_AN_IMAGE", "One of the files is not a readable image.", "Upload JPEG or PNG brain MRI slices.")
    if fmt not in ALLOWED:
        raise ApiError(422, "UNSUPPORTED_FORMAT", f"{fmt} images are not supported.", "Upload JPEG or PNG brain MRI slices.")
    return ALLOWED[fmt]


@router.post("/scans/batch")
async def upload_batch(files: list[UploadFile] = File(...), doctor_id: str | None = Form(default=None),
                       patient_id: str | None = Form(default=None),
                       patient_name: str | None = Form(default=None), exam_type: str | None = Form(default=None),
                       clinical_concern: str | None = Form(default=None), referring_doctor: str | None = Form(default=None),
                       patient_age: int | None = Form(default=None), patient_gender: str | None = Form(default=None),
                       user: dict = Depends(auth.admin_only)):
    """Administrators only. Each batch is assigned to one doctor and linked to one patient; that doctor is then
    the only doctor who can open, review and report on these scans."""
    if not files:
        raise ApiError(422, "NO_FILES", "Choose at least one image.")
    if len(files) > 50:
        raise ApiError(422, "TOO_MANY_FILES", "Upload at most 50 scans at a time.")
    store, patient = get_store(), None
    doctor = await load_doctor(doctor_id)
    if not patient_id and not (patient_name or "").strip():
        raise ApiError(422, "PATIENT_REQUIRED", "Choose the patient these scans belong to.",
                       "Pick a patient account, or type the patient's name if they have no account yet.")
    if patient_id:
        patient = await store.get("users", patient_id)
        if not patient or patient["role"] != "patient":
            raise ApiError(404, "PATIENT_NOT_FOUND", "That patient account does not exist.")
    out = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_BYTES:
            raise ApiError(413, "FILE_TOO_LARGE", f"{f.filename} is larger than 15 MB.", "Export a smaller image and try again.")
        ctype = sniff_image(data)
        scan = new_scan(filename=(f.filename or "scan")[:120], path="", content_type=ctype, uploader=user, patient=patient,
                        patient_name=(patient_name or "").strip()[:120], doctor=doctor,
                        exam={"exam_type": (exam_type or "").strip()[:80], "clinical_concern": (clinical_concern or "").strip()[:500],
                              "referring_doctor": (referring_doctor or "").strip()[:120],
                              "patient_age": patient_age if patient_age and 0 < patient_age < 130 else None,
                              "patient_gender": (patient_gender or (patient or {}).get("gender") or "").strip()[:20]})
        scan["storage_path"] = f"scans/{scan['id']}"
        await store.put_file(scan["storage_path"], data, ctype)
        scan = await store.insert("scans", scan)
        await pipeline.audit("UPLOAD", user, scan["id"], {"filename": scan["filename"], "bytes": len(data)})
        await pipeline.audit("ASSIGNED", user, scan["id"], {"doctor_id": doctor["id"], "doctor": doctor["full_name"],
                                                            "patient_id": scan["patient_id"], "from_doctor": None})
        await hub.scan_updated(scan)
        out.append(scan)
    return {"scans": out}


@router.post("/scans/{scan_id}/classify")
async def classify(scan_id: str, body: JobIn | None = None, user: dict = Depends(auth.staff)):
    scan = require_access(await load_scan(scan_id), user)
    if scan["status"] in ("reviewed", "drafted", "signed"):
        raise ApiError(409, "ALREADY_REVIEWED", "A radiologist has already reviewed this scan.", "Reviewed scans are not re-classified.")
    job_id = (body.job_id if body else None) or str(uuid.uuid4())
    hub.start_job(job_id, "classify", user, lambda ctx: pipeline.classify_scan(scan_id, user, ctx), scan_id=scan_id, broadcast=True)
    return {"job_id": job_id}


@router.post("/queue/process")
async def process_queue(body: JobIn | None = None, user: dict = Depends(auth.staff)):
    job_id = (body.job_id if body else None) or str(uuid.uuid4())
    hub.start_job(job_id, "process_queue", user, lambda ctx: pipeline.process_pending(ctx, user), broadcast=True)
    return {"job_id": job_id}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, user: dict = Depends(auth.any_user)):
    return {"cancelled": hub.cancel_job(job_id, user)}


@router.get("/queue")
async def queue(user: dict = Depends(auth.staff)):
    await pipeline.escalate_waiting()
    scans = [s for s in await get_store().select("scans") if can_access(s, user)]
    scans.sort(key=verifier.queue_key)
    return {"scans": scans, "thresholds": load_thresholds(), "reason_text": verifier.REASON_TEXT, "server_time": now_iso()}


def released_report(scan: dict, rep: dict) -> dict:
    """What a patient receives: the doctor-approved result only. No probabilities, tiers or model internals."""
    # The patient version is its own document (see services/patient_report.py); the clinical report is never sent.
    return {"id": rep["id"], "signed_by_name": rep["signed_by_name"], "signed_at": rep["signed_at"], **build_patient_report(scan, rep)}


@router.get("/my/scans")
async def my_scans(user: dict = Depends(auth.require("patient"))):
    """A patient's own examinations. Ownership is enforced by the query, not by anything the client sends."""
    scans = await get_store().select("scans", {"patient_id": user["id"]}, order="uploaded_at", desc=True)
    out = []
    for s in scans:
        row = scan_for_patient(s)
        if s["status"] == "signed" and s.get("report_id"):
            rep = await get_store().get("reports", s["report_id"])
            if rep and rep["status"] == "signed":  # finalized reports only
                row["report"] = released_report(s, rep)
        out.append(row)
    return {"scans": out}


@router.post("/my/scans/{scan_id}/opened")
async def my_report_opened(scan_id: str, user: dict = Depends(auth.require("patient"))):
    """Audit trail: the patient opened their finalized report."""
    scan = await load_scan(scan_id)
    if scan.get("patient_id") != user["id"]:
        raise ApiError(403, "FORBIDDEN", "You do not have access to this report.")
    if scan["status"] != "signed":
        raise ApiError(409, "NOT_RELEASED", "This report has not been finalized yet.")
    await pipeline.audit("PATIENT_ACCESSED_REPORT", user, scan_id, {"how": "view"})
    return {"logged": True}


@router.get("/scans/{scan_id}")
async def get_scan(scan_id: str, user: dict = Depends(auth.staff)):
    scan = require_access(await load_scan(scan_id), user)
    from app.api.reports import clean_report
    report = clean_report(await get_store().get("reports", scan["report_id"]) if scan.get("report_id") else None)
    top = (scan.get("prediction") or {}).get("top_class")
    final = (scan.get("review") or {}).get("final_class")
    return {"scan": scan, "report": report, "reason_text": verifier.REASON_TEXT, "class_labels": CLASS_LABELS,
            "next_steps": {"label": "For radiologist consideration", "rules_version": RULES_VERSION, "for_class": final or top,
                           "items": next_steps_for(final or top) if (final or top) else []},
            "all_next_steps": {c: next_steps_for(c) for c in CLASSES}}


async def _authorise_file(scan: dict, user: dict) -> None:
    if can_access(scan, user):
        return
    if user["role"] == "patient" and scan.get("patient_id") == user["id"]:
        return
    raise ApiError(403, "FORBIDDEN", "You do not have access to this file.")


@router.get("/scans/{scan_id}/image")
async def scan_image(scan_id: str, user: dict = Depends(auth.current_user)):
    scan = await load_scan(scan_id)
    await _authorise_file(scan, user)
    data = await get_store().get_file(scan["storage_path"])
    if data is None:
        raise ApiError(404, "FILE_MISSING", "The image file is missing from storage.")
    return Response(data, media_type=scan.get("content_type") or "image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/scans/{scan_id}/heatmap")
async def scan_heatmap(scan_id: str, user: dict = Depends(auth.staff)):
    scan = await pipeline.ensure_heatmap(require_access(await load_scan(scan_id), user))
    if not scan.get("heatmap_path"):
        raise ApiError(409, "HEATMAP_UNAVAILABLE", "No heatmap is available for this scan yet.", "Classify the scan first.")
    data = await get_store().get_file(scan["heatmap_path"])
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/scans/{scan_id}/review")
async def review(scan_id: str, body: ReviewIn, user: dict = Depends(auth.doctor_only)):
    scan = require_access(await load_scan(scan_id), user)
    if scan["status"] == "signed":
        raise ApiError(409, "ALREADY_SIGNED", "This report is signed and released.", "Signed reports cannot be changed.")
    if not scan.get("prediction") or scan.get("tier_provisional"):
        raise ApiError(409, "NOT_CLASSIFIED", "This scan has not finished processing.", "Wait for the tier to finalize, then review.")
    predicted = scan["prediction"]["top_class"]
    if body.decision == "confirm":
        final = predicted
    elif body.decision == "override":
        if body.final_class not in CLASSES:
            raise ApiError(422, "INVALID_CLASS", "Choose the finding you are overriding to.")
        if not (body.override_reason or "").strip():
            raise ApiError(422, "OVERRIDE_REASON_REQUIRED", "An override needs a reason.", "Say briefly why you disagree with the prediction.")
        final = body.final_class
    else:
        raise ApiError(422, "INVALID_DECISION", "Decision must be confirm or override.")
    has_lesion = final != "no_tumor"  # size and location describe a lesion; there is none to describe otherwise
    rev = {"decision": body.decision, "predicted_class": predicted, "final_class": final,
           "override_reason": (body.override_reason or "").strip() or None, "size_mm": body.size_mm if has_lesion else None,
           "location": ((body.location or "").strip() or None) if has_lesion else None, "notes": (body.notes or "").strip() or None,
           "symptoms": body.symptoms or None, "history": body.history or None, "treatment_plan": body.treatment_plan or None,
           "medications": [m.model_dump() for m in body.medications], "follow_up": body.follow_up or None,
           "patient_instructions": body.patient_instructions or None, "warning_signs": body.warning_signs or None,
           "reviewer_id": user["id"], "reviewer_name": user["full_name"], "at": now_iso()}
    store = get_store()
    if scan.get("report_id"):  # the confirmed fields changed, so any earlier draft is stale
        await store.delete("reports", scan["report_id"])
    scan = await store.update("scans", scan_id, {"review": rev, "status": "reviewed", "reviewed_at": rev["at"], "report_id": None})
    await pipeline.audit("CONFIRM" if body.decision == "confirm" else "OVERRIDE", user, scan_id,
                         {"predicted": predicted, "final": final, "tier": scan.get("tier"), "reason": rev["override_reason"],
                          "waited_min": round(pipeline.minutes_since(scan["uploaded_at"]), 1)})
    await hub.scan_updated(scan)
    return {"scan": scan}


class AssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doctor_id: str


@router.post("/scans/{scan_id}/assign")
async def assign(scan_id: str, body: AssignIn, user: dict = Depends(auth.admin_only)):
    """Give a scan to a (different) doctor. Not possible once a doctor has reviewed it: the review is theirs."""
    scan = await load_scan(scan_id)
    if scan["status"] in ("reviewed", "drafted", "signed"):
        raise ApiError(409, "ALREADY_REVIEWED", "A doctor has already reviewed this scan.", "A reviewed scan stays with the doctor who reviewed it.")
    doctor = await load_doctor(body.doctor_id)
    previous = scan.get("assigned_doctor_id")
    if previous == doctor["id"]:
        return {"scan": scan}
    scan = await get_store().update("scans", scan_id, {"assigned_doctor_id": doctor["id"], "assigned_doctor_name": doctor["full_name"],
                                                       "assigned_at": now_iso()})
    await pipeline.audit("ASSIGNED", user, scan_id, {"doctor_id": doctor["id"], "doctor": doctor["full_name"],
                                                    "patient_id": scan.get("patient_id"), "from_doctor": previous})
    await hub.scan_unassigned(scan_id, previous)
    await hub.scan_updated(scan)
    return {"scan": scan}


@router.delete("/scans/{scan_id}")
async def delete_scan(scan_id: str, user: dict = Depends(auth.admin_only)):
    scan = await load_scan(scan_id)
    if scan["status"] == "signed":
        raise ApiError(409, "ALREADY_SIGNED", "Signed scans are part of the record and cannot be removed.")
    store = get_store()
    if scan.get("report_id"):
        await store.delete("reports", scan["report_id"])
    for p in (scan.get("storage_path"), scan.get("heatmap_path")):
        if p:
            await store.delete_file(p)
    await store.delete("scans", scan_id)
    await pipeline.audit("SCAN_REMOVED", user, scan_id, {"filename": scan["filename"], "status": scan["status"]})
    await hub.scan_removed(scan)
    return {"removed": True}
