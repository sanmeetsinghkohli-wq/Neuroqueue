"""Create the demo accounts from backend/.env (idempotent).

    python seed.py            # admin + approved demo doctor + demo patient

Credentials are read from the environment and never printed.
"""
from __future__ import annotations

import asyncio
import os

from app import auth
from app.config import get_settings
from app.services.audit import new_event, now_iso
from app.store import get_store


async def ensure(email: str, password: str, **kw) -> str:
    if not (email and password):
        return "skipped (not configured)"
    if await auth.find_by_email(email):
        return "already exists"
    user = await auth.create_user(email=email, password=password, **kw)
    await get_store().audit_append(new_event("USER_REGISTERED", user, details={"role": user["role"], "seed": True}))
    return "created"


async def main() -> None:
    store = get_store()
    await store.start()
    await auth.ensure_admin()
    print(f"store: {store.name}")
    print(f"admin   {get_settings().admin_email}: ready")
    print("doctor  " + os.getenv("DEMO_DOCTOR_EMAIL", "") + ": " + await ensure(
        os.getenv("DEMO_DOCTOR_EMAIL", ""), os.getenv("DEMO_DOCTOR_PASSWORD", ""), full_name="Dr. Maya Chen", role="doctor",
        status="approved", email_verified=True, specialty="Neuroradiology", license_no="DEMO-0001", hospital="NeuroQueue Demo Hospital",
        approved_at=now_iso(), approved_by_name="seed"))
    print("patient " + os.getenv("DEMO_PATIENT_EMAIL", "") + ": " + await ensure(
        os.getenv("DEMO_PATIENT_EMAIL", ""), os.getenv("DEMO_PATIENT_PASSWORD", ""), full_name="Alex Rivera", role="patient", status="approved", email_verified=True))
    print("Passwords are in backend/.env")
    await store.stop()


if __name__ == "__main__":
    asyncio.run(main())
