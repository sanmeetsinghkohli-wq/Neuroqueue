from __future__ import annotations

import asyncio
import time

import httpx

from app.config import Settings
from app.services.audit import canonical_json


class SupabaseStore:
    """Postgres (PostgREST) + Storage on the Supabase project.

    The backend is the only client of the database. It authenticates either with
    a service-role key, or as the dedicated `service` account that the row-level
    security policies in supabase/schema.sql grant write access to.
    """

    name = "supabase"

    def __init__(self, s: Settings) -> None:
        self.s = s
        self.http = httpx.AsyncClient(base_url=s.supabase_url, timeout=30)
        self._token = s.supabase_service_key or ""
        self._exp = float("inf") if s.supabase_service_key else 0.0
        self._lock = asyncio.Lock()
        self._cache: dict[str, bytes] = {}

    async def start(self) -> None:
        await self._headers()

    async def stop(self) -> None:
        await self.http.aclose()

    async def _headers(self) -> dict:
        if time.time() > self._exp - 60:
            async with self._lock:
                if time.time() > self._exp - 60:
                    r = await self.http.post("/auth/v1/token", params={"grant_type": "password"},
                                             headers={"apikey": self.s.supabase_anon_key},
                                             json={"email": self.s.supabase_service_email, "password": self.s.supabase_service_password})
                    r.raise_for_status()
                    j = r.json()
                    self._token, self._exp = j["access_token"], time.time() + j.get("expires_in", 3600)
        return {"apikey": self.s.supabase_service_key or self.s.supabase_anon_key, "Authorization": f"Bearer {self._token}"}

    async def _rest(self, method: str, path: str, **kw):
        h = {**await self._headers(), **kw.pop("headers", {})}
        r = await self.http.request(method, f"/rest/v1/{path}", headers=h, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase {method} {path.split('?')[0]} failed ({r.status_code}): {r.text[:300]}")
        return r.json() if r.content else None

    async def insert(self, table, row):
        return (await self._rest("POST", table, json=row, headers={"Prefer": "return=representation"}))[0]

    async def get(self, table, id):
        rows = await self._rest("GET", table, params={"id": f"eq.{id}", "limit": 1})
        return rows[0] if rows else None

    async def update(self, table, id, patch):
        rows = await self._rest("PATCH", table, params={"id": f"eq.{id}"}, json=patch, headers={"Prefer": "return=representation"})
        if not rows:
            raise KeyError(f"{table}/{id}")
        return rows[0]

    async def delete(self, table, id):
        await self._rest("DELETE", table, params={"id": f"eq.{id}"})

    async def select(self, table, where=None, order=None, desc=False, limit=None):
        params = {k: ("is.null" if v is None else f"eq.{str(v).lower() if isinstance(v, bool) else v}") for k, v in (where or {}).items()}
        if order:
            params["order"] = f"{order}.{'desc' if desc else 'asc'}.nullslast"
        if limit:
            params["limit"] = limit
        return await self._rest("GET", table, params=params)

    async def put_file(self, path, data, content_type):
        h = {**await self._headers(), "Content-Type": content_type, "x-upsert": "true"}
        r = await self.http.post(f"/storage/v1/object/{self.s.supabase_bucket}/{path}", headers=h, content=data)
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase storage upload failed ({r.status_code}): {r.text[:300]}")
        self._cache[path] = data

    async def get_file(self, path):
        if path in self._cache:
            return self._cache[path]
        r = await self.http.get(f"/storage/v1/object/authenticated/{self.s.supabase_bucket}/{path}", headers=await self._headers())
        if r.status_code >= 400:
            return None
        if len(self._cache) > 300:
            self._cache.pop(next(iter(self._cache)))
        self._cache[path] = r.content
        return r.content

    async def delete_file(self, path):
        self._cache.pop(path, None)
        await self.http.request("DELETE", f"/storage/v1/object/{self.s.supabase_bucket}", headers=await self._headers(), json={"prefixes": [path]})

    async def audit_append(self, event):
        # The database takes a lock, reads the chain head and computes the hash, so
        # concurrent writers can never fork the chain.
        return await self._rest("POST", "rpc/nq_audit_append", json={"p_event": event, "p_canonical": canonical_json(event)})

    async def audit_list(self, scan_id=None, limit=None):
        params = {"order": "seq.desc" if limit else "seq.asc"}
        if scan_id:
            params["scan_id"] = f"eq.{scan_id}"
        if limit:
            params["limit"] = limit
        rows = await self._rest("GET", "audit_events", params=params)
        return rows[::-1] if limit else rows
