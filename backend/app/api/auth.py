"""Sign-up, sign-in (email + password, Google), email verification, password reset and user administration.

Responses to sign-up, resend and forgot-password are identical whether or not an
account exists, so they cannot be used to find out who has an account.
"""
from __future__ import annotations

import hmac
import re

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app import auth
from app.config import get_settings
from app.errors import ApiError
from app.realtime import hub
from app.services import accounts
from app.services.audit import now_iso
from app.services.pipeline import audit
from app.store import get_store

router = APIRouter(prefix="/api", tags=["auth"])
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
GENERIC_SIGNUP = {"ok": True, "message": "Check your email. If this address can be registered, we have sent a link to verify it."}
GENERIC_SENT = {"ok": True, "message": "If an account exists for this email, you will receive further instructions."}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterIn(Strict):
    email: str = Field(max_length=160)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=120)
    role: str
    phone: str | None = Field(default=None, max_length=40)
    date_of_birth: str | None = Field(default=None, max_length=10)
    gender: str | None = Field(default=None, max_length=20)
    specialty: str | None = Field(default=None, max_length=80)
    license_no: str | None = Field(default=None, max_length=60)
    hospital: str | None = Field(default=None, max_length=120)
    admin_code: str | None = Field(default=None, max_length=64)


class LoginIn(Strict):
    email: str = Field(max_length=160)
    password: str = Field(max_length=128)
    role: str | None = None


class GoogleIn(Strict):
    credential: str = Field(min_length=20, max_length=4096)
    role: str = "patient"
    specialty: str | None = Field(default=None, max_length=80)
    license_no: str | None = Field(default=None, max_length=60)
    hospital: str | None = Field(default=None, max_length=120)
    admin_code: str | None = Field(default=None, max_length=64)


class EmailIn(Strict):
    email: str = Field(max_length=160)


class TokenIn(Strict):
    token: str = Field(min_length=10, max_length=200)


class ResetIn(TokenIn):
    password: str = Field(min_length=8, max_length=128)


class ChangePasswordIn(Strict):
    current_password: str = Field(default="", max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ProfileIn(Strict):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    date_of_birth: str | None = Field(default=None, max_length=10)
    gender: str | None = Field(default=None, max_length=20)
    specialty: str | None = Field(default=None, max_length=80)
    hospital: str | None = Field(default=None, max_length=120)


class DecisionIn(Strict):
    status: str  # approved | rejected | disabled


def _ip(request: Request) -> str:
    return auth.client_ip(request)


def _role_rules(role: str, license_no: str | None, specialty: str | None, admin_code: str | None) -> str:
    """Returns the initial account status for the role, or raises."""
    if role not in auth.ROLES:
        raise ApiError(422, "INVALID_ROLE", "Choose patient, doctor or admin.")
    if role == "doctor":
        if not (license_no and specialty):
            raise ApiError(422, "MISSING_CREDENTIALS", "Doctors must give a medical licence number and specialty.",
                           "An administrator uses these to verify your registration.")
        return "pending"
    if role == "admin":
        code = get_settings().admin_invite_code
        if not code or not hmac.compare_digest(admin_code or "", code):
            raise ApiError(403, "INVALID_ADMIN_CODE", "The administrator access code is not correct.",
                           "Ask the system owner for the administrator access code.")
    return "approved"


@router.post("/auth/register")
async def register(body: RegisterIn, request: Request):
    """Creates the account unverified and emails a verification link. No session is issued here."""
    accounts.rate_limit(f"register:{_ip(request)}", 8, 600)
    if not EMAIL_RE.match(body.email):
        raise ApiError(422, "INVALID_EMAIL", "Enter a valid email address.")
    status = _role_rules(body.role, body.license_no, body.specialty, body.admin_code)
    existing = await auth.find_by_email(body.email)
    if existing:
        if not existing.get("email_verified"):   # let a stuck sign-up finish, without saying so
            await accounts.send_verification(existing)
        return GENERIC_SIGNUP
    user = await auth.create_user(email=body.email, password=body.password, full_name=body.full_name, role=body.role, status=status,
                                  phone=body.phone, date_of_birth=body.date_of_birth, gender=body.gender, specialty=body.specialty,
                                  license_no=body.license_no, hospital=body.hospital)
    await accounts.send_verification(user)
    await audit("USER_REGISTERED", user, details={"role": user["role"], "status": status, "email_verified": False})
    await hub.publish({"type": "user_updated", "user": auth.public_user(user)}, roles=("admin",))
    return GENERIC_SIGNUP


@router.post("/auth/verify-email")
async def verify_email(body: TokenIn, request: Request, response: Response):
    accounts.rate_limit(f"verify:{_ip(request)}", 20, 600)
    user = await accounts.consume_token(body.token, "verify_email")
    user = await get_store().update("users", user["id"], {"email_verified": True})
    await audit("EMAIL_VERIFIED", user)
    await hub.publish({"type": "user_updated", "user": auth.public_user(user)}, roles=("admin",))
    auth.set_session(response, user)   # the link proves control of the mailbox
    return {"user": auth.public_user(user)}


@router.post("/auth/resend-verification")
async def resend_verification(body: EmailIn, request: Request):
    accounts.rate_limit(f"resend:{_ip(request)}", 5, 600)
    accounts.rate_limit(f"resend:{body.email.lower()}", 3, 600)
    user = await auth.find_by_email(body.email)
    if user and not user.get("email_verified"):
        await accounts.send_verification(user)
    return GENERIC_SENT


@router.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response):
    accounts.rate_limit(f"login:{_ip(request)}", 20, 300)
    accounts.check_lock(body.email)
    user = await auth.find_by_email(body.email)
    if not user or not auth.verify_password(body.password, user.get("password_hash")):
        accounts.record_failure(body.email)
        raise ApiError(401, "INVALID_CREDENTIALS", "Email or password is not correct.", "Check both and try again.")
    accounts.clear_failures(body.email)
    # From here on the caller has proved they know the password, so specific messages reveal nothing new.
    if body.role and user["role"] != body.role:
        raise ApiError(403, "WRONG_PORTAL", f"This account is a {user['role']} account.", f"Use the {user['role']} sign-in tab.")
    if user["status"] == "disabled":
        raise ApiError(403, "ACCOUNT_DISABLED", "This account has been disabled.", "Contact support.")
    if user["status"] == "rejected":
        raise ApiError(403, "REGISTRATION_REJECTED", "Your registration was not approved.", "Contact support if you think this is a mistake.")
    if not user.get("email_verified"):
        raise ApiError(403, "EMAIL_NOT_VERIFIED", "Verify your email address before signing in.", "Open the link we emailed you, or request a new one.")
    auth.set_session(response, user)
    return {"user": auth.public_user(user)}


@router.post("/auth/google")
async def google(body: GoogleIn, request: Request, response: Response):
    """Continue with Google, for both sign-up and sign-in. The ID token is verified on the server."""
    accounts.rate_limit(f"google:{_ip(request)}", 20, 300)
    g = accounts.verify_google_credential(body.credential)
    store = get_store()
    by_sub = await store.select("users", {"google_sub": g["sub"]}, limit=1)
    user = by_sub[0] if by_sub else await auth.find_by_email(g["email"])
    if user:
        # Same address, already ours: link rather than duplicate. Safe because Google has verified the address.
        if not user.get("google_sub") or not user.get("email_verified"):
            user = await store.update("users", user["id"], {"google_sub": g["sub"], "email_verified": True})
            await audit("GOOGLE_LINKED", user)
    else:
        status = _role_rules(body.role, body.license_no, body.specialty, body.admin_code)
        user = await auth.create_user(email=g["email"], password=None, full_name=g["name"], role=body.role, status=status, email_verified=True,
                                      google_sub=g["sub"], specialty=body.specialty, license_no=body.license_no, hospital=body.hospital)
        await audit("USER_REGISTERED", user, details={"role": user["role"], "status": status, "via": "google"})
        await hub.publish({"type": "user_updated", "user": auth.public_user(user)}, roles=("admin",))
    if user["status"] in ("disabled", "rejected"):
        raise ApiError(403, "ACCOUNT_DISABLED", "This account is not available.", "Contact support.")
    auth.set_session(response, user)
    return {"user": auth.public_user(user)}


@router.post("/auth/forgot-password")
async def forgot_password(body: EmailIn, request: Request):
    accounts.rate_limit(f"forgot:{_ip(request)}", 5, 600)
    accounts.rate_limit(f"forgot:{body.email.lower()}", 3, 600)
    user = await auth.find_by_email(body.email)
    if user and user["status"] not in ("disabled", "rejected"):
        await accounts.send_reset(user)
    return GENERIC_SENT


@router.post("/auth/reset-password")
async def reset_password(body: ResetIn, request: Request, response: Response):
    accounts.rate_limit(f"reset:{_ip(request)}", 10, 600)
    user = await accounts.consume_token(body.token, "reset_password")
    # Receiving the reset link also proves control of the mailbox. Every existing session is ended.
    user = await get_store().update("users", user["id"], {"password_hash": auth.hash_password(body.password), "email_verified": True,
                                                         "session_version": int(user.get("session_version") or 0) + 1})
    accounts.clear_failures(user["email"])
    await audit("PASSWORD_RESET", user)
    auth.clear_session(response)
    return {"ok": True, "message": "Your password has been changed. Sign in with the new password."}


@router.post("/auth/change-password")
async def change_password(body: ChangePasswordIn, request: Request, response: Response, user: dict = Depends(auth.current_user)):
    accounts.rate_limit(f"changepw:{user['id']}", 5, 600)
    if user.get("password_hash") and not auth.verify_password(body.current_password, user["password_hash"]):
        raise ApiError(403, "WRONG_PASSWORD", "Your current password is not correct.")
    user = await get_store().update("users", user["id"], {"password_hash": auth.hash_password(body.new_password),
                                                         "session_version": int(user.get("session_version") or 0) + 1})
    await audit("PASSWORD_CHANGED", user)
    auth.set_session(response, user)   # other devices are signed out; this one continues
    return {"ok": True}


@router.post("/auth/logout")
async def logout(response: Response):
    auth.clear_session(response)
    return {"ok": True}


@router.post("/auth/logout-all")
async def logout_all(response: Response, user: dict = Depends(auth.current_user)):
    await auth.end_all_sessions(user)
    auth.clear_session(response)
    return {"ok": True}


@router.post("/auth/ws-ticket")
async def ws_ticket(user: dict = Depends(auth.current_user)):
    """A one-time, 30-second ticket to open the live connection. Never the session token."""
    return {"ticket": auth.issue_ws_ticket(user)}


@router.get("/auth/me")
async def me(user: dict = Depends(auth.current_user)):
    return {"user": auth.public_user(user)}


@router.patch("/auth/me")
async def update_me(body: ProfileIn, user: dict = Depends(auth.current_user)):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if patch:
        user = await get_store().update("users", user["id"], patch)
    return {"user": auth.public_user(user)}


# ---------------- administration ----------------
@router.get("/users")
async def list_users(role: str | None = None, status: str | None = None, _: dict = Depends(auth.admin_only)):
    where = {k: v for k, v in {"role": role, "status": status}.items() if v}
    rows = await get_store().select("users", where, order="created_at", desc=True)
    return {"users": [auth.public_user(u) for u in rows]}


@router.get("/patients")
async def list_patients(_: dict = Depends(auth.admin_only)):
    rows = await get_store().select("users", {"role": "patient"}, order="full_name")
    return {"patients": [{"id": u["id"], "full_name": u["full_name"], "email": u["email"]} for u in rows if u.get("email_verified") and u["status"] == "approved"]}


@router.get("/doctors")
async def list_doctors(_: dict = Depends(auth.admin_only)):
    """Doctors a scan can be assigned to: approved and email-verified."""
    rows = await get_store().select("users", {"role": "doctor"}, order="full_name")
    return {"doctors": [{"id": u["id"], "full_name": u["full_name"], "email": u["email"], "specialty": u.get("specialty"), "hospital": u.get("hospital")}
                        for u in rows if u.get("email_verified") and u["status"] == "approved"]}


@router.post("/users/{user_id}/status")
async def set_status(user_id: str, body: DecisionIn, admin: dict = Depends(auth.admin_only)):
    if body.status not in ("approved", "rejected", "disabled"):
        raise ApiError(422, "INVALID_STATUS", "Status must be approved, rejected or disabled.")
    target = await get_store().get("users", user_id)
    if not target:
        raise ApiError(404, "USER_NOT_FOUND", "That user does not exist.")
    if target["id"] == admin["id"]:
        raise ApiError(409, "CANNOT_CHANGE_SELF", "You cannot change your own account status.", "Ask another administrator.")
    patch = {"status": body.status}
    if body.status == "approved":
        patch.update({"approved_at": now_iso(), "approved_by_name": admin["full_name"]})
    else:
        patch["session_version"] = int(target.get("session_version") or 0) + 1   # sign the account out everywhere
    target = await get_store().update("users", user_id, patch)
    await audit(f"USER_{body.status.upper()}", admin, details={"user_id": user_id, "role": target["role"]})
    await hub.publish({"type": "user_updated", "user": auth.public_user(target)}, roles=("admin",), user_ids=(user_id,))
    return {"user": auth.public_user(target)}


@router.get("/dev/outbox")
async def dev_outbox(_: dict = Depends(auth.admin_only)):
    """Development aid: when no mail server is configured, the emails that would have been sent. Disabled once SMTP is set."""
    if accounts.smtp_configured():
        raise ApiError(404, "NOT_FOUND", "Not available: a mail server is configured.")
    return {"emails": list(accounts.DEV_OUTBOX), "note": "No SMTP server is configured, so verification and reset emails are kept here instead of being sent."}
