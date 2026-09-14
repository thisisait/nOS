"""S7 — a DataTable seeded with no rows does not GET the live ledger.

p=54800: caddy-sessions (rows: []) still fetched every chat row ~21s to
compute a WHERE-guard the upsert loop never used. A later table's upsert
must not see the previous table's slug list.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SEED = REPO / "roles" / "pazny.keap" / "tasks" / "seed-face-table.yml"


def _tasks():
    return yaml.safe_load(SEED.read_text(encoding="utf-8"))


def _named_contains(needle: str) -> dict:
    return next(
        t for t in _tasks()
        if isinstance(t, dict) and needle in str(t.get("name", ""))
    )


def _when(task: dict) -> str:
    w = task.get("when")
    if w is None:
        return ""
    if isinstance(w, list):
        return " && ".join(str(x) for x in w)
    return str(w)


def test_row_fetch_is_skipped_when_the_seed_is_empty():
    fetch = _named_contains("Fetch existing rows")
    text = _when(fetch)
    assert "_face_tbl.rows" in text and "length" in text, (
        f"{SEED}: fetch must skip when `_face_tbl.rows` is empty; when={text}"
    )


def test_empty_seed_resets_slug_guard_so_the_next_table_is_not_poisoned():
    reset = _named_contains("No row WHERE-guard")
    assert reset.get("ansible.builtin.set_fact", reset.get("set_fact")) == {
        "_face_existing_row_slugs": []
    } or "_face_existing_row_slugs" in str(reset)
    assert "[]" in str(reset.get("ansible.builtin.set_fact") or reset.get("set_fact") or reset)
    assert "== 0" in _when(reset) or "length" in _when(reset)


def test_upsert_when_survives_an_undefined_slug_guard():
    upsert = _named_contains("Upsert MISSING system rows")
    text = _when(upsert)
    assert "_face_existing_row_slugs" in text
    assert "default([])" in text or "default([])" in str(upsert), (
        f"{SEED}: upsert `when` must default the slug list; empty-table skip "
        f"otherwise errors or reuses the prior include's slugs: {text}"
    )
    assert "_face_tbl.rows" in text
