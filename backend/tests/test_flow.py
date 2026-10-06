"""End-to-end flow, safety gates, access control and contracts. Mock mode, no network."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from app.config import CLASSES
from app.realtime import hub, scan_for_patient
from app.services import report_writer as rw
from app.services.audit import verify_chain
from app.services.classifier import MockClassifier
from app.services.pdf import build_pdf
from app.services.qwen import MockQwen, set_qwen
from app.services.simulation import run_simulation
from app.store import get_store
from tests.conftest import png, run

APP_DIR = Path(__file__).resolve().parent.parent / "app"


# ---------------- contracts ----------------
def test_mock_classifier_returns_the_prediction_schema():
    r = MockClassifier().predict(png(), "glioma_case.png")
    assert set(r) == {"probs", "model", "model_version", "energy", "ood"}
    assert list(r["probs"]) == CLASSES and abs(sum(r["probs"].values()) - 1) < 1e-3
    assert set(r["ood"]) == {"flag", "reason"}


def test_pdf_export_produces_a_pdf():
    review = {"decision": "confirm", "final_class": "glioma", "size_mm": 12, "location": "left frontal lobe", "reviewer_name": "Dr A"}
    scan = {"id": "abcdef12", "filename": "s.png", "patient_name": "Pat", "patient_id": None, "uploaded_at": "2026-10-06T09:00:00.000+00:00", "review": review,
            "prediction": {"top_class": "glioma", "top_prob": 0.97, "probs": {"glioma": 0.97, "meningioma": 0.01, "pituitary": 0.01, "no_tumor": 0.01}, "model": "mock"}}
    body = rw.template_clinical(rw.review_fields(review))
    report = {"id": "r1", "report_no": "NQ-20261006-ABCDEF", "signed_by_name": "Dr A", "clinical_text": rw.assemble_clinical(scan, review, body),
              "patient_summary": rw.assemble_summary("A glioma was seen.")}
    pdf = build_pdf(scan=scan, report=report, doctor={"full_name": "Dr A", "specialty": "Neuroradiology", "license_no": "L1"}, patient=None,
                    signed_at="2026-10-06T10:00:00.000+00:00", audit_hash="ab" * 32, image=png())
    assert pdf[:5] == b"%PDF-" and len(pdf) > 2000


def test_simulation_reports_assumptions_and_orders_urgent_first():
    r = run_simulation({"replications": 30})
    assert {"arrivals_per_hour", "read_minutes", "urgent_fraction", "prediction_source"} <= set(r["assumptions"])
    assert r["policies"]["neuroqueue"]["urgent_mean_wait_min"] <= r["policies"]["fcfs"]["urgent_mean_wait_min"]
    assert "not clinical outcomes" in r["disclaimer"].lower()


# ---------------- the full flow ----------------
def test_end_to_end_upload_to_signed_pdf():
    async def scenario(api):
        await api.approve_doctor()
        await api.upload(["no_tumor_a.png", "glioma_b.png", "uncertain_c.png", "pituitary_d.png", "meningioma_e.png"])
        before = await api.queue()
        assert all(s["status"] == "pending" and s["tier"] is None for s in before)

        await api.process()
        q = await api.queue()
        assert [s["tier"] for s in q] == ["URGENT", "URGENT", "URGENT", "REVIEW", "ROUTINE"]
        by_name = {s["filename"]: s for s in q}
        assert by_name["uncertain_c.png"]["reasons"][0] == "LOW_CONFIDENCE"
        assert by_name["pituitary_d.png"]["prediction"]["top_class"] == "pituitary"  # the model's class, preserved exactly
        assert by_name["no_tumor_a.png"]["reasons"] == ["CONFIDENT_NO_TUMOR"]
        assert all(not s["tier_provisional"] and "second_opinion" not in s for s in q)
        assert by_name["glioma_b.png"]["heatmap_path"] and not by_name["no_tumor_a.png"]["heatmap_path"]

        top = q[0]
        r = await api.review(top["id"], size_mm=18, location="left frontal lobe", notes="Ring-enhancing lesion.")
        assert r.status_code == 200 and r.json()["scan"]["status"] == "reviewed"

        report = await api.draft(top["id"])
        assert report["status"] == "passed", report["check"]["issues"]
        assert "AI-assisted triage was used." in report["clinical_text"] and "AI-assisted triage was used." in report["patient_summary"]
        assert (await api.c.get(f"/api/scans/{top['id']}/pdf", headers=api.h("doctor"))).json()["code"] == "NOT_RELEASED"

        r = await api.sign(top["id"])
        assert r.status_code == 200, r.text
        assert r.json()["report"]["status"] == "signed" and r.json()["scan"]["status"] == "signed"
        pdf = await api.c.get(f"/api/scans/{top['id']}/pdf", headers=api.h("doctor"))
        assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"

        audit = (await api.c.get("/api/audit", headers=api.h("doctor"))).json()
        assert audit["chain"]["ok"]
        actions = [e["action"] for e in audit["events"] if e["scan_id"] == top["id"]][::-1]
        assert actions == ["UPLOAD", "ASSIGNED", "CLASSIFIED", "TIER", "CONFIRM", "DRAFT", "CHECK_PASSED", "REPORT_OPENED", "APPROVED_AND_FINALIZED", "PDF_EXPORTED"]
        assert r.json()["report"]["report_no"].startswith("NQ-")
    run(scenario)


def test_override_requires_a_reason_and_is_logged():
    async def scenario(api):
        await api.approve_doctor()
        (scan,) = await api.upload(["glioma_x.png"])
        await api.process()
        r = await api.review(scan["id"], decision="override", final_class="meningioma")
        assert r.status_code == 422 and r.json()["code"] == "OVERRIDE_REASON_REQUIRED"
        r = await api.review(scan["id"], decision="override", final_class="meningioma", override_reason="Dural tail visible.")
        assert r.status_code == 200 and r.json()["scan"]["review"]["final_class"] == "meningioma"
        events = (await api.c.get("/api/audit", params={"scan_id": scan["id"]}, headers=api.h("doctor"))).json()["events"]
        override = next(e for e in events if e["action"] == "OVERRIDE")
        assert override["details"]["predicted"] == "glioma" and override["details"]["final"] == "meningioma"
        live = (await api.c.get("/api/metrics", headers=api.h("doctor"))).json()["live"]
        assert live["overridden"] == 1 and live["errors_caught_by_verifier"] == 1
    run(scenario)


# ---------------- safety ----------------
def test_cannot_draft_or_sign_without_a_review():
    async def scenario(api):
        await api.approve_doctor()
        (scan,) = await api.upload(["glioma_x.png"])
        await api.process()
        r = await api.c.post(f"/api/scans/{scan['id']}/draft", json={}, headers=api.h("doctor"))
        assert r.status_code == 409 and r.json()["code"] == "REVIEW_REQUIRED"
        r = await api.sign(scan["id"])
        assert r.status_code == 409 and r.json()["code"] == "REVIEW_REQUIRED"
    run(scenario)


def test_cannot_review_before_the_tier_is_final():
    async def scenario(api):
        await api.approve_doctor()
        (scan,) = await api.upload(["glioma_x.png"])
        r = await api.review(scan["id"])
        assert r.status_code == 409 and r.json()["code"] == "NOT_CLASSIFIED"
    run(scenario)


def test_blocked_report_cannot_be_signed_until_fixed_and_rechecked():
    async def scenario(api):
        await api.approve_doctor()
        (scan,) = await api.upload(["glioma_x.png"])
        await api.process()
        await api.review(scan["id"], size_mm=20, location="left frontal lobe")
        report = await api.draft(scan["id"])
        assert report["status"] == "passed"

        tampered = report["clinical_text"].replace("IMPRESSION:", "IMPRESSION: Likely malignant, 45 mm, extending to the right temporal lobe.")
        r = await api.c.post(f"/api/scans/{scan['id']}/check", json={"clinical_text": tampered}, headers=api.h("doctor"))
        assert r.status_code == 200
        await hub.wait_idle()
        report = (await api.c.get(f"/api/scans/{scan['id']}/report", headers=api.h("doctor"))).json()["report"]
        assert report["status"] == "blocked"
        assert {"FORBIDDEN_PHRASE", "INVENTED_DETAIL"} <= {i["code"] for i in report["check"]["issues"]}

        r = await api.sign(scan["id"])
        assert r.status_code == 409 and r.json()["code"] == "REPORT_BLOCKED"
        assert (await api.c.get(f"/api/scans/{scan['id']}/pdf", headers=api.h("doctor"))).json()["code"] == "NOT_RELEASED"

        report = await api.draft(scan["id"])  # regenerate
        assert report["status"] == "passed"
        assert (await api.sign(scan["id"])).status_code == 200
    run(scenario)


def test_sign_rechecks_the_text_even_if_the_stored_status_says_passed():
    async def scenario(api):
        await api.approve_doctor()
        (scan,) = await api.upload(["glioma_x.png"])
        await api.process()
        await api.review(scan["id"], size_mm=20, location="left frontal lobe")
        report = await api.draft(scan["id"])
        await get_store().update("reports", report["id"], {"clinical_text": report["clinical_text"] + " Prognosis is poor."})
        r = await api.sign(scan["id"])
        assert r.status_code == 409 and r.json()["code"] == "REPORT_BLOCKED"
    run(scenario)


def test_sign_needs_the_named_signed_in_reviewer():
    async def scenario(api):
        await api.approve_doctor()
        (scan,) = await api.upload(["glioma_x.png"])
        await api.process()
        await api.review(scan["id"], size_mm=20, location="left frontal lobe")
        await api.draft(scan["id"])
        assert (await api.sign(scan["id"], reviewer="")).json()["code"] == "REVIEWER_REQUIRED"
        assert (await api.sign(scan["id"], reviewer="Dr Someone Else")).json()["code"] == "REVIEWER_MISMATCH"
        assert (await api.sign(scan["id"])).status_code == 200
        assert (await api.sign(scan["id"])).json()["code"] == "ALREADY_SIGNED"
        assert (await api.review(scan["id"])).json()["code"] == "ALREADY_SIGNED"
    run(scenario)


def test_re_review_discards_the_stale_draft():
    async def scenario(api):
        await api.approve_doctor()
        (scan,) = await api.upload(["glioma_x.png"])
        await api.process()
        await api.review(scan["id"], size_mm=20, location="left frontal lobe")
        await api.draft(scan["id"])
        await api.review(scan["id"], decision="override", final_class="meningioma", override_reason="Extra-axial.")
        assert (await api.c.get(f"/api/scans/{scan['id']}/report", headers=api.h("doctor"))).json()["report"] is None
        assert (await api.sign(scan["id"])).json()["code"] == "NO_DRAFT"
    run(scenario)


def test_the_model_result_is_immutable_and_preserved_through_an_override():
    async def scenario(api):
        await api.approve_doctor()
        (scan,) = await api.upload(["pituitary_x.png"])
        await api.process()
        before = (await api.queue())[0]["prediction"]
        await api.review(scan["id"], decision="override", final_class="meningioma", override_reason="Extra-axial.", size_mm=11, location="left frontal lobe")
        report = await api.draft(scan["id"])
        after = (await api.queue())[0]
        assert after["prediction"] == before and after["prediction"]["top_class"] == "pituitary"
        assert after["review"]["predicted_class"] == "pituitary" and after["review"]["final_class"] == "meningioma"
        assert report["status"] == "passed" and "meningioma" in report["clinical_text"]
    run(scenario)


def test_a_model_failure_never_produces_a_classification():
    async def scenario(api):
        await api.approve_doctor()

        class Broken(MockClassifier):
            def predict(self, data, filename=""):
                raise RuntimeError("model crashed")
        from app.services.classifier import set_classifier
        set_classifier(Broken())
        (scan,) = await api.upload(["glioma_x.png"])
        await api.process()
        (s,) = await api.queue()
        assert s["status"] == "failed" and s["prediction"] is None and s["tier"] is None and "No classification" in s["error"]
        assert (await api.review(scan["id"])).json()["code"] == "NOT_CLASSIFIED"
    run(scenario)


def test_no_language_model_is_called_during_classification():
    async def scenario(api):
        await api.approve_doctor()

        class Tripwire(MockQwen):
            async def stream(self, messages, **kw):
                raise AssertionError("the language model was called during classification")
                yield ""
        set_qwen(Tripwire())
        await api.upload(["glioma_a.png", "no_tumor_b.png", "uncertain_c.png"])
        await api.process()
        assert [s["status"] for s in await api.queue()] == ["classified"] * 3
        assert not hasattr(Tripwire, "second_opinion")
    run(scenario)


def test_no_code_path_marks_a_scan_cleared():
    """Every status, tier and patient-facing stage the code can assign comes from a closed list with no 'cleared'."""
    allowed_status = {"pending", "processing", "classified", "reviewed", "drafted", "signed", "failed",       # scans
                      "passed", "blocked", "pass", "fail", "skipped",                                          # reports / check rows
                      "ok", "abstained", "unavailable", "open", "in_progress"}                                 # providers / tickets
    found = set()
    for path in APP_DIR.rglob("*.py"):
        if path.name in ("auth.py",):  # account statuses, not scan statuses
            continue
        text = path.read_text(encoding="utf-8")
        found |= set(re.findall(r'"status":\s*"([a-z_]+)"', text))
        assert not re.search(r'"tier":\s*"(?!URGENT|REVIEW|ROUTINE)[A-Za-z_]+"', text), path.name
    assert found <= allowed_status, found - allowed_status
    stages = {scan_for_patient({"id": "1", "status": s})["stage"] for s in allowed_status}
    assert stages == {"Awaiting doctor review", "Reviewed by doctor", "Report under physician review", "Report finalized"}
    assert not any(w in " ".join(stages | found).lower() for w in ("clear", "normal", "negative", "healthy"))


def test_wait_time_escalation_retiers_and_logs():
    async def scenario(api):
        await api.approve_doctor()
        await api.upload(["no_tumor_a.png", "uncertain_b.png", "glioma_c.png"])
        await api.process()
        r = await api.c.post("/api/demo/advance", json={"minutes": 90}, headers=api.h("doctor"))
        assert r.json()["escalated"] == 2
        q = await api.queue()
        assert all(s["tier"] == "URGENT" for s in q)
        assert sum(s["reasons"][0] == "ESCALATED_WAIT" for s in q) == 2
        events = (await api.c.get("/api/audit", params={"action": "TIER"}, headers=api.h("doctor"))).json()["events"]
        assert sum(e["details"].get("reason") == "ESCALATED_WAIT" for e in events) == 2
    run(scenario)


def test_non_image_upload_is_rejected_with_a_structured_error():
    async def scenario(api):
        await api.approve_doctor()
        r = await api.c.post("/api/scans/batch", files=[("files", ("notes.txt", b"hello", "text/plain"))],
                             data={"doctor_id": api.doctor_id, "patient_name": "Walk-in Patient"}, headers=api.h("admin"))
        assert r.status_code == 422 and set(r.json()) == {"code", "message", "hint"} and r.json()["code"] == "NOT_AN_IMAGE"
    run(scenario)


# ---------------- access control ----------------
def test_pending_doctor_is_locked_out_until_an_admin_approves():
    async def scenario(api):
        r = await api.c.get("/api/queue", headers=api.h("doctor"))
        assert r.status_code == 403 and r.json()["code"] == "NOT_APPROVED"
        assert (await api.c.get("/api/users", headers=api.h("doctor"))).status_code == 403
        pending = (await api.c.get("/api/users", params={"status": "pending"}, headers=api.h("admin"))).json()["users"]
        assert [u["email"] for u in pending] == ["doc@test.local"]
        await api.approve_doctor()
        assert (await api.c.get("/api/queue", headers=api.h("doctor"))).status_code == 200
    run(scenario)


def test_rejected_doctor_cannot_sign_in():
    async def scenario(api):
        await api.c.post(f"/api/users/{api.doctor_id}/status", json={"status": "rejected"}, headers=api.h("admin"))
        r = await api.c.post("/api/auth/login", json={"email": "doc@test.local", "password": "a-long-password-1"})
        assert r.status_code == 403 and r.json()["code"] == "REGISTRATION_REJECTED"
        assert (await api.c.get("/api/auth/me", headers=api.h("doctor"))).status_code == 401  # the existing session died too
    run(scenario)


def test_patients_cannot_upload_scans_or_run_the_model():
    async def scenario(api):
        await api.approve_doctor()
        r = await api.c.post("/api/scans/batch", files=[("files", ("mine.png", png(), "image/png"))], headers=api.h("patient"))
        assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN"
        (scan,) = await api.upload(["glioma_p.png"], patient_id=api.patient_id)
        for url, body in ((f"/api/scans/{scan['id']}/classify", {}), ("/api/queue/process", {}), (f"/api/scans/{scan['id']}/review", {"decision": "confirm"}),
                          (f"/api/scans/{scan['id']}/draft", {}), (f"/api/scans/{scan['id']}/sign", {"reviewer": "Pat Example"}), ("/api/demo/load", None)):
            assert (await api.c.post(url, json=body, headers=api.h("patient"))).status_code == 403, url
        # a doctor reads scans but never uploads them: only an administrator can
        r = await api.c.post("/api/scans/batch", files=[("files", ("a.png", png(), "image/png"))], data={"doctor_id": api.doctor_id, "patient_name": "X"}, headers=api.h("doctor"))
        assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN"
    run(scenario)


def test_patient_sees_only_their_own_doctor_finalized_report():
    async def scenario(api):
        await api.approve_doctor()
        other_token, other_id = await api.register_verified("other@test.local", full_name="Other Patient")
        (mine,) = await api.upload(["glioma_mine.png"], patient_id=api.patient_id, clinical_concern="Headaches for two weeks", exam_type="MRI Brain with contrast")
        (theirs,) = await api.upload(["meningioma_other.png"], patient_id=other_id)
        await api.process()

        rows = (await api.c.get("/api/my/scans", headers=api.h("patient"))).json()["scans"]
        assert [r["id"] for r in rows] == [mine["id"]]  # never another patient's examination
        assert rows[0]["stage"] == "Awaiting doctor review" and "report" not in rows[0]
        assert rows[0]["clinical_concern"] == "Headaches for two weeks" and rows[0]["exam_type"] == "MRI Brain with contrast"
        assert not ({"prediction", "tier", "reasons", "verifier", "storage_path"} & set(rows[0]))
        for url in ("/api/queue", f"/api/scans/{mine['id']}", "/api/audit", "/api/metrics", f"/api/scans/{mine['id']}/heatmap", f"/api/scans/{mine['id']}/report"):
            assert (await api.c.get(url, headers=api.h("patient"))).status_code == 403, url
        for url in (f"/api/scans/{theirs['id']}/image", f"/api/scans/{theirs['id']}/pdf"):
            assert (await api.c.get(url, headers=api.h("patient"))).status_code == 403, url
        assert (await api.c.post(f"/api/my/scans/{theirs['id']}/opened", headers=api.h("patient"))).status_code == 403
        assert (await api.c.get(f"/api/scans/{mine['id']}/pdf", headers=api.h("patient"))).json()["code"] == "NOT_RELEASED"

        await api.review(mine["id"], size_mm=20, location="left frontal lobe")
        await api.draft(mine["id"])
        rows = (await api.c.get("/api/my/scans", headers=api.h("patient"))).json()["scans"]
        assert "report" not in rows[0] and rows[0]["stage"] == "Report under physician review"  # drafted, not finalized
        await api.sign(mine["id"])

        rows = (await api.c.get("/api/my/scans", headers=api.h("patient"))).json()["scans"]
        rep = rows[0]["report"]
        assert rows[0]["stage"] == "Report finalized" and rep["approved_finding"] == "Glioma" and rep["status"] == "Approved and finalized"
        assert rep["report_no"].startswith("NQ-") and rep["signed_by_name"] == "Dr Ada Reader"
        assert [x["id"] for x in rep["sections"]] == ["visit", "found", "result", "tests", "treatment", "medicines", "next", "follow_up", "notes", "help"]
        assert not ({"probs", "prediction", "clinical_text", "check", "sources", "patient_summary"} & set(rep))
        assert (await api.c.get(f"/api/scans/{mine['id']}/pdf", headers=api.h("patient"))).content[:5] == b"%PDF-"
        assert (await api.c.post(f"/api/my/scans/{mine['id']}/opened", headers=api.h("patient"))).status_code == 200
        assert (await api.c.get(f"/api/scans/{mine['id']}/pdf", headers={"Authorization": f"Bearer {other_token}"})).status_code == 403
        events = (await api.c.get("/api/audit", params={"action": "PATIENT_ACCESSED_REPORT"}, headers=api.h("doctor"))).json()["events"]
        assert sorted(e["details"]["how"] for e in events) == ["pdf", "view"]
    run(scenario)


def test_patient_view_never_contains_ai_output():
    scan = {"id": "1", "filename": "f", "uploaded_at": "t", "patient_id": "p", "patient_name": "n", "status": "classified", "tier": "URGENT",
            "prediction": {"top_class": "glioma"}, "reasons": ["CONFIDENT_TUMOR"], "verifier": {}, "storage_path": "x", "heatmap_path": "h"}
    assert not ({"tier", "prediction", "reasons", "verifier", "storage_path", "heatmap_path"} & set(scan_for_patient(scan)))


def test_requests_without_a_session_are_rejected():
    async def scenario(api):
        for url in ("/api/queue", "/api/audit", "/api/metrics", "/api/my/scans", "/api/users"):
            r = await api.c.get(url)
            assert r.status_code == 401 and r.json()["code"] == "NOT_AUTHENTICATED", url
        assert (await api.c.get("/api/health")).json()["status"] == "ok"
    run(scenario)


def test_help_assistant_streams_and_audit_chain_stays_valid_under_concurrency():
    async def scenario(api):
        await api.approve_doctor()
        r = await api.c.post("/api/assist/chat", json={"messages": [{"role": "user", "content": "What does Routine mean?"}]})
        lines = [l for l in r.text.splitlines() if l]
        assert r.status_code == 200 and len(lines) > 3 and '"done": true' in lines[-1]
        await api.upload([f"glioma_{i}.png" for i in range(8)])
        await api.process()  # eight scans classified concurrently, all appending audit events
        chain = verify_chain(await get_store().audit_list())
        assert chain["ok"] and chain["count"] >= 8 * 3
    run(scenario)


def test_a_language_model_verdict_is_never_shown_on_a_report_even_if_one_is_in_storage():
    async def scenario(api):
        await api.approve_doctor()
        (scan,) = await api.upload(["pituitary_x.png"])
        await api.process()
        await api.review(scan["id"], size_mm=12, location="sellar region")
        report = await api.draft(scan["id"])
        assert [r["id"] for r in report["check"]["rows"]] == ["REVIEW", "TUMOR_TYPE", "MEASUREMENTS", "LOCATION", "LANGUAGE", "STATEMENTS"]
        legacy = {"id": "LLM", "label": "Qwen second reviewer (contradictions and invented details)", "status": "fail",
                  "issues": [{"code": "CONTRADICTION", "where": "clinical", "quote": "pituitary tumor", "detail": "old data"}]}
        stored = await get_store().get("reports", report["id"])
        await get_store().update("reports", report["id"], {"check": {**stored["check"], "rows": stored["check"]["rows"] + [legacy], "issues": legacy["issues"], "passed": False}})
        for url in (f"/api/scans/{scan['id']}/report", f"/api/scans/{scan['id']}"):
            body = (await api.c.get(url, headers=api.h("doctor"))).json()["report"]
            assert "LLM" not in [r["id"] for r in body["check"]["rows"]] and body["check"]["issues"] == [] and "Qwen" not in str(body["check"])
    run(scenario)


# ---------------- administrator uploads, assigned doctor reads ----------------
def test_admin_upload_assigns_one_doctor_and_only_that_doctor_can_read_and_report():
    async def scenario(api):
        await api.approve_doctor()
        other, other_id = await api.register_verified("doc2@test.local", "doctor", full_name="Dr Bo Other", license_no="MED-2", specialty="Radiology")
        api.tokens["other"] = other
        files = [("files", (n, png(60 + 9 * i), "image/png")) for i, n in enumerate(["glioma_a.png", "meningioma_b.png", "no_tumor_c.png"])]
        base = {"patient_id": api.patient_id}

        # a doctor and a patient must both be chosen, and the doctor must be approved
        r = await api.c.post("/api/scans/batch", files=files, data=base, headers=api.h("admin"))
        assert r.status_code == 422 and r.json()["code"] == "DOCTOR_REQUIRED"
        r = await api.c.post("/api/scans/batch", files=files, data={"doctor_id": api.doctor_id}, headers=api.h("admin"))
        assert r.status_code == 422 and r.json()["code"] == "PATIENT_REQUIRED"
        r = await api.c.post("/api/scans/batch", files=files, data={**base, "doctor_id": other_id}, headers=api.h("admin"))
        assert r.status_code == 409 and r.json()["code"] == "DOCTOR_NOT_APPROVED"
        r = await api.c.post("/api/scans/batch", files=files, data={**base, "doctor_id": api.patient_id}, headers=api.h("admin"))
        assert r.status_code == 404 and r.json()["code"] == "DOCTOR_NOT_FOUND"
        assert (await api.c.post(f"/api/users/{other_id}/status", json={"status": "approved"}, headers=api.h("admin"))).status_code == 200

        # several scans in one upload, all linked to the chosen doctor and patient
        r = await api.c.post("/api/scans/batch", files=files, data={**base, "doctor_id": api.doctor_id}, headers=api.h("admin"))
        scans = r.json()["scans"]
        assert r.status_code == 200 and len(scans) == 3
        assert all(s["assigned_doctor_id"] == api.doctor_id and s["assigned_doctor_name"] == "Dr Ada Reader" and s["patient_id"] == api.patient_id
                   and s["uploaded_by_name"] == "NeuroQueue Admin" for s in scans)

        # the administrator starts the trained model; no language model is involved (covered elsewhere)
        r = await api.c.post("/api/queue/process", json={}, headers=api.h("admin"))
        assert r.status_code == 200
        await hub.wait_idle()
        sid = scans[0]["id"]

        # the assigned doctor sees them; another approved doctor sees and can touch nothing
        assert len(await api.queue()) == 3
        assert (await api.c.get("/api/queue", headers=api.h("other"))).json()["scans"] == []
        assert len((await api.c.get("/api/queue", headers=api.h("admin"))).json()["scans"]) == 3
        for url in (f"/api/scans/{sid}", f"/api/scans/{sid}/image", f"/api/scans/{sid}/heatmap", f"/api/scans/{sid}/report", f"/api/scans/{sid}/pdf"):
            assert (await api.c.get(url, headers=api.h("other"))).status_code == 403, url
        for url, body in ((f"/api/scans/{sid}/review", {"decision": "confirm"}), (f"/api/scans/{sid}/draft", {}), (f"/api/scans/{sid}/classify", {}),
                          (f"/api/scans/{sid}/sign", {"reviewer": "Dr Bo Other"}), (f"/api/scans/{sid}/explain", {})):
            r = await api.c.post(url, json=body, headers=api.h("other"))
            assert r.status_code == 403 and r.json()["code"] == "NOT_ASSIGNED", url
        assert (await api.c.get("/api/stats/overview", headers=api.h("other"))).json()["total_scans"] == 0
        assert (await api.c.get("/api/stats/overview", headers=api.h("doctor"))).json()["total_scans"] == 3
        assert [e for e in (await api.c.get("/api/audit", headers=api.h("other"))).json()["events"] if e["scan_id"]] == []

        # administrators assign and read, but never review or sign
        assert (await api.c.post(f"/api/scans/{sid}/review", json={"decision": "confirm"}, headers=api.h("admin"))).status_code == 403
        # doctors cannot list patients or doctors, or assign scans
        for url in ("/api/patients", "/api/doctors"):
            assert (await api.c.get(url, headers=api.h("doctor"))).status_code == 403
        assert (await api.c.post(f"/api/scans/{sid}/assign", json={"doctor_id": api.doctor_id}, headers=api.h("doctor"))).status_code == 403
        assert [d["full_name"] for d in (await api.c.get("/api/doctors", headers=api.h("admin"))).json()["doctors"]] == ["Dr Ada Reader", "Dr Bo Other"]

        # reassignment moves the scan; after a review it stays with the reviewing doctor
        r = await api.c.post(f"/api/scans/{scans[1]['id']}/assign", json={"doctor_id": other_id}, headers=api.h("admin"))
        assert r.status_code == 200 and r.json()["scan"]["assigned_doctor_name"] == "Dr Bo Other"
        assert len(await api.queue()) == 2 and len((await api.c.get("/api/queue", headers=api.h("other"))).json()["scans"]) == 1
        assert (await api.review(sid, size_mm=20, location="left frontal lobe")).status_code == 200
        r = await api.c.post(f"/api/scans/{sid}/assign", json={"doctor_id": other_id}, headers=api.h("admin"))
        assert r.status_code == 409 and r.json()["code"] == "ALREADY_REVIEWED"

        # the assigned doctor's review produces the report, and the linked patient receives it with their doctor's name
        report = await api.draft(sid)
        assert report["status"] == "passed", report["check"]["issues"]
        assert (await api.sign(sid)).status_code == 200
        mine = (await api.c.get("/api/my/scans", headers=api.h("patient"))).json()["scans"]
        assert len(mine) == 3 and all(m["doctor_name"] in ("Dr Ada Reader", "Dr Bo Other") for m in mine)
        assert next(m for m in mine if m["id"] == sid)["report"]["signed_by_name"] == "Dr Ada Reader"
        assert (await api.c.get("/api/audit", headers=api.h("admin"))).json()["chain"]["ok"]
    run(scenario)


def test_demo_set_is_loaded_by_an_admin_for_a_chosen_doctor():
    async def scenario(api):
        await api.approve_doctor()
        assert (await api.c.post("/api/demo/load", json={"doctor_id": api.doctor_id}, headers=api.h("doctor"))).status_code == 403
        r = await api.c.post("/api/demo/load", json={"doctor_id": api.doctor_id}, headers=api.h("admin"))
        assert r.status_code in (200, 409)   # 409 only when the demo images have not been generated
        if r.status_code == 200:
            assert all(s["assigned_doctor_id"] == api.doctor_id for s in r.json()["scans"])
    run(scenario)
