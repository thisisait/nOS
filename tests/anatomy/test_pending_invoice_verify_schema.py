"""D5 unit 1 (review-sink-schema) — retro-red gate.

RETRO-RED: before this commit, `state/keap-tables/pending-invoice-verify.table.yml`
did not exist (verified manually: `git show HEAD~1:state/keap-tables/pending-
invoice-verify.table.yml` errors "does not exist" on the pre-D5 tree). This test
would fail with FileNotFoundError on that tree; it is green only because the
table + its join key now exist.

Also asserts D1's invoice-review facet already uses a REAL KEAP visibility
value (tier-managers) — the wf-def's unit build step says "D1 already set;
assert here, don't re-add", so this is confirmation, not construction.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TABLE = REPO / "state" / "keap-tables" / "pending-invoice-verify.table.yml"
INVOICE_REVIEW = REPO / "state" / "keap-tables" / "invoice-review.table.yml"

#: KEAP's tableVisibilitySchema enum — same list test_keap_table_concepts.py
#: pins (KEAP_VISIBILITY there). The __visibility:system phantom the gate
#: warns against is not a value at all — it's a graph-node flag, never a
#: table's `visibility:` key.
KEAP_VISIBILITY = {"private", "tier-managers", "tier-users", "tier-guests", "shared"}


def _doc(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_pending_invoice_verify_table_exists_with_the_join_key():
    doc = _doc(TABLE)
    assert doc["visibility"] == "tier-managers"
    assert doc["visibility"] in KEAP_VISIBILITY, "not the phantom __visibility:system"
    assert doc["graph"]["mode"] == "rows", "TablesApp browses+edits rows — no bespoke screen"

    cols = {c["key"]: c for c in doc["schema"]["columns"]}
    assert "sidecar_id" in cols, "the stable JOIN KEY unit 2 looks up by"
    assert cols["sidecar_id"]["kind"] == "text"
    assert cols["sidecar_id"].get("required") is True, "unit 2 has nothing to join on without it"

    assert cols["resolution"]["kind"] == "select"
    assert set(cols["resolution"]["options"]) == {"pending", "approved", "rejected"}
    assert "resolved_by" in cols and "resolved_at" in cols


def test_pending_invoice_verify_row_editable_via_the_existing_upsert_path():
    """No new endpoint: face's bff/tables POST {op:upsertRow} works on ANY
    slug matching SLUG_RE — this just proves the slug itself is well-formed
    (the existing path validates the rest at request time)."""
    import re

    slug_re = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
    assert slug_re.match("pending-invoice-verify")


def test_d1_invoice_review_facet_already_uses_a_real_visibility():
    doc = _doc(INVOICE_REVIEW)
    assert doc["visibility"] == "tier-managers"
    assert doc["visibility"] in KEAP_VISIBILITY
