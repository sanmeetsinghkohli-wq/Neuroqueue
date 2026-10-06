"""Accounts, password hashing, sessions and role guards.

Sessions: a signed token in an HttpOnly cookie. JavaScript can never read it,
it is never placed in a URL, and it stops working the moment the account's
session version changes (password change, password reset, "sign out everywhere")
or the account is disabled.

Roles: patient, doctor, admin. Doctors register as `pending` and cannot reach any
clinical endpoint until an admin approves them. Every guard here runs on the
server; nothing depends on what the frontend chooses to show.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
import uuid

import jwt
from fastapi import Depends, Request, Response

from app.config import get_settings
from app.errors import ApiError
from app.services.audit import new_event, now_iso
from app.store import get_store

ROLES = ("patient", "doctor", "admin")
COOKIE = "nq_session"
PUBLIC_FIELDS = ("id", "email", "full_name", "role", "status", "phone", "specialty", "license_no", "hospital",
                 "date_of_birth", "gender", "created_at", "approved_at", "approved_by_name", "email_verified")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str | None) -> bool:
    try:
        _, salt, dk = (stored or "").split("$")
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


def public_user(u: dict) -> dict:
    out = {k: u.get(k) for k in PUBLIC_FIELDS}
    out["has_password"] = bool(u.get("password_hash"))
    out["google_linked"] = bool(u.get("google_sub"))
    return out


def make_token(user: dict) -> str:
    s = get_settings()
    return jwt.encode({"sub": user["id"], "role": user["role"], "ver": int(user.get("session_version") or 0),
                       "exp": int(time.time()) + s.token_hours * 3600}, s.secret_key, algorithm="HS256")


def set_session(response: Response, user: dict) -> None:
    """Issue a fresh session cookie. A new token on every sign-in also rules out session fixation."""
    s = get_settings()
    response.set_cookie(COOKIE, make_token(user), max_age=s.token_hours * 3600, httponly=True, secure=s.cookie_secure,
                        samesite=s.cookie_samesite, path="/")


def clear_session(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(COOKIE, path="/", secure=s.cookie_secure, samesite=s.cookie_samesite, httponly=True)


async def user_from_token(token: str | None) -> dict:
    if not token:
        raise ApiError(401, "NOT_AUTHENTICATED", "Please sign in.", "Your session is missing. Sign in again.")
    try:
        claims = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise ApiError(401, "SESSION_EXPIRED", "Your session has expired.", "Sign in again.")
    user = await get_store().get("users", claims["sub"])
    if not user or user.get("status") in ("disabled", "rejected"):
        raise ApiError(401, "ACCOUNT_UNAVAILABLE", "This account is not available.", "Contact support.")
    if int(claims.get("ver", 0)) != int(user.get("session_version") or 0):
        raise ApiError(401, "SESSION_EXPIRED", "Your session has ended.", "Sign in again.")
    if not user.get("email_verified"):
        raise ApiError(401, "EMAIL_NOT_VERIFIED", "Verify your email address to continue.", "Open the link we emailed you, or request a new one.")
    return user


def token_from_request(request: Request) -> str | None:
    """Session cookie first; an Authorization header is accepted for non-browser API clients. Never a URL parameter."""
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:]
    return request.cookies.get(COOKIE)


async def current_user(request: Request) -> dict:
    return await user_from_token(token_from_request(request))


async def optional_user(request: Request) -> dict | None:
    try:
        return await user_from_token(token_from_request(request))
    except ApiError:
        return None


def require(*roles: str):
    """Dependency: signed in, email verified, approved, and one of `roles`."""
    async def dep(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise ApiError(403, "FORBIDDEN", "You do not have access to this.", f"This area is for: {', '.join(roles)}.")
        if user.get("status") != "approved":
            raise ApiError(403, "NOT_APPROVED", "Your account is awaiting administrator approval.",
                           "You will get access as soon as an administrator approves your registration.")
        return user
    return dep


staff = require("doctor", "admin")
doctor_only = require("doctor")
admin_only = require("admin")
any_user = require("patient", "doctor", "admin")


# ---- one-time tickets for the live (WebSocket) connection ----
_ws_tickets: dict[str, tuple[str, float]] = {}


def issue_ws_ticket(user: dict) -> str:
    now = time.time()
    for k in [k for k, (_, exp) in _ws_tickets.items() if exp < now]:
        _ws_tickets.pop(k, None)
    ticket = base64.urlsafe_b64encode(os.urandom(24)).decode().rstrip("=")
    _ws_tickets[ticket] = (user["id"], now + 30)
    return ticket


def redeem_ws_ticket(ticket: str) -> str | None:
    """Single use, 30 seconds. Returns the user id or None."""
    user_id, exp = _ws_tickets.pop(ticket, (None, 0.0))
    return user_id if user_id and exp >= time.time() else None


def client_ip(request: Request) -> str:
    """The caller's address. Behind our own proxy (TRUST_PROXY=true) the first X-Forwarded-For hop is used."""
    if get_settings().trust_proxy:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


async def find_by_email(email: str) -> dict | None:
    rows = await get_store().select("users", {"email": email.strip().lower()}, limit=1)
    return rows[0] if rows else None


async def create_user(*, email: str, password: str | None, full_name: str, role: str, status: str, email_verified: bool = False,
                      google_sub: str | None = None, **extra) -> dict:
    email = email.strip().lower()
    if await find_by_email(email):
        raise ApiError(409, "EMAIL_IN_USE", "An account with this email already exists.", "Sign in instead, or use another email.")
    user = {"id": str(uuid.uuid4()), "email": email, "password_hash": hash_password(password) if password else None, "full_name": full_name.strip(),
            "role": role, "status": status, "created_at": now_iso(), "phone": None, "specialty": None, "license_no": None,
            "hospital": None, "date_of_birth": None, "gender": None, "approved_at": None, "approved_by_name": None,
            "email_verified": email_verified, "google_sub": google_sub, "session_version": 0}
    user.update({k: v for k, v in extra.items() if k in user and v not in ("", None)})
    return await get_store().insert("users", user)


async def end_all_sessions(user: dict) -> dict:
    """Invalidate every existing session for this account."""
    return await get_store().update("users", user["id"], {"session_version": int(user.get("session_version") or 0) + 1})


async def ensure_admin() -> None:
    """Bootstrap the first administrator from ADMIN_EMAIL / ADMIN_PASSWORD (trusted configuration, so pre-verified)."""
    s = get_settings()
    if not (s.admin_email and s.admin_password) or await find_by_email(s.admin_email):
        return
    user = await create_user(email=s.admin_email, password=s.admin_password, full_name="NeuroQueue Admin", role="admin", status="approved",
                             email_verified=True)
    await get_store().audit_append(new_event("USER_REGISTERED", user, details={"role": "admin", "bootstrap": True}))
