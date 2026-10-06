"""Account security: one-time tokens, email delivery, Google sign-in, throttling.

One-time tokens (email verification, password reset) are random, stored only as a
SHA-256 hash, expire, and can be used exactly once.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import smtplib
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import httpx
import jwt

from app.config import get_settings
from app.errors import ApiError
from app.services.audit import now_iso
from app.store import get_store

log = logging.getLogger("neuroqueue.accounts")
TTL_MIN = {"verify_email": 24 * 60, "reset_password": 30}

# ---------------- one-time tokens ----------------
def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def issue_token(user: dict, kind: str) -> str:
    """Create a single-use token. Any earlier unused token of the same kind is revoked."""
    store = get_store()
    for old in await store.select("auth_tokens", {"user_id": user["id"], "kind": kind}):
        if not old.get("used_at"):
            await store.update("auth_tokens", old["id"], {"used_at": now_iso()})
    raw = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(minutes=TTL_MIN[kind])).isoformat(timespec="milliseconds")
    await store.insert("auth_tokens", {"id": str(uuid.uuid4()), "user_id": user["id"], "kind": kind, "token_hash": _hash(raw),
                                       "expires_at": expires, "used_at": None, "created_at": now_iso()})
    return raw


async def consume_token(raw: str, kind: str) -> dict:
    """Returns the user. Raises for unknown, expired or already-used tokens."""
    store = get_store()
    rows = await store.select("auth_tokens", {"token_hash": _hash(raw or ""), "kind": kind}, limit=1)
    if not rows:
        raise ApiError(400, "LINK_INVALID", "This link is not valid.", "Request a new one.")
    tok = rows[0]
    if tok.get("used_at"):
        raise ApiError(400, "LINK_USED", "This link has already been used.", "Request a new one if you still need it.")
    if datetime.fromisoformat(tok["expires_at"]) < datetime.now(timezone.utc):
        raise ApiError(400, "LINK_EXPIRED", "This link has expired.", "Request a new one.")
    await store.update("auth_tokens", tok["id"], {"used_at": now_iso()})
    user = await store.get("users", tok["user_id"])
    if not user:
        raise ApiError(400, "LINK_INVALID", "This link is not valid.", "Request a new one.")
    return user


# ---------------- email ----------------
DEV_OUTBOX: deque = deque(maxlen=50)   # development only: used when no SMTP server is configured


def relay_configured() -> bool:
    s = get_settings()
    return bool(s.mail_relay_url and s.mail_relay_secret)


def smtp_configured() -> bool:
    """True when real email can be sent, directly over SMTP or through the site's mail relay."""
    s = get_settings()
    return bool(s.smtp_host and s.smtp_from) or relay_configured()


async def _send_relay(to: str, subject: str, body: str) -> None:
    s = get_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(s.mail_relay_url, json={"to": to, "subject": subject, "body": body},
                              headers={"x-relay-secret": s.mail_relay_secret})
        r.raise_for_status()


def _send_smtp(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


async def send_email(to: str, subject: str, body: str, link: str) -> None:
    """Never logs the message body or the link when a real mail server is in use."""
    if smtp_configured() and not get_settings().mock_mode:
        try:
            if relay_configured():
                await _send_relay(to, subject, body)
            else:
                await asyncio.to_thread(_send_smtp, to, subject, body)
        except Exception as e:  # noqa: BLE001
            log.error("email delivery failed: %s", type(e).__name__)
        return
    DEV_OUTBOX.appendleft({"to": to, "subject": subject, "link": link, "at": now_iso()})
    log.warning("No SMTP server configured: email to %s kept in the development outbox (admin > Users).", to)


def _link(path: str, token: str) -> str:
    return f"{get_settings().app_url}{path}?token={token}"


async def send_verification(user: dict) -> None:
    link = _link("/verify-email", await issue_token(user, "verify_email"))
    await send_email(user["email"], "Verify your NeuroQueue email address",
                     f"Hello {user['full_name']},\n\nConfirm your email address to activate your NeuroQueue account:\n\n{link}\n\n"
                     "The link works once and expires in 24 hours. If you did not create this account, ignore this email.", link)


async def send_reset(user: dict) -> None:
    link = _link("/reset-password", await issue_token(user, "reset_password"))
    await send_email(user["email"], "Reset your NeuroQueue password",
                     f"Hello {user['full_name']},\n\nSet a new password with this link:\n\n{link}\n\n"
                     "The link works once and expires in 30 minutes. If you did not ask for this, ignore this email; your password is unchanged.", link)


# ---------------- throttling ----------------
_hits: dict[str, deque] = defaultdict(deque)
_failures: dict[str, deque] = defaultdict(deque)
LOCK_AFTER, LOCK_WINDOW = 5, 15 * 60


def rate_limit(key: str, limit: int, window: int = 60) -> None:
    q, now = _hits[key], time.time()
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= limit:
        raise ApiError(429, "RATE_LIMITED", "Too many requests. Please wait a moment.", "Try again in a few minutes.")
    q.append(now)


def check_lock(email: str) -> None:
    q, now = _failures[email.strip().lower()], time.time()
    while q and q[0] < now - LOCK_WINDOW:
        q.popleft()
    if len(q) >= LOCK_AFTER:
        raise ApiError(429, "TOO_MANY_ATTEMPTS", "Too many failed sign-in attempts.", "Wait 15 minutes, or reset your password.")


def record_failure(email: str) -> None:
    _failures[email.strip().lower()].append(time.time())


def clear_failures(email: str) -> None:
    _failures.pop(email.strip().lower(), None)


def reset_throttles() -> None:
    _hits.clear()
    _failures.clear()
    DEV_OUTBOX.clear()


# ---------------- Google sign-in ----------------
_jwks = None


def verify_google_credential(credential: str) -> dict:
    """Verify a Google ID token on the server: signature (Google's published keys), audience, issuer and expiry.
    Nothing the browser says about the user's identity is trusted."""
    global _jwks
    client_id = get_settings().google_client_id
    if not client_id:
        raise ApiError(503, "GOOGLE_NOT_CONFIGURED", "Google sign-in is not set up on this server.", "Use email and password instead.")
    try:
        if _jwks is None:
            _jwks = jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs", cache_keys=True, lifespan=3600)
        key = _jwks.get_signing_key_from_jwt(credential)
        claims = jwt.decode(credential, key.key, algorithms=["RS256"], audience=client_id, options={"require": ["exp", "iat", "sub", "aud", "iss"]})
    except Exception:
        raise ApiError(401, "GOOGLE_TOKEN_INVALID", "Google sign-in could not be verified.", "Try again.")
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise ApiError(401, "GOOGLE_TOKEN_INVALID", "Google sign-in could not be verified.", "Try again.")
    if not claims.get("email") or not claims.get("email_verified"):
        raise ApiError(403, "GOOGLE_EMAIL_UNVERIFIED", "Your Google account's email address is not verified.", "Verify it with Google, or use email and password.")
    return {"sub": claims["sub"], "email": claims["email"].lower(), "name": claims.get("name") or claims["email"].split("@")[0]}
