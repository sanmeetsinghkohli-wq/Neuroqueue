from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app import auth
from app.api.scans import can_access, load_scan, require_access
from app.config import load_json_artifact
from app.errors import ApiError
from app.realtime import JobCtx, hub
from app.services import pipeline, report_check, report_writer
from app.services.audit import now_iso
from app.services.patient_report import build_patient_report
from app.services.pdf import build_patient_pdf, build_pdf
from app.services.qwen import get_qwen
from app.store import get_store

router = APIRouter(prefix="/api", tags=["reports"])


class DraftIn(BaseModel):
    job_id: str | None = None


class CheckIn(BaseModel):
    job_id: str | None = None
    clinical_text: str | None = Field(default=None, max_length=8000)
    patient_summary: str | None = Field(default=None, max_length=4000)


class SignIn(BaseModel):
    reviewer: str = Field(default="", max_length=120)


def _require_review(scan: dict) -> dict:
    rev = scan.get("review")
    if not rev or not rev.get("final_class"):
        raise ApiError(409, "REVIEW_REQUIRED", "A radiologist must review this scan before a report can be drafted.",
                       "Open the scan, confirm or override the prediction, then draft the report.")
    return rev


def clean_report(report: dict | None) -> dict | None:
    """Only deterministic check rows are ever returned. Guards against rows saved by older versions."""
    if report and report.get("check"):
        rows = [r for r in report["check"].get("rows") or [] if r.get("id") in report_check.ROW_IDS]
        if len(rows) != len(report["check"].get("rows") or []):
            report = {**report, "check": report_check.summarise(rows)}
    return report


async def _check(ctx: JobCtx | None, scan: dict, clinical: str, summary: str) -> dict:
    """Runs the deterministic report check, streaming one row at a time."""
    rev = scan.get("review")
    fields = report_writer.review_fields(rev, scan) if rev and rev.get("final_class") else None
    fixed = report_writer.fixed_text(scan, rev) if fields else ""
    rows = []
    async for row in report_check.run_check(clinical, summary, fields, fixed_text=fixed):
        rows.append(row)
        if ctx:
            await ctx.partial({"check_row": row})
            await asyncio.sleep(0.12)  # rows land one at a time rather than as a block
    return report_check.summarise(rows)


async def _save_report(scan: dict, user: dict, clinical: str, summary: str, check: dict, sources: dict, guard: dict | None) -> dict:
    store = get_store()
    row = {"scan_id": scan["id"], "status": "passed" if check["passed"] else "blocked", "clinical_text": clinical,
           "patient_summary": summary, "check": check, "sources": sources, "guard": guard, "updated_at": now_iso(),
           "signed_by": None, "signed_by_name": None, "signed_at": None, "pdf_path": None, "patient_pdf_path": None}
    if scan.get("report_id") and await store.get("reports", scan["report_id"]):
        report = await store.update("reports", scan["report_id"], row)
    else:
        rid, created = str(uuid.uuid4()), now_iso()
        report = await store.insert("reports", {"id": rid, "created_at": created, "report_no": report_writer.report_number(rid, created), **row})
    scan = await store.update("scans", scan["id"], {"report_id": report["id"], "status": "drafted"})
    await hub.scan_updated(scan)
    return report


async def draft_job(ctx: JobCtx, scan_id: str, user: dict) -> dict:
    scan = await load_scan(scan_id)
    rev = _require_review(scan)
    fields, qwen = report_writer.review_fields(rev, scan), get_qwen()
    await ctx.progress("drafting clinical report and patient summary", 5)

    async def section(name: str) -> tuple[str, str, dict | None]:
        async def on_token(tok: str):
            if tok == "\u0000RESET":
                await ctx.partial({"reset": name})
            else:
                await ctx.token(tok, name)
        try:
            body, source = await report_writer.write_section(qwen, name, fields, on_token)
            return body, source, None
        except report_writer.GuardTripped as g:
            await ctx.partial({"guard": {"section": name, "phrase": g.phrase}})
            return g.text, "qwen", {"section": name, "phrase": g.phrase}

    (c_body, c_src, c_guard), (s_body, s_src, s_guard) = await asyncio.gather(section("clinical"), section("summary"))
    clinical = report_writer.assemble_clinical(scan, rev, c_body)
    summary = report_writer.assemble_summary(s_body)
    await ctx.partial({"assembled": {"clinical_text": clinical, "patient_summary": summary}})
    await ctx.progress("running report check", 70)
    check = await _check(ctx, scan, clinical, summary)
    guard = c_guard or s_guard
    report = await _save_report(scan, user, clinical, summary, check, {"clinical": c_src, "summary": s_src}, guard)
    await pipeline.audit("DRAFT", user, scan_id, {"sources": report["sources"], "guard_tripped": bool(guard)})
    await pipeline.audit("CHECK_PASSED" if check["passed"] else "CHECK_BLOCKED", user, scan_id,
                         {"issues": [{"code": i["code"], "where": i["where"], "quote": i["quote"]} for i in check["issues"]][:20]})
    return {"report": report}


async def check_job(ctx: JobCtx, scan_id: str, user: dict, body: CheckIn) -> dict:
    scan = await load_scan(scan_id)
    _require_review(scan)
    report = await get_store().get("reports", scan["report_id"]) if scan.get("report_id") else None
    if not report:
        raise ApiError(409, "NO_DRAFT", "There is no draft to check.", "Draft the report first.")
    if report["status"] == "signed":
        raise ApiError(409, "ALREADY_SIGNED", "This report is signed and released.", "Signed reports cannot be changed.")
    clinical = body.clinical_text if body.clinical_text is not None else report["clinical_text"]
    summary = body.patient_summary if body.patient_summary is not None else report["patient_summary"]
    edited = clinical != report["clinical_text"] or summary != report["patient_summary"]
    await ctx.progress("running report check", 20)
    check = await _check(ctx, scan, clinical, summary)
    sources = {**(report.get("sources") or {}), **({"edited_by": user["full_name"]} if edited else {})}
    report = await _save_report(scan, user, clinical, summary, check, sources, None)
    if edited:
        await pipeline.audit("DRAFT_EDITED", user, scan_id, {})
    await pipeline.audit("CHECK_PASSED" if check["passed"] else "CHECK_BLOCKED", user, scan_id,
                         {"issues": [{"code": i["code"], "where": i["where"], "quote": i["quote"]} for i in check["issues"]][:20]})
    return {"report": report}


@router.post("/scans/{scan_id}/draft")
async def draft(scan_id: str, body: DraftIn | None = None, user: dict = Depends(auth.doctor_only)):
    scan = require_access(await load_scan(scan_id), user)
    if scan["status"] == "signed":
        raise ApiError(409, "ALREADY_SIGNED", "This report is signed and released.", "Signed reports cannot be redrafted.")
    _require_review(scan)
    job_id = (body.job_id if body else None) or str(uuid.uuid4())
    hub.start_job(job_id, "draft", user, lambda ctx: draft_job(ctx, scan_id, user), scan_id=scan_id)
    return {"job_id": job_id}


@router.post("/scans/{scan_id}/check")
async def check(scan_id: str, body: CheckIn, user: dict = Depends(auth.doctor_only)):
    scan = require_access(await load_scan(scan_id), user)
    _require_review(scan)
    job_id = body.job_id or str(uuid.uuid4())
    hub.start_job(job_id, "check", user, lambda ctx: check_job(ctx, scan_id, user, body), scan_id=scan_id)
    return {"job_id": job_id}


@router.get("/scans/{scan_id}/report")
async def get_report(scan_id: str, user: dict = Depends(auth.staff)):
    scan = require_access(await load_scan(scan_id), user)
    report = clean_report(await get_store().get("reports", scan["report_id"]) if scan.get("report_id") else None)
    if report and user["role"] == "doctor":
        await pipeline.audit("REPORT_OPENED", user, scan_id, {"report_no": report.get("report_no"), "status": report["status"]})
    return {"report": report, "stage": report_writer.report_stage(report), "stamp": "FINAL" if report and report["status"] == "signed" else "DRAFT"}


@router.post("/scans/{scan_id}/sign")
async def sign(scan_id: str, body: SignIn, user: dict = Depends(auth.doctor_only)):
    """Sign-off gate: completed review + passed check + named reviewer. Nothing is released otherwise."""
    scan = require_access(await load_scan(scan_id), user)
    store = get_store()
    if scan["status"] == "signed":
        raise ApiError(409, "ALREADY_SIGNED", "This report is already signed and released.")
    rev = _require_review(scan)
    report = await store.get("reports", scan["report_id"]) if scan.get("report_id") else None
    if not report:
        raise ApiError(409, "NO_DRAFT", "There is no draft report to sign.", "Draft the report first.")
    reviewer = body.reviewer.strip()
    if not reviewer:
        raise ApiError(422, "REVIEWER_REQUIRED", "Type your name to sign.", "Sign-off needs a named reviewer.")
    if reviewer.lower() != user["full_name"].strip().lower():
        raise ApiError(403, "REVIEWER_MISMATCH", "The name does not match the signed-in radiologist.", f"Sign as {user['full_name']}.")
    # Never trust a stored 'passed' flag: re-run the authoritative deterministic layer on the exact text being released.
    fields = report_writer.review_fields(rev, scan)
    rows = report_check.deterministic_rows(report["clinical_text"], report["patient_summary"], fields, report_writer.fixed_text(scan, rev))
    fresh = report_check.summarise(rows)
    if report["status"] != "passed" or not fresh["passed"]:
        await pipeline.audit("SIGN_REFUSED", user, scan_id, {"report_status": report["status"], "issues": len(fresh["issues"])})
        raise ApiError(409, "REPORT_BLOCKED", "The report check has not passed, so this report cannot be signed.",
                       "Fix the highlighted issues or regenerate the draft, then re-run the check.")

    signed_at = now_iso()
    ev = await pipeline.audit("APPROVED_AND_FINALIZED", user, scan_id, {"reviewer": reviewer, "final_class": rev["final_class"],
                                                                     "model_class": scan["prediction"]["top_class"], "report_no": report.get("report_no")})
    image = await store.get_file(scan["storage_path"])
    patient = await store.get("users", scan["patient_id"]) if scan.get("patient_id") else None
    final = {**report, "status": "signed", "signed_by_name": reviewer, "signed_at": signed_at}
    pdf = await asyncio.to_thread(build_pdf, scan=scan, report=final, doctor=user, patient=patient, signed_at=signed_at,
                                  audit_hash=ev["hash"], image=image, model_metrics=load_json_artifact("metrics.json"))
    patient_pdf = await asyncio.to_thread(build_patient_pdf, scan=scan, report=final, patient=patient)
    path, patient_path = f"reports/{report['id']}.pdf", f"reports/{report['id']}-patient.pdf"
    await store.put_file(path, pdf, "application/pdf")
    await store.put_file(patient_path, patient_pdf, "application/pdf")
    report = await store.update("reports", report["id"], {"status": "signed", "signed_by": user["id"], "signed_by_name": reviewer,
                                                         "signed_at": signed_at, "pdf_path": path, "patient_pdf_path": patient_path})
    scan = await store.update("scans", scan_id, {"status": "signed", "signed_at": signed_at})
    await pipeline.audit("PDF_EXPORTED", user, scan_id, {"bytes": len(pdf), "path": path})
    await hub.scan_updated(scan)
    return {"report": report, "scan": scan}


@router.get("/scans/{scan_id}/patient-version")
async def patient_version(scan_id: str, user: dict = Depends(auth.staff)):
    """Lets the doctor see exactly what the patient will receive, before and after finalizing."""
    scan = require_access(await load_scan(scan_id), user)
    report = await get_store().get("reports", scan["report_id"]) if scan.get("report_id") else None
    if not report:
        raise ApiError(409, "NO_DRAFT", "There is no report yet.", "Draft the report first.")
    return {"patient_report": build_patient_report(scan, report), "final": report["status"] == "signed"}


@router.get("/scans/{scan_id}/pdf")
async def pdf(scan_id: str, version: str = "auto", user: dict = Depends(auth.current_user)):
    """The role decides the document, on the server. A patient always receives the patient version, whatever they ask for;
    the clinical report never leaves through a patient session."""
    scan = await load_scan(scan_id)
    staff_ok = can_access(scan, user)
    is_owner = user["role"] == "patient" and user["status"] == "approved" and scan.get("patient_id") == user["id"]
    if not staff_ok and not is_owner:
        raise ApiError(403, "FORBIDDEN", "You do not have access to this report.")
    store = get_store()
    report = await store.get("reports", scan["report_id"]) if scan.get("report_id") else None
    if not report or report["status"] != "signed" or not report.get("pdf_path"):
        raise ApiError(409, "NOT_RELEASED", "This report has not been finalized yet.",
                       "A doctor must approve and finalize the report before it can be downloaded.")
    want_patient = is_owner or (staff_ok and version == "patient")
    if want_patient:
        data = await store.get_file(report["patient_pdf_path"]) if report.get("patient_pdf_path") else None
        if data is None:   # reports finalized before the patient version existed
            patient = await store.get("users", scan["patient_id"]) if scan.get("patient_id") else None
            data = await asyncio.to_thread(build_patient_pdf, scan=scan, report=report, patient=patient)
            path = f"reports/{report['id']}-patient.pdf"
            await store.put_file(path, data, "application/pdf")
            await store.update("reports", report["id"], {"patient_pdf_path": path})
        name = f"your-mri-report-{report.get('report_no') or scan_id[:8]}.pdf"
    else:
        data = await store.get_file(report["pdf_path"])
        name = f"clinical-report-{report.get('report_no') or scan_id[:8]}.pdf"
    if is_owner:
        await pipeline.audit("PATIENT_ACCESSED_REPORT", user, scan_id, {"report_no": report.get("report_no"), "how": "pdf"})
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
