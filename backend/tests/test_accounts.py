"""Authentication, account security and the two report versions. Mock mode, no network."""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

from app.services import accounts
from app.services.patient_report import build_patient_report
from app.store import get_store
from tests.conftest import png, run

PW = "a-long-password-1"


def pdf_text(data: bytes) -> str:
    import pymupdf
    return " ".join(page.get_text() for page in pymupdf.open(stream=io.BytesIO(data).read(), filetype="pdf"))


# ---------------- sign-up and email verification ----------------
def test_signup_creates_an_unverified_account_and_issues_no_session():
    async def scenario(api):
        r = await api.c.post("/api/auth/register", json={"email": "new@test.local", "password": PW, "full_name": "New User", "role": "patient"})
        assert r.status_code == 200 and "nq_session" not in r.cookies and "token" not in r.json() and "user" not in r.json()
        user = (await get_store().select("users", {"email": "new@test.local"}))[0]
        assert user["email_verified"] is False
        r = await api.c.post("/api/auth/login", json={"email": "new@test.local", "password": PW})
        assert r.status_code == 403 and r.json()["code"] == "EMAIL_NOT_VERIFIED" and "nq_session" not in r.cookies
    run(scenario)


def test_verification_link_works_once_and_then_sign_in_is_allowed():
    async def scenario(api):
        await api.c.post("/api/auth/register", json={"email": "new@test.local", "password": PW, "full_name": "New User", "role": "patient"})
        token = api.emailed_token("new@test.local")
        r = await api.c.post("/api/auth/verify-email", json={"token": token})
        assert r.status_code == 200 and r.json()["user"]["email_verified"] is True
        api.c.cookies.clear()
        assert (await api.c.post("/api/auth/verify-email", json={"token": token})).json()["code"] == "LINK_USED"
        assert (await api.c.post("/api/auth/verify-email", json={"token": "not-a-real-token-at-all"})).json()["code"] == "LINK_INVALID"
        r = await api.c.post("/api/auth/login", json={"email": "new@test.local", "password": PW})
        assert r.status_code == 200 and "nq_session" in r.cookies
    run(scenario)


def test_expired_verification_link_is_refused_and_a_resend_replaces_it():
    async def scenario(api):
        await api.c.post("/api/auth/register", json={"email": "new@test.local", "password": PW, "full_name": "New User", "role": "patient"})
        first = api.emailed_token("new@test.local")
        store = get_store()
        tok = (await store.select("auth_tokens", {"kind": "verify_email"}))[-1]
        await store.update("auth_tokens", tok["id"], {"expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()})
        assert (await api.c.post("/api/auth/verify-email", json={"token": first})).json()["code"] == "LINK_EXPIRED"
        assert (await api.c.post("/api/auth/resend-verification", json={"email": "new@test.local"})).status_code == 200
        second = api.emailed_token("new@test.local")
        assert second != first
        assert (await api.c.post("/api/auth/verify-email", json={"token": second})).status_code == 200
    run(scenario)


def test_signup_resend_and_forgot_do_not_reveal_whether_an_account_exists():
    async def scenario(api):
        body = {"password": PW, "full_name": "Some One", "role": "patient"}
        fresh = await api.c.post("/api/auth/register", json={**body, "email": "fresh@test.local"})
        taken = await api.c.post("/api/auth/register", json={**body, "email": "pat@test.local"})
        assert fresh.status_code == taken.status_code == 200 and fresh.json() == taken.json()
        assert len(await get_store().select("users", {"email": "pat@test.local"})) == 1
        for url in ("/api/auth/forgot-password", "/api/auth/resend-verification"):
            known = await api.c.post(url, json={"email": "pat@test.local"})
            unknown = await api.c.post(url, json={"email": "nobody@test.local"})
            assert known.status_code == unknown.status_code == 200 and known.json() == unknown.json(), url
        wrong_pw = await api.c.post("/api/auth/login", json={"email": "pat@test.local", "password": "wrong-password"})
        no_user = await api.c.post("/api/auth/login", json={"email": "nobody@test.local", "password": "wrong-password"})
        assert wrong_pw.status_code == no_user.status_code == 401 and wrong_pw.json() == no_user.json()
    run(scenario)


def test_role_rules_still_apply_at_signup():
    async def scenario(api):
        post = lambda body: api.c.post("/api/auth/register", json={"password": PW, "full_name": "Some One", **body})  # noqa: E731
        assert (await post({"email": "d2@test.local", "role": "doctor"})).json()["code"] == "MISSING_CREDENTIALS"
        assert (await post({"email": "a2@test.local", "role": "admin", "admin_code": "WRONG"})).json()["code"] == "INVALID_ADMIN_CODE"
        assert (await post({"email": "a2@test.local", "role": "admin", "admin_code": "INVITE"})).status_code == 200
        assert (await post({"email": "x@test.local", "role": "patient", "is_admin": True})).status_code == 422   # unexpected fields are rejected
        r = await api.c.post("/api/auth/login", json={"email": "pat@test.local", "password": PW, "role": "doctor"})
        assert r.json()["code"] == "WRONG_PORTAL"
    run(scenario)


# ---------------- sessions ----------------
def test_session_cookie_is_httponly_and_the_token_never_appears_in_a_response_body():
    async def scenario(api):
        r = await api.c.post("/api/auth/login", json={"email": "pat@test.local", "password": PW})
        cookie = r.headers["set-cookie"].lower()
        assert "nq_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
        assert r.cookies["nq_session"] not in r.text and "password_hash" not in r.text
        me = await api.c.get("/api/auth/me")   # the cookie alone authenticates
        assert me.status_code == 200 and me.json()["user"]["email"] == "pat@test.local"
        out = await api.c.post("/api/auth/logout")
        assert out.status_code == 200 and 'nq_session=""' in out.headers["set-cookie"]
        api.c.cookies.clear()
        assert (await api.c.get("/api/auth/me")).status_code == 401
    run(scenario)


def test_a_token_in_the_url_is_never_accepted():
    async def scenario(api):
        for url in ("/api/auth/me", "/api/my/scans"):
            assert (await api.c.get(url, params={"t": api.tokens["patient"], "token": api.tokens["patient"]})).status_code == 401
    run(scenario)


def test_requests_from_another_site_are_refused():
    async def scenario(api):
        evil = {"Origin": "https://evil.example", **api.h("patient")}
        r = await api.c.post("/api/auth/logout-all", headers=evil)
        assert r.status_code == 403 and r.json()["code"] == "BAD_ORIGIN"
        ok = await api.c.post("/api/support/contact", json={"name": "Pat", "email": "p@test.local", "message": "hello there"}, headers={"Origin": "http://localhost:3000"})
        assert ok.status_code == 200
        pre = await api.c.options("/api/queue", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
        assert "access-control-allow-origin" not in pre.headers
        good = await api.c.get("/api/health", headers={"Origin": "http://localhost:3000"})
        assert good.headers["access-control-allow-origin"] == "http://localhost:3000" and good.headers["access-control-allow-credentials"] == "true"
        assert good.headers["x-content-type-options"] == "nosniff" and good.headers["cache-control"] == "no-store" and good.headers["x-frame-options"] == "DENY"
    run(scenario)


def test_repeated_wrong_passwords_lock_sign_in_even_with_the_right_password():
    async def scenario(api):
        for _ in range(5):
            assert (await api.c.post("/api/auth/login", json={"email": "pat@test.local", "password": "wrong"})).status_code == 401
        r = await api.c.post("/api/auth/login", json={"email": "pat@test.local", "password": PW})
        assert r.status_code == 429 and r.json()["code"] == "TOO_MANY_ATTEMPTS"
    run(scenario)


def test_reset_and_verification_requests_are_rate_limited():
    async def scenario(api):
        codes = [(await api.c.post("/api/auth/forgot-password", json={"email": "pat@test.local"})).status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]
    run(scenario)


# ---------------- password reset and change ----------------
def test_password_reset_is_single_use_and_ends_existing_sessions():
    async def scenario(api):
        assert (await api.c.get("/api/auth/me", headers=api.h("patient"))).status_code == 200
        await api.c.post("/api/auth/forgot-password", json={"email": "pat@test.local"})
        token = api.emailed_token("pat@test.local")
        r = await api.c.post("/api/auth/reset-password", json={"token": token, "password": "a-brand-new-password-2"})
        assert r.status_code == 200 and "nq_session" not in r.cookies
        assert (await api.c.post("/api/auth/reset-password", json={"token": token, "password": "another-password-3"})).json()["code"] == "LINK_USED"
        assert (await api.c.get("/api/auth/me", headers=api.h("patient"))).status_code == 401          # old session is dead
        assert (await api.c.post("/api/auth/login", json={"email": "pat@test.local", "password": PW})).status_code == 401
        assert (await api.c.post("/api/auth/login", json={"email": "pat@test.local", "password": "a-brand-new-password-2"})).status_code == 200
        user = (await get_store().select("users", {"email": "pat@test.local"}))[0]
        assert "a-brand-new-password-2" not in str(user) and user["password_hash"].startswith("scrypt$")
    run(scenario)


def test_expired_reset_link_is_refused():
    async def scenario(api):
        await api.c.post("/api/auth/forgot-password", json={"email": "pat@test.local"})
        token = api.emailed_token("pat@test.local")
        store = get_store()
        tok = (await store.select("auth_tokens", {"kind": "reset_password"}))[-1]
        await store.update("auth_tokens", tok["id"], {"expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()})
        assert (await api.c.post("/api/auth/reset-password", json={"token": token, "password": "a-brand-new-password-2"})).json()["code"] == "LINK_EXPIRED"
    run(scenario)


def test_change_password_needs_the_current_one_and_signs_out_other_devices():
    async def scenario(api):
        bad = await api.c.post("/api/auth/change-password", json={"current_password": "wrong", "new_password": "next-password-12"}, headers=api.h("patient"))
        assert bad.status_code == 403 and bad.json()["code"] == "WRONG_PASSWORD"
        r = await api.c.post("/api/auth/change-password", json={"current_password": PW, "new_password": "next-password-12"}, headers=api.h("patient"))
        assert r.status_code == 200
        fresh = api.session(r)
        assert (await api.c.get("/api/auth/me", headers=api.h("patient"))).status_code == 401
        assert (await api.c.get("/api/auth/me", headers={"Authorization": f"Bearer {fresh}"})).status_code == 200
    run(scenario)


def test_disabling_an_account_ends_its_sessions():
    async def scenario(api):
        await api.c.post(f"/api/users/{api.patient_id}/status", json={"status": "disabled"}, headers=api.h("admin"))
        assert (await api.c.get("/api/my/scans", headers=api.h("patient"))).status_code == 401
        assert (await api.c.post("/api/auth/login", json={"email": "pat@test.local", "password": PW})).json()["code"] == "ACCOUNT_DISABLED"
    run(scenario)


# ---------------- Google sign-in (token verification is replaced; everything else is real) ----------------
def test_google_sign_in_creates_links_and_never_duplicates(monkeypatch):
    identity = {"sub": "g-123", "email": "pat@test.local", "name": "Pat Example"}
    monkeypatch.setattr(accounts, "verify_google_credential", lambda credential: dict(identity))

    async def scenario(api):
        r = await api.c.post("/api/auth/google", json={"credential": "x" * 40})
        assert r.status_code == 200 and r.json()["user"]["id"] == api.patient_id and r.json()["user"]["google_linked"] is True
        api.c.cookies.clear()
        assert len(await get_store().select("users", {"email": "pat@test.local"})) == 1          # linked, not duplicated
        assert (await api.c.post("/api/auth/login", json={"email": "pat@test.local", "password": PW})).status_code == 200   # password still works
        api.c.cookies.clear()

        identity.update(sub="g-999", email="brand.new@test.local", name="Brand New")
        r = await api.c.post("/api/auth/google", json={"credential": "x" * 40})
        new = r.json()["user"]
        assert r.status_code == 200 and new["role"] == "patient" and new["email_verified"] is True and new["has_password"] is False
        api.c.cookies.clear()
        assert (await api.c.post("/api/auth/login", json={"email": "brand.new@test.local", "password": ""})).status_code == 401   # no password login for it
        r = await api.c.post("/api/auth/google", json={"credential": "x" * 40, "role": "doctor"})
        assert r.json()["user"]["role"] == "patient"                                               # an existing account never changes role this way
        api.c.cookies.clear()

        identity.update(sub="g-777", email="newdoc@test.local", name="New Doc")
        assert (await api.c.post("/api/auth/google", json={"credential": "x" * 40, "role": "doctor"})).json()["code"] == "MISSING_CREDENTIALS"
        r = await api.c.post("/api/auth/google", json={"credential": "x" * 40, "role": "doctor", "license_no": "L-9", "specialty": "Radiology"})
        assert r.json()["user"]["status"] == "pending"                                             # doctors still need admin approval
    run(scenario)


def test_google_sign_in_is_refused_when_not_configured_or_invalid():
    async def scenario(api):
        r = await api.c.post("/api/auth/google", json={"credential": "x" * 40})
        assert r.status_code == 503 and r.json()["code"] == "GOOGLE_NOT_CONFIGURED" and "nq_session" not in r.cookies
    run(scenario)


# ---------------- two report versions ----------------
CLINICAL = {"symptoms": "Headaches and blurred vision", "history": "Hypertension", "treatment_plan": "Refer to endocrinology and neurosurgery.",
            "follow_up": "Return in 2 weeks with blood test results.", "patient_instructions": "Book the blood test at the front desk.",
            "warning_signs": "Sudden loss of vision or a severe headache.", "notes": "Suprasellar extension suspected, discuss at MDT.",
            "medications": [{"name": "Cabergoline", "purpose": "To lower prolactin", "how_to_take": "0.5 mg tablet by mouth", "when_to_take": "Twice a week",
                             "duration": "Until review", "instructions": "Take with food"}]}


def test_doctor_and_patient_receive_different_documents_from_the_same_review():
    async def scenario(api):
        await api.approve_doctor()
        (scan,) = await api.upload(["pituitary_p.png"], patient_id=api.patient_id, clinical_concern="Headaches for three weeks")
        await api.process()
        r = await api.review(scan["id"], size_mm=14, location="sellar region", **CLINICAL)
        assert r.status_code == 200, r.text
        assert (await api.draft(scan["id"]))["status"] == "passed"
        assert (await api.sign(scan["id"])).status_code == 200

        doctor_pdf = pdf_text((await api.c.get(f"/api/scans/{scan['id']}/pdf", headers=api.h("doctor"))).content)
        patient_pdf = pdf_text((await api.c.get(f"/api/scans/{scan['id']}/pdf", headers=api.h("patient"))).content)
        assert doctor_pdf != patient_pdf

        # doctor version: clinical detail, model output, private notes
        for needle in ("CLINICAL INFORMATION", "Hypertension", "DETAILED CLASSIFICATION PROBABILITIES", "MODEL CONFIDENCE", "discuss at MDT", "Cabergoline"):
            assert needle in doctor_pdf, needle
        # patient version: its own plain-language structure, with the doctor's instructions word for word
        for needle in ("Your MRI Report", "Your Visit Summary", "What the Doctor Found", "Your Result", "Medicines", "What You Should Do Next", "Follow-Up",
                       "When to Seek Further Medical Help", "Cabergoline", "0.5 mg tablet by mouth", "Twice a week", "Return in 2 weeks with blood test results.",
                       "Sudden loss of vision or a severe headache."):
            assert needle in patient_pdf, needle
        # and nothing that is for the doctor only
        for secret in ("discuss at MDT", "MODEL CONFIDENCE", "PROBABILITIES", "Hypertension", "Licence", "RECOMMENDATIONS", "sha256", "efficientnet", "mock-classifier"):
            assert secret not in patient_pdf, secret

        # the patient cannot talk the server into the clinical version
        forced = pdf_text((await api.c.get(f"/api/scans/{scan['id']}/pdf", params={"version": "doctor"}, headers=api.h("patient"))).content)
        assert "Your MRI Report" in forced and "discuss at MDT" not in forced
        assert (await api.c.get(f"/api/scans/{scan['id']}/patient-version", headers=api.h("patient"))).status_code == 403
        assert (await api.c.get(f"/api/scans/{scan['id']}/report", headers=api.h("patient"))).status_code == 403
        api_view = (await api.c.get("/api/my/scans", headers=api.h("patient"))).text
        assert "discuss at MDT" not in api_view and "Hypertension" not in api_view and "probs" not in api_view and "Cabergoline" in api_view

        preview = pdf_text((await api.c.get(f"/api/scans/{scan['id']}/pdf", params={"version": "patient"}, headers=api.h("doctor"))).content)
        assert "Your MRI Report" in preview   # the doctor can check what the patient gets
    run(scenario)


def test_patient_report_never_invents_and_never_alters_what_the_doctor_wrote():
    scan = {"exam_type": "MRI Brain", "clinical_concern": None, "uploaded_at": "2026-10-06T09:00:00+00:00",
            "review": {"final_class": "glioma", "size_mm": None, "location": None, "medications": [{"name": "Dexamethasone", "how_to_take": "4 mg by mouth"}]}}
    pr = build_patient_report(scan, {"report_no": "NQ-1", "patient_summary": "Your doctor confirmed a glioma.", "signed_by_name": "Dr A", "signed_at": None})
    by_id = {s["id"]: s for s in pr["sections"]}
    assert "not recorded" in by_id["visit"]["text"] and by_id["found"]["facts"] == ["Size: not recorded", "Where: not recorded"]
    assert by_id["treatment"]["from_doctor"] is False and "has not recorded" in by_id["treatment"]["text"]
    med = by_id["medicines"]["medicines"][0]
    assert med["name"] == "Dexamethasone"
    assert {d["label"]: d["value"] for d in med["details"]} == {"What it is for": "Not provided", "How to take it": "4 mg by mouth", "When to take it": "Not provided",
                                                              "For how long": "Not provided", "Important instructions": "Not provided"}
    text = str(pr).lower()
    assert not any(w in text for w in ("malignan", "benign", "cancer", "prognos", "survival"))


def test_reports_finalized_before_the_patient_version_existed_still_work():
    async def scenario(api):
        await api.approve_doctor()
        (scan,) = await api.upload(["glioma_old.png"], patient_id=api.patient_id)
        await api.process()
        await api.review(scan["id"], size_mm=20, location="left frontal lobe")
        report = await api.draft(scan["id"])
        await api.sign(scan["id"])
        await get_store().update("reports", report["id"], {"patient_pdf_path": None})   # simulate an older report
        r = await api.c.get(f"/api/scans/{scan['id']}/pdf", headers=api.h("patient"))
        assert r.status_code == 200 and "Your MRI Report" in pdf_text(r.content)
    run(scenario)


def test_review_rejects_unexpected_fields_and_oversized_input():
    async def scenario(api):
        await api.approve_doctor()
        (scan,) = await api.upload(["glioma_x.png"])
        await api.process()
        assert (await api.review(scan["id"], reviewer_id="someone-else")).status_code == 422
        assert (await api.review(scan["id"], treatment_plan="x" * 5000)).status_code == 422
        assert (await api.review(scan["id"], medications=[{"name": "A", "dose_override": "10x"}])).status_code == 422
        r = await api.review(scan["id"], notes="<script>alert(1)</script>", size_mm=10, location="left frontal lobe")
        assert r.status_code == 200 and r.json()["scan"]["review"]["notes"] == "<script>alert(1)</script>"   # stored as text; the UI and PDF escape it
        await api.draft(scan["id"])
        await api.sign(scan["id"])
        assert b"%PDF-" == (await api.c.get(f"/api/scans/{scan['id']}/pdf", headers=api.h("doctor"))).content[:5]
        bad = await api.c.post("/api/scans/batch", files=[("files", ("x.png", b"<?php echo 1; ?>", "image/png"))],
                               data={"doctor_id": api.doctor_id, "patient_name": "Walk-in Patient"}, headers=api.h("admin"))
        assert bad.status_code == 422 and bad.json()["code"] == "NOT_AN_IMAGE"   # content is checked, not the extension
        assert (await api.c.get("/api/scans/..%2f..%2fetc%2fpasswd/image", headers=api.h("doctor"))).status_code == 404
    run(scenario)
