from __future__ import annotations

from app.config import get_settings
from app.store.base import Store
from app.store.local import LocalStore

_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        s = get_settings()
        if s.use_supabase:
            from app.store.supabase import SupabaseStore
            _store = SupabaseStore(s)
        else:
            _store = LocalStore(s.data_dir)
    return _store


def set_store(store: Store | None) -> None:
    global _store
    _store = store
