"""Anatomy CI gate — every docs/ directory is a realm or declared outside one;
the plan surfaces only shrink.

Repo body plan I-16 (roadmap row plan-homes-frozen-docs-realms, 2026-10-06):
docs/plans/README.md said "retired 2026-08-02" while 19 files sat under it, one
dated 2026-10-06; docs/idea had a ceiling in a sibling gate and docs/drafts had
none. New work is captured as a roadmap row (/dtt-capture), never as a new file
in these trees, so each frozen surface carries a `ceiling` in ssot/INDEX.yml
that may only fall. Lowering it is routine; raising it is the loud act.

Every top-level docs/ directory is either a realm path (ssot/INDEX.yml
`realms.<name>.path`) or listed under `unrealmed:` with the reason it is not one.
A directory in neither is a tree nobody owns.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
INDEX = yaml.safe_load((REPO / "ssot/INDEX.yml").read_text(encoding="utf-8"))

#: Surfaces that may only shrink; each needs a `ceiling` in the INDEX.
FROZEN = ("docs/idea", "docs/plans", "docs/drafts")


def _entries() -> dict[str, dict]:
    """path → its INDEX entry, realms and unrealmed alike."""
    out = {spec["path"]: spec for spec in INDEX["realms"].values()}
    out.update({e["path"]: e for e in INDEX.get("unrealmed") or []})
    return out


def _count(rel: str) -> int:
    return sum(1 for p in (REPO / rel).rglob("*") if p.is_file() and not p.name.startswith("."))


def test_every_docs_dir_is_a_realm_or_declared_unrealmed():
    known = {p.rstrip("/") for p in _entries()}
    loose = sorted(f"docs/{d.name}" for d in (REPO / "docs").iterdir()
                   if d.is_dir() and f"docs/{d.name}" not in known)
    assert not loose, (
        f"docs/ directories that are no realm path and not under ssot/INDEX.yml "
        f"`unrealmed:` (with a `why`): {loose}")


def test_each_unrealmed_dir_has_a_reason():
    bad = [e.get("path") for e in INDEX.get("unrealmed") or []
           if not str(e.get("why") or "").strip() or not (REPO / e["path"]).is_dir()]
    assert not bad, f"unrealmed entries without a `why` or without a directory: {bad}"


def test_frozen_surfaces_only_shrink():
    entries = _entries()
    bad = []
    for rel in FROZEN:
        ceiling = (entries.get(rel) or {}).get("ceiling")
        if not isinstance(ceiling, int):
            bad.append(f"{rel}: no integer `ceiling` in ssot/INDEX.yml")
            continue
        if (n := _count(rel)) > ceiling:
            bad.append(f"{rel}: {n} files against a ceiling of {ceiling} — new work "
                       "goes through /dtt-capture; raising the ceiling is the loud act")
    assert not bad, bad
