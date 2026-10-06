"""NeuroQueue API.

    uvicorn app.main:app --reload --port 8000      (from the backend/ folder)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import auth, errors
from app.api import assist, auth as auth_api, insights, reports, scans
from app.config import get_settings
from app.errors import ApiError
from app.realtime import hub
from app.services import pipeline
from app.services.classifier import get_classifier
from app.store import get_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("neuroqueue")


async def startup() -> None:
    store = get_store()
    await store.start()
    await auth.ensure_admin()
    await asyncio.to_thread(get_classifier)  # load the model before the first request needs it
    log.info("store=%s classifier=%s mock_mode=%s", store.name, get_classifier().name, get_settings().mock_mode)


async def _escalation_loop() -> None:
    while True:
        await asyncio.sleep(20)
        with suppress(Exception):
            await pipeline.escalate_waiting()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await startup()
    task = asyncio.create_task(_escalation_loop())
    yield
    task.cancel()
    await get_store().stop()


app = FastAPI(title="NeuroQueue API", version="2.0.0", lifespan=lifespan,
              description="Decision support only, not a diagnosis. Every scan is read by a radiologist.")
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def security(request: Request, call_next):
    """CSRF defence for cookie sessions: a state-changing request from a browser must come from one of our own origins.
    Also sets the response headers that keep API data out of caches and other sites' frames."""
    origin = request.headers.get("origin")
    if request.method in UNSAFE and origin and origin not in get_settings().cors_origins:
        return JSONResponse({"code": "BAD_ORIGIN", "message": "This request did not come from the NeuroQueue site.", "hint": ""}, status_code=403)
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if get_settings().cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# Explicit origins only (never "*"), because the browser sends the session cookie.
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["GET", "POST", "PATCH", "DELETE"],
                   allow_headers=["Content-Type", "Authorization"], allow_credentials=True)
errors.install(app)
for r in (auth_api.router, scans.router, reports.router, insights.router, assist.router):
    app.include_router(r)


@app.websocket("/ws")
async def ws(socket: WebSocket, ticket: str | None = None):
    # Other sites cannot open this socket. The session token itself is never put in a URL:
    # the socket is opened either with the HttpOnly cookie (same site) or with a one-time,
    # 30-second ticket that the signed-in page fetched a moment ago (site and API on different hosts).
    origin = socket.headers.get("origin")
    if origin and origin not in get_settings().cors_origins:
        await socket.close(code=4403)
        return
    await socket.accept()
    try:
        user_id = auth.redeem_ws_ticket(ticket) if ticket else None
        if user_id:
            user = await get_store().get("users", user_id)
            if not user or user.get("status") in ("disabled", "rejected"):
                raise ApiError(401, "ACCOUNT_UNAVAILABLE", "This account is not available.", "Contact support.")
        else:
            user = await auth.user_from_token(socket.cookies.get(auth.COOKIE))
    except ApiError as e:
        await socket.send_json({"type": "error", "error": {"code": e.code, "message": e.message, "hint": e.hint}})
        await socket.close(code=4401)
        return
    await hub.connect(socket, user)
    await socket.send_json({"type": "hello", "user_id": user["id"]})
    try:
        while True:
            msg = await socket.receive_json()
            if msg.get("type") == "ping":
                await socket.send_json({"type": "pong"})
            elif msg.get("type") == "cancel_job":
                hub.cancel_job(str(msg.get("job_id")), user)
            elif msg.get("type") == "refresh_user":  # e.g. after an admin approves a pending doctor
                fresh = await get_store().get("users", user["id"])
                if fresh:
                    user = fresh
                    await hub.connect(socket, user)
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        hub.disconnect(socket)
