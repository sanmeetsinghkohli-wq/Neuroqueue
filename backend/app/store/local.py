from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

from app.services.audit import GENESIS, seal
from app.store.base import TABLES


class LocalStore:
    """Whole database in memory, flushed to one JSON file. Fine for a demo-sized queue."""

    name = "local"

    def __init__(self, data_dir: Path | None) -> None:
        self.dir = data_dir  # None -> purely in-memory (tests)
        self.db: dict[str, list[dict]] = {t: [] for t in TABLES}
        self.files: dict[str, bytes] = {}
        self.lock = asyncio.Lock()

    async def start(self) -> None:
        if self.dir:
            (self.dir / "files").mkdir(parents=True, exist_ok=True)
            f = self.dir / "db.json"
            if f.exists():
                self.db = {**{t: [] for t in TABLES}, **json.loads(f.read_text(encoding="utf-8"))}

    async def stop(self) -> None:
        return None

    def _flush(self) -> None:
        if self.dir:
            tmp = self.dir / "db.json.tmp"
            tmp.write_text(json.dumps(self.db), encoding="utf-8")
            tmp.replace(self.dir / "db.json")

    async def insert(self, table, row):
        async with self.lock:
            self.db[table].append(copy.deepcopy(row))
            self._flush()
        return copy.deepcopy(row)

    async def get(self, table, id):
        return next((copy.deepcopy(r) for r in self.db[table] if r.get("id") == id), None)

    async def update(self, table, id, patch):
        async with self.lock:
            for r in self.db[table]:
                if r.get("id") == id:
                    r.update(copy.deepcopy(patch))
                    self._flush()
                    return copy.deepcopy(r)
        raise KeyError(f"{table}/{id}")

    async def delete(self, table, id):
        async with self.lock:
            self.db[table] = [r for r in self.db[table] if r.get("id") != id]
            self._flush()

    async def select(self, table, where=None, order=None, desc=False, limit=None):
        rows = [r for r in self.db[table] if all(r.get(k) == v for k, v in (where or {}).items())]
        if order:
            rows.sort(key=lambda r: (r.get(order) is None, r.get(order) or ""), reverse=desc)
        return copy.deepcopy(rows[:limit] if limit else rows)

    def _fpath(self, path: str) -> Path:
        return self.dir / "files" / path.replace("/", "__")

    async def put_file(self, path, data, content_type):
        if self.dir:
            await asyncio.to_thread(self._fpath(path).write_bytes, data)
        else:
            self.files[path] = data

    async def get_file(self, path):
        if self.dir:
            p = self._fpath(path)
            return await asyncio.to_thread(p.read_bytes) if p.exists() else None
        return self.files.get(path)

    async def delete_file(self, path):
        if self.dir:
            self._fpath(path).unlink(missing_ok=True)
        else:
            self.files.pop(path, None)

    async def audit_append(self, event):
        async with self.lock:
            chain = self.db["audit_events"]
            sealed = seal(event, chain[-1]["hash"] if chain else GENESIS)
            sealed["seq"] = len(chain) + 1
            chain.append(sealed)
            self._flush()
        return copy.deepcopy(sealed)

    async def audit_list(self, scan_id=None, limit=None):
        rows = [r for r in self.db["audit_events"] if scan_id is None or r.get("scan_id") == scan_id]
        return copy.deepcopy(rows[-limit:] if limit else rows)
