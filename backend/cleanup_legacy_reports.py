"""Remove what the retired Qwen second opinion / second reviewer left behind in stored data.

    python cleanup_legacy_reports.py

- Unsigned drafts written under the old rules are discarded, so the doctor regenerates them
  with the current writer and the deterministic check. The review itself is kept.
- Finalized reports keep their text (they are part of the record); only the stored
  "Qwen second reviewer" row is dropped from their saved check result.
Safe to run more than once.
"""
from __future__ import annotations

import asyncio

from app.services import report_check
from app.services.audit import new_event
from app.store import get_store

LEGACY_ROW = "LLM"


def is_legacy(report: dict) -> bool:
    rows = (report.get("check") or {}).get("rows") or []
    return any(r.get("id") == LEGACY_ROW for r in rows) or (report.get("clinical_text") or "").startswith("BRAIN MRI TRIAGE REPORT")


async def main() -> None:
    store = get_store()
    await store.start()
    discarded = cleaned = 0
    for rep in await store.select("reports"):
        if not is_legacy(rep):
            continue
        if rep["status"] == "signed":
            rows = [r for r in rep["check"]["rows"] if r.get("id") != LEGACY_ROW]
            if len(rows) != len(rep["check"]["rows"]):
                await store.update("reports", rep["id"], {"check": report_check.summarise(rows)})
                cleaned += 1
            continue
        scan = await store.get("scans", rep["scan_id"])
        await store.delete("reports", rep["id"])
        if scan and scan.get("report_id") == rep["id"]:
            await store.update("scans", scan["id"], {"report_id": None, "status": "reviewed"})
            await store.audit_append(new_event("DRAFT_DISCARDED", None, scan["id"], {"reason": "drafted under retired second-reviewer rules"}))
        discarded += 1
    print(f"store: {store.name} | stale drafts discarded: {discarded} | finalized reports cleaned: {cleaned}")
    await store.stop()


if __name__ == "__main__":
    asyncio.run(main())
