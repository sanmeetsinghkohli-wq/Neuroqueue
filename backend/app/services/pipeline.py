"""Scan pipeline.

    MRI image -> validation + preprocessing -> OUR TRAINED MRI MODEL -> classification
              -> deterministic verifier (tier) -> occlusion heatmap

The trained classifier is the only thing that classifies a scan. No language
model sees the image or has any say in the classification or the tier. If the
model cannot read the image the scan is marked failed; nothing is guessed.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.config import load_thresholds
from app.realtime import JobCtx, hub
from app.services import verifier
from app.services.audit import new_event, now_iso
from app.services.classifier import get_classifier
from app.services.heatmap import overlay_png
from app.store import get_store

log = logging.getLogger("neuroqueue.pipeline")
SYSTEM = {"id": None, "full_name": "system"}


def minutes_since(iso: str | None) -> float:
    if not iso:
        return 0.0
    return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 60)


async def audit(action: str, actor: dict | None, scan_id: str | None = None, details: dict | None = None) -> dict:
    ev = await get_store().audit_append(new_event(action, actor, scan_id, details))
    await hub.publish({"type": "audit_appended", "event": ev}, roles=("admin",), user_ids=((actor or {}).get("id"),))
    return ev


async def _save(scan_id: str, patch: dict) -> dict:
    scan = await get_store().update("scans", scan_id, patch)
    await hub.scan_updated(scan)
    return scan


async def classify_scan(scan_id: str, actor: dict | None = None, ctx: JobCtx | None = None) -> dict:
    store, th = get_store(), load_thresholds()
    scan = await store.get("scans", scan_id)
    if scan is None:
        raise KeyError(scan_id)
    if scan.get("status") in ("reviewed", "drafted", "signed"):
        return scan  # a radiologist has already read it; never re-tier underneath them
    data = await store.get_file(scan["storage_path"])
    if data is None:
        return await _save(scan_id, {"status": "failed", "error": "Image file is missing from storage."})

    scan = await _save(scan_id, {"status": "processing", "error": None})
    if ctx:
        await ctx.progress("running the MRI classification model", 20)
    clf = get_classifier()
    try:
        pred = await asyncio.to_thread(clf.predict, data, scan["filename"])
    except Exception as e:  # noqa: BLE001 - a model failure is reported, never papered over with a guess
        log.warning("classifier failed on %s: %s", scan_id, type(e).__name__)
        await audit("CLASSIFY_FAILED", actor or SYSTEM, scan_id, {"error": type(e).__name__})
        return await _save(scan_id, {"status": "failed", "error": "The model could not read this image. No classification was produced."})

    result = verifier.verify(pred["probs"], th, waited_min=minutes_since(scan["uploaded_at"]), out_of_distribution=bool(pred["ood"]["flag"]))
    # The model result is stored once and never edited afterwards; a doctor's review is recorded separately.
    prediction = {"probs": pred["probs"], "top_class": result["top_class"], "top_prob": result["top_prob"],
                  "margin_top2": result["margin_top2"], "model": pred["model"], "model_version": pred.get("model_version"),
                  "energy": pred.get("energy"), "at": now_iso()}
    scan = await _save(scan_id, {"prediction": prediction, "ood": pred["ood"], "tier": result["tier"], "tier_provisional": False,
                                 "reasons": result["reasons"], "notes": [], "verifier": result, "status": "classified",
                                 "classified_at": prediction["at"]})
    if ctx:
        await ctx.partial({"stage": "classifier", "scan_id": scan_id, "prediction": prediction, "tier": result["tier"]})
    await audit("CLASSIFIED", actor or SYSTEM, scan_id, {"model": pred["model"], "model_version": pred.get("model_version"),
                                                        "top_class": result["top_class"], "top_prob": result["top_prob"],
                                                        "margin_top2": result["margin_top2"]})
    await audit("TIER", actor or SYSTEM, scan_id, {"from": None, "to": result["tier"], "reason": result["reason"], "reasons": result["reasons"]})

    if result["tier"] != verifier.ROUTINE:  # heatmaps only for flagged scans; others are computed on demand
        if ctx:
            await ctx.progress("occlusion heatmap", 80)
        scan = await ensure_heatmap(scan)
    return scan


async def ensure_heatmap(scan: dict) -> dict:
    if scan.get("heatmap_path") or not scan.get("prediction"):
        return scan
    store = get_store()
    data = await store.get_file(scan["storage_path"])
    try:
        png = await asyncio.to_thread(overlay_png, get_classifier(), data, scan["prediction"]["top_class"])
    except Exception as e:  # noqa: BLE001
        log.warning("heatmap failed on %s: %s", scan["id"], type(e).__name__)
        return scan
    path = f"heatmaps/{scan['id']}.png"
    await store.put_file(path, png, "image/png")
    return await _save(scan["id"], {"heatmap_path": path})


async def process_pending(ctx: JobCtx, actor: dict) -> dict:
    store = get_store()
    pending = await store.select("scans", {"status": "pending"}, order="uploaded_at")
    pending += await store.select("scans", {"status": "failed"}, order="uploaded_at")
    if actor.get("role") == "doctor":   # a doctor only ever runs the model on scans assigned to them
        pending = [s for s in pending if s.get("assigned_doctor_id") == actor["id"]]
    total, done, sem = len(pending), 0, asyncio.Semaphore(4)

    async def one(s: dict):
        nonlocal done
        async with sem:
            try:
                await classify_scan(s["id"], actor, ctx)
            except Exception:  # noqa: BLE001
                log.exception("pipeline failed for %s", s["id"])
                await _save(s["id"], {"status": "failed", "error": "Processing failed. Retry from the queue."})
            done += 1
            await ctx.emit("job_progress", stage=f"{done} of {total} scans classified", pct=round(100 * done / max(1, total)))

    await asyncio.gather(*(one(s) for s in pending))
    return {"processed": total}


async def escalate_waiting() -> int:
    """Re-tier unread scans that have waited past max_wait_min to URGENT."""
    store, th, n = get_store(), load_thresholds(), 0
    for scan in await store.select("scans", {"status": "classified"}):
        if scan.get("tier") in (verifier.REVIEW, verifier.ROUTINE) and minutes_since(scan["uploaded_at"]) > th["max_wait_min"]:
            reasons = ["ESCALATED_WAIT"] + [r for r in (scan.get("reasons") or []) if r != "ESCALATED_WAIT"]
            await _save(scan["id"], {"tier": verifier.URGENT, "reasons": reasons, "escalated_at": now_iso()})
            await audit("TIER", SYSTEM, scan["id"], {"from": scan["tier"], "to": verifier.URGENT, "reason": "ESCALATED_WAIT",
                                                    "waited_min": round(minutes_since(scan["uploaded_at"]), 1)})
            n += 1
    return n
