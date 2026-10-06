"""Append-only, hash-chained audit log.

    hash = sha256(prev_hash + canonical_json(event))

`canonical_json` covers every stored field except `seq`, `prev_hash` and `hash`,
so editing, deleting or re-ordering any row breaks the chain from that row on.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

GENESIS = "0" * 64
HASHED_FIELDS = ("id", "ts", "actor_id", "actor_name", "action", "scan_id", "details")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _normalise(v):
    """Make values survive a JSON/JSONB round trip unchanged (floats are the risk)."""
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, dict):
        return {str(k): _normalise(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_normalise(x) for x in v]
    return v


def canonical_json(event: dict) -> str:
    body = {k: _normalise(event.get(k)) for k in HASHED_FIELDS}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_hash(prev_hash: str, event: dict) -> str:
    return hashlib.sha256((prev_hash + canonical_json(event)).encode()).hexdigest()


def new_event(action: str, actor: dict | None = None, scan_id: str | None = None, details: dict | None = None) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "ts": now_iso(),
        "actor_id": (actor or {}).get("id"),
        "actor_name": (actor or {}).get("full_name") or "system",
        "action": action,
        "scan_id": scan_id,
        "details": _normalise(details or {}),
    }


def seal(event: dict, prev_hash: str) -> dict:
    return {**event, "prev_hash": prev_hash, "hash": compute_hash(prev_hash, event)}


def verify_chain(events: list[dict]) -> dict:
    """`events` must be in append order. Returns {ok, count, broken_at, reason}."""
    prev = GENESIS
    for i, e in enumerate(events):
        if e.get("prev_hash") != prev:
            return {"ok": False, "count": len(events), "broken_at": i, "event_id": e.get("id"),
                    "reason": "prev_hash does not match the previous event (row removed, inserted or re-ordered)"}
        if compute_hash(prev, e) != e.get("hash"):
            return {"ok": False, "count": len(events), "broken_at": i, "event_id": e.get("id"),
                    "reason": "hash does not match the event contents (row was modified)"}
        prev = e["hash"]
    return {"ok": True, "count": len(events), "broken_at": None, "event_id": None, "reason": None, "head": prev}
