"""Anatomy CI gate — the septum: every KEAP table def says whose data it holds.

One person, many clients on one host (Model C). `client_scope:` in each
state/keap-tables/*.table.yml names the path from a row to the client party:
  none        estate/system data — no person, no client
  personal    the person's own data (should be `visibility: private`)
  self        the row IS a party (party table only; client iff role: client)
  book_owner  the `book_owner` rowRef → party
  rowRef:<c>  rowRef column <c> → party, or → a table that is itself scoped
  unresolved  holds client data, but no column names the client (a known gap;
              tools/septum-status.py reports it red)
This is a DECLARATION, not row isolation: KEAP enforces no per-row owner yet.
A missing key, an unwalkable path, or `none`/`personal` on a table whose rowRefs
reach `party` is red. Committed defs carry no `unresolved`, and every `personal`
table is `visibility: private` (operator ruling R5, 2026-10-16). Reader: tools/septum-status.py.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TABLES = REPO / "state" / "keap-tables"
FIXED = {"none", "personal", "self", "book_owner", "unresolved"}
NOT_CLIENT = {"none", "personal"}


def _defs() -> dict[str, dict]:
    return {p.name.removesuffix(".table.yml"): yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            for p in sorted(TABLES.glob("*.table.yml"))}


def _refs(d: dict) -> dict[str, str]:
    cols = (d.get("schema") or {}).get("columns") or []
    return {c["key"]: c.get("refTable") for c in cols if c.get("kind") == "rowRef"}


def _reaches_party(name: str, defs: dict, seen: frozenset = frozenset()) -> bool:
    if name == "party":
        return True
    if name in seen or name not in defs:
        return False
    return any(_reaches_party(t, defs, seen | {name}) for t in _refs(defs[name]).values())


def errors(name: str, defs: dict) -> list[str]:
    d = defs[name]
    if "client_scope" not in d:
        return [f"{name}: no client_scope"]
    s, refs = d["client_scope"], _refs(d)
    if not isinstance(s, str) or not (s in FIXED or s.startswith("rowRef:")):
        return [f"{name}: client_scope {s!r} is not one of {sorted(FIXED)} or rowRef:<column>"]
    if s == "self" and name != "party":
        return [f"{name}: only the party table is `self`"]
    if s == "book_owner" and refs.get("book_owner") != "party":
        return [f"{name}: book_owner scope needs a book_owner rowRef → party"]
    if s.startswith("rowRef:"):
        col = s.split(":", 1)[1]
        target = refs.get(col)
        if not target:
            return [f"{name}: {s} names no rowRef column"]
        tscope = (defs.get(target) or {}).get("client_scope")
        if target != "party" and (tscope in NOT_CLIENT or tscope is None):
            return [f"{name}: {s} → {target}, which is not client-scoped ({tscope!r})"]
    if s in NOT_CLIENT and _reaches_party(name, defs):
        return [f"{name}: `{s}` but its rowRefs reach party — say the path, or `unresolved`"]
    return []


DEFS = _defs()


@pytest.mark.parametrize("name", sorted(DEFS))
def test_table_declares_its_client_scope(name):
    assert errors(name, DEFS) == []


@pytest.mark.parametrize("name", sorted(DEFS))
def test_table_names_its_client_and_hides_the_personal(name):
    d = DEFS[name]
    assert d.get("client_scope") != "unresolved", f"{name}: add a book_owner rowRef → party"
    if d.get("client_scope") == "personal":
        assert d.get("visibility") == "private", f"{name}: personal data at {d.get('visibility')!r}"


def test_the_gate_has_teeth():
    party = {"schema": {"columns": [{"key": "slug", "kind": "text"}]}, "client_scope": "self"}
    cols = {"schema": {"columns": [{"key": "who", "kind": "rowRef", "refTable": "party"}]}}
    assert errors("t", {"party": party, "t": cols}) == ["t: no client_scope"]
    assert errors("t", {"party": party, "t": {**cols, "client_scope": "none"}})
    assert errors("t", {"party": party, "t": {**cols, "client_scope": "rowRef:nope"}})
    assert errors("t", {"party": party, "t": {**cols, "client_scope": "book_owner"}})
    assert errors("t", {"party": party, "t": {**cols, "client_scope": "self"}})
    assert errors("t", {"party": party, "t": {**cols, "client_scope": "rowRef:who"}}) == []
