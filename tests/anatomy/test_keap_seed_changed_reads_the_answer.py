"""converge-keap-churn — the face-table seed reports `changed` only on a change.

Measured on spark1: ~25 seed tasks `changed` on every converge. KEAP wraps
every answer as {success, data}; the row WHERE-guard read `.json.rows` (never
there) so every system row re-upserted, and the reconcile reported 200 as a
change. This evaluates the task's own expressions against recorded shapes
(server/agent.ts GET/POST /agent/v1/tables*).
"""
from __future__ import annotations

import pathlib

import jinja2
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SEED = REPO / "roles" / "pazny.keap" / "tasks" / "seed-face-table.yml"
ENV = jinja2.Environment()

COLS = [{"key": "slug", "kind": "text"}, {"key": "title", "kind": "text"}]
NEW = COLS + [{"key": "owner", "kind": "text"}]


def _task(needle: str) -> dict:
    return next(t for t in yaml.safe_load(SEED.read_text()) if needle in t.get("name", ""))


def _eval(expr, **ctx):
    exprs = expr if isinstance(expr, list) else [expr]
    return all(ENV.compile_expression(str(e))(**ctx) for e in exprs)


def _table(cols, shared=()):
    return {"status": 200, "json": {"success": True, "data": {"schema": {"columns": cols}, "sharedWith": list(shared)}}}


def _reconcile_changed(probe, create) -> bool:
    return _eval(_task("Reconcile DataTable")["changed_when"], _face_tbl_probe=probe, _face_tbl_create=create)


def test_reconcile_that_changed_nothing_is_not_changed():
    assert _reconcile_changed(_table(COLS), _table(COLS)) is False


def test_reconcile_that_adds_a_column_is_changed():
    assert _reconcile_changed(_table(COLS), _table(NEW)) is True


def test_reconcile_that_changes_the_acl_is_changed():
    assert _reconcile_changed(_table(COLS), _table(COLS, ["group:x"])) is True


def test_create_of_a_missing_table_is_changed():
    assert _reconcile_changed({"status": 404, "json": {"success": False}}, _table(COLS)) is True


def test_refused_reconcile_is_not_changed():
    assert _reconcile_changed(_table(COLS), {"status": 409, "json": {"success": False}}) is False


def _existing(rows_probe) -> list:
    expr = _task("Compute already-seeded row slugs")["ansible.builtin.set_fact"]["_face_existing_row_slugs"]
    return yaml.safe_load(ENV.from_string(expr.strip()).render(_face_rows_probe=rows_probe))


def _upsert_runs(item, existing) -> bool:
    return _eval(
        _task("Upsert MISSING system rows")["when"],
        item=item,
        _face_existing_row_slugs=existing,
        _face_tbl={"rows": [item]},
        _face_tbl_probe={"status": 200},
        _face_tbl_create={"status": 200},
    )


def test_a_seeded_row_is_not_upserted_again():
    probe = {"status": 200, "json": {"success": True, "data": {"rows": [{"slug": "a", "__id": "a"}]}}}
    assert _existing(probe) == ["a"]
    assert _upsert_runs({"slug": "a"}, _existing(probe)) is False


def test_a_missing_row_is_upserted_and_changed():
    probe = {"status": 200, "json": {"success": True, "data": {"rows": [{"slug": "a", "__id": "a"}]}}}
    assert _upsert_runs({"slug": "b"}, _existing(probe)) is True
    upsert = _task("Upsert MISSING system rows")
    assert _eval(upsert["changed_when"], _face_row_upsert={"status": 200}) is True
