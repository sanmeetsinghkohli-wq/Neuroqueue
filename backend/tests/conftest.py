"""Test harness: mock mode, in-memory store, no network."""
from __future__ import annotations

import asyncio
import io
import os

import tempfile

os.environ["NQ_MOCK_MODE"] = "1"
os.environ["NQ_ARTIFACTS_DIR"] = tempfile.mkdtemp(prefix="nq-no-artifacts-")  # hermetic: default thresholds, no model
os.environ["ADMIN_EMAIL"] = "admin@test.local"
for _k in ("GOOGLE_CLIENT_ID", "SMTP_HOST", "SMTP_FROM", "SMTP_USER", "SMTP_PASSWORD", "MAIL_RELAY_URL", "MAIL_RELAY_SECRET", "SUPABASE_URL"):
    os.environ[_k] = ""   # tests never use the real Google client, mail server or database from backend/.env
os.environ["ADMIN_PASSWORD"] = "admin-pass-1"
os.environ["ADMIN_INVITE_CODE"] = "INVITE"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"

import httpx  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from app import auth  # noqa: E402
from app.services import accounts  # noqa: E402
from app.main import app  # noqa: E402
from app.realtime import hub  # noqa: E402
from app.services.classifier import MockClassifier, set_classifier  # noqa: E402
from app.services.qwen import MockQwen, set_qwen  # noqa: E402
from app.store import set_store  # noqa: E402
from app.store.local import LocalStore  # noqa: E402

TH = {"min_conf": 0.85, "min_margin": 0.15, "routine_conf": 0.90, "max_wait_min": 60}


def png(shade: int = 90) -> bytes:
    buf = io.BytesIO()
    Image.new("L", (64, 64), shade).save(buf, format="PNG")
    return buf.getvalue()


class Api:
    """Thin async client plus helpers for the common steps."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.c = client
        self.tokens: dict[str, str] = {}

    def h(self, who: str) -> dict:
        return {"Authorization": f"Bearer {self.tokens[who]}"}

    def session(self, r) -> str:
        """Take the session out of the Set-Cookie header and keep the shared client cookie-free,
        so each request in a test is authenticated only by the header it chooses to send."""
        token = r.cookies.get("nq_session")
        self.c.cookies.clear()
        assert token, r.text
        return token

    @staticmethod
    def emailed_token(to: str) -> str:
        """The one-time token from the most recent email 'sent' to this address."""
        mail = next(m for m in accounts.DEV_OUTBOX if m["to"] == to)
        return mail["link"].split("token=")[1]

    async def register_verified(self, email: str, role: str = "patient", **extra) -> tuple[str, str]:
        """Sign up, then follow the emailed verification link. Returns (session token, user id)."""
        body = {"email": email, "password": "a-long-password-1", "full_name": extra.pop("full_name", "Some One"), "role": role, **extra}
        r = await self.c.post("/api/auth/register", json=body)
        assert r.status_code == 200, r.text
        r = await self.c.post("/api/auth/verify-email", json={"token": self.emailed_token(email)})
        assert r.status_code == 200, r.text
        return self.session(r), r.json()["user"]["id"]

    async def setup_users(self) -> None:
        r = await self.c.post("/api/auth/login", json={"email": "admin@test.local", "password": "admin-pass-1"})
        self.tokens["admin"] = self.session(r)
        self.tokens["doctor"], self.doctor_id = await self.register_verified("doc@test.local", "doctor", full_name="Dr Ada Reader",
                                                                             license_no="MED-1", specialty="Neuroradiology")
        self.tokens["patient"], self.patient_id = await self.register_verified("pat@test.local", "patient", full_name="Pat Example")

    async def approve_doctor(self) -> None:
        r = await self.c.post(f"/api/users/{self.doctor_id}/status", json={"status": "approved"}, headers=self.h("admin"))
        assert r.status_code == 200, r.text

    async def upload(self, names: list[str], who: str = "admin", **form) -> list[dict]:
        """An administrator uploads and assigns the scans to the test doctor (and a named patient unless one is given)."""
        form.setdefault("doctor_id", self.doctor_id)
        if "patient_id" not in form:
            form.setdefault("patient_name", "Walk-in Patient")
        files = [("files", (n, png(60 + 7 * i), "image/png")) for i, n in enumerate(names)]
        r = await self.c.post("/api/scans/batch", files=files, data=form, headers=self.h(who))
        assert r.status_code == 200, r.text
        return r.json()["scans"]

    async def process(self) -> None:
        r = await self.c.post("/api/queue/process", json={}, headers=self.h("doctor"))
        assert r.status_code == 200, r.text
        await hub.wait_idle()

    async def queue(self) -> list[dict]:
        return (await self.c.get("/api/queue", headers=self.h("doctor"))).json()["scans"]

    async def review(self, scan_id: str, **body):
        return await self.c.post(f"/api/scans/{scan_id}/review", json={"decision": "confirm", **body}, headers=self.h("doctor"))

    async def draft(self, scan_id: str) -> dict:
        r = await self.c.post(f"/api/scans/{scan_id}/draft", json={}, headers=self.h("doctor"))
        assert r.status_code == 200, r.text
        await hub.wait_idle()
        return (await self.c.get(f"/api/scans/{scan_id}/report", headers=self.h("doctor"))).json()["report"]

    async def sign(self, scan_id: str, reviewer: str = "Dr Ada Reader"):
        return await self.c.post(f"/api/scans/{scan_id}/sign", json={"reviewer": reviewer}, headers=self.h("doctor"))


def run(scenario):
    """Run `async def scenario(api)` against a fresh app with an empty in-memory store."""
    async def main():
        store = LocalStore(None)
        set_store(store)
        set_classifier(MockClassifier())
        set_qwen(MockQwen())
        hub.clients.clear()
        accounts.reset_throttles()
        await store.start()
        await auth.ensure_admin()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            api = Api(client)
            await api.setup_users()
            return await scenario(api)
    return asyncio.run(main())


@pytest.fixture
def th() -> dict:
    return dict(TH)
