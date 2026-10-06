"""Metrics, dashboards, audit log, simulation and demo-mode endpoints."""
from __future__ import annotations

import asyncio
import json
import mimetypes
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app import auth
from app.api.scans import load_doctor, new_scan
from app.config import ARTIFACTS_DIR, CLASS_LABELS, CLASSES, get_settings, load_json_artifact, load_thresholds
from app.errors import ApiError
from app.realtime import hub
from app.services import pipeline, verifier
from app.services.audit import now_iso, verify_chain
from app.services.classifier import get_classifier
from app.services.simulation import DEFAULTS, run_simulation
from app.store import get_store

router = APIRouter(prefix="/api", tags=["insights"])
TIERS = (verifier.URGENT, verifier.REVIEW, verifier.ROUTINE)


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def live_verifier_stats(scans: list[dict]) -> dict:
    classified = [s for s in scans if s.get("verifier")]
    reviewed = [s for s in scans if s.get("review")]
    overrides = [s for s in reviewed if s["review"]["decision"] == "override"]
    waits = defaultdict(list)
    for s in reviewed:
        waits[s.get("tier") or "?"].append((_dt(s["review"]["at"]) - _dt(s["uploaded_at"])).total_seconds() / 60)
    demo = [s for s in classified if s.get("demo_true_label")]
    demo_wrong = [s for s in demo if s["prediction"]["top_class"] != s["demo_true_label"]]
    return {
        "classified": len(classified),
        "tier_counts": {t: sum(1 for s in classified if s.get("tier") == t) for t in TIERS},
        "reason_counts": dict(Counter(r for s in classified for r in (s.get("reasons") or []))),
        "reviewed": len(reviewed), "confirmed": len(reviewed) - len(overrides), "overridden": len(overrides),
        # An override is a model error a radiologist caught. Errors are "caught by the verifier" when the
        # scan had been routed to REVIEW or URGENT rather than left to be read last.
        "errors_caught_by_verifier": sum(1 for s in overrides if s.get("tier") != verifier.ROUTINE),
        "errors_found_in_routine": sum(1 for s in overrides if s.get("tier") == verifier.ROUTINE),
        "mean_wait_to_review_min": {t: round(sum(v) / len(v), 1) for t, v in waits.items() if v},
        "demo_ground_truth": {"scans": len(demo), "model_wrong": len(demo_wrong),
                              "wrong_not_in_routine": sum(1 for s in demo_wrong if s.get("tier") != verifier.ROUTINE)},
    }


@router.get("/metrics")
async def metrics(_: dict = Depends(auth.staff)):
    scans = await get_store().select("scans")
    sim = load_json_artifact("simulation.json") or await asyncio.to_thread(run_simulation, None)
    return {"model": load_json_artifact("metrics.json"), "thresholds": load_thresholds(), "live": live_verifier_stats(scans),
            "simulation": sim, "simulation_defaults": DEFAULTS, "classes": CLASSES,
            "limits": ["Public 2D MRI images from a single dataset", "No patient history or clinical context",
                       "Performance on other scanners and protocols is unknown", "Simulation results depend on the stated assumptions"]}


class SimIn(BaseModel):
    job_id: str | None = None
    arrivals_per_hour: float = Field(default=DEFAULTS["arrivals_per_hour"], gt=0, le=120)
    read_minutes: float = Field(default=DEFAULTS["read_minutes"], gt=0, le=120)
    urgent_fraction: float = Field(default=DEFAULTS["urgent_fraction"], ge=0, le=1)
    hours: float = Field(default=DEFAULTS["hours"], gt=0, le=24)
    radiologists: int = Field(default=DEFAULTS["radiologists"], ge=1, le=20)


@router.post("/simulation/run")
async def simulation(body: SimIn, user: dict = Depends(auth.staff)):
    job_id = body.job_id or str(uuid.uuid4())
    params = body.model_dump(exclude={"job_id"})

    async def run(ctx):
        await ctx.progress("simulating 200 working days per policy", 15)
        return await asyncio.to_thread(run_simulation, params)

    hub.start_job(job_id, "simulation", user, run)
    return {"job_id": job_id}


@router.get("/audit")
async def audit_log(scan_id: str | None = None, action: str | None = None, limit: int = 300, user: dict = Depends(auth.staff)):
    store = get_store()
    chain = verify_chain(await store.audit_list())  # always verify the whole chain, whatever the filter
    events = await store.audit_list(scan_id=scan_id)
    if user["role"] == "doctor":   # a doctor sees their own actions and the history of scans assigned to them
        mine = {s["id"] for s in await store.select("scans", {"assigned_doctor_id": user["id"]})}
        events = [e for e in events if e.get("actor_id") == user["id"] or e.get("scan_id") in mine]
    if action:
        events = [e for e in events if e["action"] == action]
    return {"events": events[-max(1, min(limit, 1000)):][::-1], "chain": chain, "actions": sorted({e["action"] for e in events})}


@router.get("/stats/overview")
async def overview(user: dict = Depends(auth.any_user)):
    store = get_store()
    if user["role"] == "patient":
        scans = await store.select("scans", {"patient_id": user["id"]})
        stages = Counter("Report finalized" if s["status"] == "signed" else "Awaiting doctor review" if s["status"] not in ("reviewed", "drafted") else "With your doctor" for s in scans)
        return {"role": "patient", "total": len(scans), "stages": [{"name": k, "value": v} for k, v in stages.items()],
                "released": sum(1 for s in scans if s["status"] == "signed"),
                "timeline": _daily(scans, 30, lambda s: "Uploaded")}

    scans = await store.select("scans")
    if user["role"] == "doctor":   # a doctor's dashboard counts only the scans assigned to them
        scans = [s for s in scans if s.get("assigned_doctor_id") == user["id"]]
    now = datetime.now(timezone.utc)
    unread = [s for s in scans if s["status"] in ("pending", "processing", "classified", "failed")]
    live = live_verifier_stats(scans)
    out = {
        "role": user["role"], "total_scans": len(scans), "unread": len(unread),
        "signed": sum(1 for s in scans if s["status"] == "signed"),
        "urgent_unread": sum(1 for s in unread if s.get("tier") == verifier.URGENT),
        "review_unread": sum(1 for s in unread if s.get("tier") == verifier.REVIEW),
        "routine_unread": sum(1 for s in unread if s.get("tier") == verifier.ROUTINE),
        "oldest_unread_min": round(max([pipeline.minutes_since(s["uploaded_at"]) for s in unread], default=0), 1),
        "tiers": [{"name": t.title(), "value": live["tier_counts"][t]} for t in TIERS],
        "statuses": [{"name": k, "value": v} for k, v in Counter(s["status"] for s in scans).items()],
        "predicted_classes": [{"name": c, "predicted": sum(1 for s in scans if (s.get("prediction") or {}).get("top_class") == c),
                               "confirmed": sum(1 for s in scans if (s.get("review") or {}).get("final_class") == c)} for c in CLASSES],
        "classes": CLASSES, "class_labels": CLASS_LABELS,
        "reasons": [{"name": verifier.REASON_TEXT.get(k, k), "code": k, "value": v} for k, v in sorted(live["reason_counts"].items(), key=lambda kv: -kv[1])],
        "daily": _daily(scans, 14, lambda s: (s.get("tier") or "Untiered").title()),
        "hourly": _hourly(scans, now),
        "confidence": _confidence_hist(scans),
        "wait_by_tier": [{"name": t.title(), "minutes": live["mean_wait_to_review_min"].get(t, 0)} for t in TIERS],
        "live": live,
        "my_reviews": sum(1 for s in scans if (s.get("review") or {}).get("reviewer_id") == user["id"]),
    }
    if user["role"] == "admin":
        users = await store.select("users")
        out["users"] = {"total": len(users), "by_role": [{"name": r, "value": sum(1 for u in users if u["role"] == r)} for r in auth.ROLES],
                        "pending_doctors": sum(1 for u in users if u["role"] == "doctor" and u["status"] == "pending"),
                        "signups": _daily(users, 14, lambda u: u["role"].title(), key="created_at")}
        out["system"] = await system_status()
    return out


def _daily(rows: list[dict], days: int, group, key: str = "uploaded_at") -> list[dict]:
    today = datetime.now(timezone.utc).date()
    buckets = {(today - timedelta(days=i)).isoformat(): Counter() for i in range(days - 1, -1, -1)}
    for r in rows:
        d = _dt(r[key]).date().isoformat()
        if d in buckets:
            buckets[d][group(r)] += 1
    return [{"date": d[5:], **c, "total": sum(c.values())} for d, c in buckets.items()]


def _hourly(scans: list[dict], now: datetime) -> list[dict]:
    out = []
    for i in range(11, -1, -1):
        start = (now - timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=1)
        out.append({"t": start.isoformat(),
                    "uploaded": sum(1 for s in scans if start <= _dt(s["uploaded_at"]) < end),
                    "reviewed": sum(1 for s in scans if s.get("reviewed_at") and start <= _dt(s["reviewed_at"]) < end)})
    return out


def _confidence_hist(scans: list[dict]) -> list[dict]:
    edges = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0001]
    probs = [s["prediction"]["top_prob"] for s in scans if s.get("prediction")]
    return [{"bin": f"{lo:.2f}-{min(hi, 1):.2f}", "scans": sum(1 for p in probs if lo <= p < hi)} for lo, hi in zip(edges[:-1], edges[1:])]


async def system_status() -> dict:
    s, store = get_settings(), get_store()
    clf = get_classifier()
    return {"store": store.name, "classifier": clf.name, "model_version": getattr(clf, "version", None),
            "report_writer": s.qwen_report_model if s.use_qwen else "template", "assistant": s.qwen_text_model if s.use_qwen else "offline",
            "voice": "assemblyai" if s.assemblyai_key and not s.mock_mode else "browser-only", "mock_mode": s.mock_mode,
            "thresholds_source": load_thresholds().get("tuned_on"), "connected_clients": len(hub.clients), "running_jobs": len(hub.jobs)}


@router.get("/health")
async def health():
    st = await system_status()
    return {"status": "ok", "time": now_iso(), **{k: st[k] for k in ("store", "classifier", "model_version", "report_writer", "voice", "mock_mode")}}


# ---------------- demo mode ----------------
class DemoIn(BaseModel):
    doctor_id: str


class AdvanceIn(BaseModel):
    minutes: int = Field(ge=1, le=600)


@router.post("/demo/load")
async def demo_load(body: DemoIn, user: dict = Depends(auth.admin_only)):
    """One-click demo: 20 pre-selected held-out test scans, assigned to the chosen doctor, queued in arrival order (unsorted)."""
    doctor = await load_doctor(body.doctor_id)
    demo_dir = ARTIFACTS_DIR / "demo"
    manifest_file = demo_dir / "manifest.json"
    if not manifest_file.exists():
        raise ApiError(409, "DEMO_SET_MISSING", "The demo scan set has not been generated.", "Run `python -m ml.train` to create ml/artifacts/demo.")
    store, out = get_store(), []
    base = datetime.now(timezone.utc) - timedelta(minutes=30)
    for i, m in enumerate(json.loads(manifest_file.read_text())):
        data = (demo_dir / m["file"]).read_bytes()
        ctype = mimetypes.guess_type(m["file"])[0] or "image/jpeg"
        scan = new_scan(filename=m["file"], path="", content_type=ctype, uploader=user, patient=None, patient_name=f"Demo patient {i + 1:02d}", doctor=doctor,
                        uploaded_at=(base + timedelta(seconds=75 * i)).isoformat(timespec="milliseconds"), demo=m,
                        exam={"clinical_concern": "Demonstration scan from the held-out test set", "referring_doctor": None})
        scan["storage_path"] = f"scans/{scan['id']}"
        await store.put_file(scan["storage_path"], data, ctype)
        scan = await store.insert("scans", scan)
        await hub.scan_updated(scan)
        out.append(scan)
    await pipeline.audit("DEMO_LOADED", user, details={"scans": len(out), "doctor_id": doctor["id"], "doctor": doctor["full_name"]})
    return {"scans": out}


@router.post("/demo/advance")
async def demo_advance(body: AdvanceIn, user: dict = Depends(auth.staff)):
    """Simulate time passing for unread scans so wait-time escalation can be shown."""
    store, n = get_store(), 0
    for s in await store.select("scans", {"status": "classified"}):
        shifted = (_dt(s["uploaded_at"]) - timedelta(minutes=body.minutes)).isoformat(timespec="milliseconds")
        await hub.scan_updated(await store.update("scans", s["id"], {"uploaded_at": shifted}))
        n += 1
    await pipeline.audit("DEMO_TIME_ADVANCED", user, details={"minutes": body.minutes, "scans": n})
    escalated = await pipeline.escalate_waiting()
    return {"shifted": n, "escalated": escalated}


@router.post("/demo/clear")
async def demo_clear(user: dict = Depends(auth.admin_only)):
    """Remove unsigned demo scans. Signed reports stay on the record."""
    store, n = get_store(), 0
    for s in await store.select("scans", {"is_demo": True}):
        if s["status"] == "signed":
            continue
        if s.get("report_id"):
            await store.delete("reports", s["report_id"])
        for p in (s.get("storage_path"), s.get("heatmap_path")):
            if p:
                await store.delete_file(p)
        await store.delete("scans", s["id"])
        await hub.scan_removed(s)
        n += 1
    await pipeline.audit("DEMO_CLEARED", user, details={"scans": n})
    return {"removed": n}


@router.get("/artifacts/{name}")
async def artifact(name: str, _: dict = Depends(auth.staff)):
    if name not in ("reliability.png", "confusion_matrix.png"):
        raise ApiError(404, "NOT_FOUND", "No such artifact.")
    path = ARTIFACTS_DIR / name
    if not path.exists():
        raise ApiError(404, "NOT_FOUND", "This plot has not been generated yet.", "Run `python -m ml.train`.")
    return Response(path.read_bytes(), media_type="image/png")
