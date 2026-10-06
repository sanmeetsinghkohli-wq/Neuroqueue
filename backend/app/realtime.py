"""Realtime hub and streamed-job framework.

One WebSocket per signed-in client. The server pushes:
  scan_updated / scan_removed / user_updated / audit_appended      (state changes)
  job_started, job_progress{stage,pct}, job_partial{data}, job_token{text},
  job_done{result}, job_failed{error,retryable}                    (streamed jobs)

Nothing in the UI polls. Administrators see every scan event; a doctor only receives
events about scans assigned to them; a patient only receives events about their own
scans, already stripped of AI output.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

log = logging.getLogger("neuroqueue.realtime")
STAFF = ("doctor", "admin")
ADMIN = ("admin",)


def scan_for_patient(scan: dict) -> dict:
    """What a patient may see of their own scan: status only. No prediction, tier or AI output."""
    status = scan.get("status")
    stage = {"signed": "Report finalized", "drafted": "Report under physician review", "reviewed": "Reviewed by doctor"}.get(
        status, "Awaiting doctor review")
    return {"id": scan["id"], "filename": scan.get("filename"), "uploaded_at": scan.get("uploaded_at"), "patient_id": scan.get("patient_id"),
            "patient_name": scan.get("patient_name"), "status": "signed" if status == "signed" else "in_progress", "stage": stage,
            "signed_at": scan.get("signed_at"), "exam_type": scan.get("exam_type") or "MRI Brain", "clinical_concern": scan.get("clinical_concern"),
            "referring_doctor": scan.get("referring_doctor"), "doctor_name": scan.get("assigned_doctor_name")}


class Hub:
    def __init__(self) -> None:
        self.clients: dict[WebSocket, dict] = {}
        self.jobs: dict[str, asyncio.Task] = {}
        self.job_owner: dict[str, str] = {}

    async def connect(self, ws: WebSocket, user: dict) -> None:
        self.clients[ws] = user

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.pop(ws, None)

    async def _send(self, ws: WebSocket, msg: dict) -> None:
        try:
            await ws.send_json(msg)
        except Exception:
            self.disconnect(ws)

    async def publish(self, msg: dict, *, roles: tuple[str, ...] = STAFF, user_ids: tuple[str | None, ...] = ()) -> None:
        targets = [ws for ws, u in list(self.clients.items())
                   if (u["role"] in roles and u.get("status") == "approved") or u["id"] in user_ids]
        if targets:
            await asyncio.gather(*(self._send(ws, msg) for ws in targets))

    async def scan_updated(self, scan: dict) -> None:
        await self.publish({"type": "scan_updated", "scan": scan}, roles=ADMIN, user_ids=(scan.get("assigned_doctor_id"),))
        if scan.get("patient_id"):
            await self.publish({"type": "scan_updated", "scan": scan_for_patient(scan)}, roles=(), user_ids=(scan["patient_id"],))

    async def scan_removed(self, scan: dict) -> None:
        await self.publish({"type": "scan_removed", "id": scan["id"]}, roles=ADMIN,
                           user_ids=(scan.get("patient_id"), scan.get("assigned_doctor_id")))

    async def scan_unassigned(self, scan_id: str, doctor_id: str | None) -> None:
        """The scan moved to another doctor: take it off the previous doctor's screen."""
        if doctor_id:
            await self.publish({"type": "scan_removed", "id": scan_id}, roles=(), user_ids=(doctor_id,))

    # ---------------- jobs ----------------
    def start_job(self, job_id: str, kind: str, owner: dict, fn: Callable[["JobCtx"], Awaitable[Any]], *, scan_id: str | None = None,
                  broadcast: bool = False) -> None:
        """Run `fn(ctx)` as a cancellable streamed job. Events go to the owner (and administrators if broadcast)."""
        if job_id in self.jobs:
            return
        ctx = JobCtx(self, job_id, kind, owner, scan_id, broadcast)

        async def runner():
            await ctx.emit("job_started")
            try:
                result = await fn(ctx)
                await ctx.emit("job_done", result=result)
            except asyncio.CancelledError:
                await ctx.emit("job_failed", error={"code": "CANCELLED", "message": "Cancelled."}, retryable=True)
            except Exception as e:  # noqa: BLE001 - reported to the client as a structured failure
                from app.errors import ApiError

                if isinstance(e, ApiError):
                    err = {"code": e.code, "message": e.message, "hint": e.hint}
                else:
                    log.exception("job %s (%s) failed", job_id, kind)
                    err = {"code": "JOB_FAILED", "message": "The job could not be completed.", "hint": "Retry. If it keeps failing, contact support."}
                await ctx.emit("job_failed", error=err, retryable=True)
            finally:
                self.jobs.pop(job_id, None)
                self.job_owner.pop(job_id, None)

        self.job_owner[job_id] = owner["id"]
        self.jobs[job_id] = asyncio.create_task(runner())

    def cancel_job(self, job_id: str, user: dict) -> bool:
        task = self.jobs.get(job_id)
        if task and (self.job_owner.get(job_id) == user["id"] or user["role"] == "admin"):
            task.cancel()
            return True
        return False

    async def wait_idle(self) -> None:
        while self.jobs:
            await asyncio.gather(*list(self.jobs.values()), return_exceptions=True)


class JobCtx:
    def __init__(self, hub: Hub, job_id: str, kind: str, owner: dict, scan_id: str | None, broadcast: bool) -> None:
        self.hub, self.job_id, self.kind, self.owner, self.scan_id, self.broadcast = hub, job_id, kind, owner, scan_id, broadcast

    async def emit(self, type_: str, **data) -> None:
        msg = {"type": type_, "job_id": self.job_id, "kind": self.kind, "scan_id": self.scan_id, **data}
        await self.hub.publish(msg, roles=ADMIN if self.broadcast else (), user_ids=(self.owner["id"],))

    async def progress(self, stage: str, pct: int) -> None:
        await self.emit("job_progress", stage=stage, pct=pct)

    async def partial(self, data: dict) -> None:
        await self.emit("job_partial", data=data)

    async def token(self, text: str, section: str | None = None) -> None:
        await self.emit("job_token", text=text, section=section)


hub = Hub()
