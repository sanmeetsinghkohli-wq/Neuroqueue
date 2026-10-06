import asyncio
import copy
import json

from app.services.audit import GENESIS, HASHED_FIELDS, canonical_json, new_event, seal, verify_chain
from app.store.local import LocalStore


def chain(n: int = 6) -> list[dict]:
    events, prev = [], GENESIS
    for i in range(n):
        e = seal(new_event("TIER", {"id": "u1", "full_name": "Dr A"}, f"scan-{i}", {"to": "URGENT", "top_prob": 0.9731 + i / 1000}), prev)
        events.append(e)
        prev = e["hash"]
    return events


def test_intact_chain_verifies():
    r = verify_chain(chain())
    assert r["ok"] and r["count"] == 6 and r["broken_at"] is None


def test_empty_chain_verifies():
    assert verify_chain([])["ok"]


def test_modified_event_is_detected():
    events = chain()
    events[2]["details"]["to"] = "ROUTINE"
    r = verify_chain(events)
    assert not r["ok"] and r["broken_at"] == 2


def test_every_hashed_field_is_protected():
    for field, value in (("actor_name", "Someone Else"), ("ts", "2020-01-01T00:00:00.000+00:00"), ("action", "SIGN"),
                         ("scan_id", "x"), ("actor_id", "u2"), ("id", "other")):
        events = chain()
        events[4][field] = value
        assert verify_chain(events)["broken_at"] == 4, field


def test_deleted_event_is_detected():
    events = chain()
    del events[3]
    r = verify_chain(events)
    assert not r["ok"] and r["broken_at"] == 3


def test_reordered_events_are_detected():
    events = chain()
    events[1], events[2] = events[2], events[1]
    assert not verify_chain(events)["ok"]


def test_rehashing_a_forged_row_breaks_the_next_link():
    events = chain()
    forged = copy.deepcopy(events[1])
    forged["details"]["to"] = "ROUTINE"
    events[1] = seal({k: forged[k] for k in HASHED_FIELDS}, forged["prev_hash"])
    assert verify_chain(events)["broken_at"] == 2


def test_canonical_json_survives_key_reordering_and_a_json_round_trip():
    e = new_event("X", None, None, {"b": 1, "a": {"y": 0.123456789, "x": [1, 2.5]}})
    again = json.loads(json.dumps(e))
    again["details"] = {"a": {"x": [1, 2.5], "y": again["details"]["a"]["y"]}, "b": 1}
    assert canonical_json(e) == canonical_json(again)


def test_store_appends_a_verifiable_chain_and_tampering_in_storage_is_detected():
    async def go():
        store = LocalStore(None)
        for i in range(5):
            await store.audit_append(new_event("UPLOAD", None, f"s{i}", {"i": i}))
        events = await store.audit_list()
        assert [e["seq"] for e in events] == [1, 2, 3, 4, 5]
        assert verify_chain(events)["ok"]
        store.db["audit_events"][1]["details"]["i"] = 99
        assert verify_chain(await store.audit_list())["broken_at"] == 1
    asyncio.run(go())
