"""Anatomy gate — every seeded DataTable column declares WHAT IT MEANS (L1).

A column carries two machine facts today: `kind` (how the value is stored) and
`role` (how OLAP may aggregate it). Neither says what the column MEANS. `status`
appears in four of the five seeded tables as four unrelated strings; `owner`,
`slug` and `taxonomy_ref` appear in all five. Nothing ties them together, so no
consumer — face, Wing, an agent, a future Rust brain — can ask "every column
meaning lifecycle status" across the estate. That is the "no common
denominator" problem, stated for one organ.

L1 closes it with a CLOSED vocabulary (`shared/contracts/field-concepts.ts` in
the KEAP repo, vendored here) plus a membership gate. This test is the nOS half:
the definitions in `state/keap-tables/` must declare a concept for every column,
from that vocabulary, at most once per table.

THE SECOND HALF MATTERS MORE, and is `test_keap_table_seeder_reconciles`:
before 2026-08-01 `data_tables.schema_json` had exactly one writer (the create
INSERT) and no UPDATE anywhere, and the seeder gated its create on a 404. So a
concept declared here would have landed in git, turned this very test green, and
never reached a converged install — a gate passing while delivering nothing.
Declaring meaning is only worth anything if the declaration can travel.

CI-safe: pure file parsing. No Docker, no live host, no KEAP checkout required
(the vocabulary is read from the vendored contract when present, else from the
concepts the definitions actually use, which still enforces internal
consistency).
"""
from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TABLE_DIR = REPO / "state" / "keap-tables"
# Vendored copy of the KEAP contract, when the cortex organ is vendored in.
VENDORED_VOCAB = REPO / "files" / "anatomy" / "cortex" / "shared" / "contracts" / "field-concepts.ts"

CONCEPT_ID = re.compile(r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9_]*)+$")


def _definitions() -> list[tuple[str, dict]]:
    files = sorted(TABLE_DIR.glob("*.table.yml"))
    assert files, f"no table definitions under {TABLE_DIR} — path drift?"
    return [(f.stem.replace(".table", ""), yaml.safe_load(f.read_text())) for f in files]


def _vendored_concept_ids() -> set[str] | None:
    """Concept ids from the vendored KEAP contract, or None when not vendored."""
    if not VENDORED_VOCAB.is_file():
        return None
    ids = set(re.findall(r"\{\s*id:\s*'([^']+)'", VENDORED_VOCAB.read_text()))
    return ids or None


def test_every_seeded_column_declares_a_concept():
    missing = [
        f"{name}.{c['key']}"
        for name, doc in _definitions()
        for c in doc["schema"]["columns"]
        if not c.get("concept")
    ]
    assert not missing, (
        "columns with no declared meaning — they carry a storage kind and an "
        "OLAP role, and nothing a cross-table consumer can key on:\n  "
        + "\n  ".join(missing)
    )


def test_concept_ids_are_well_formed():
    bad = [
        f"{name}.{c['key']} -> {c['concept']}"
        for name, doc in _definitions()
        for c in doc["schema"]["columns"]
        if c.get("concept") and not CONCEPT_ID.match(str(c["concept"]))
    ]
    assert not bad, "concept ids must be lowercase namespace.name:\n  " + "\n  ".join(bad)


def test_one_concept_is_declared_at_most_once_per_table():
    """Two columns claiming one meaning makes every query-by-concept ambiguous,
    which is the entire thing concepts are for. Reuse ACROSS tables is the point
    and stays legal."""
    offenders = []
    for name, doc in _definitions():
        seen: dict[str, str] = {}
        for c in doc["schema"]["columns"]:
            con = c.get("concept")
            if not con:
                continue
            if con in seen:
                offenders.append(f"{name}: {c['key']} and {seen[con]} both claim {con}")
            seen[con] = c["key"]
    assert not offenders, "\n  ".join(["duplicate meanings within one table:"] + offenders)


def test_declared_concepts_exist_in_the_vendored_vocabulary():
    """The vocabulary is CLOSED. A typo must be a failure here, not a silently
    accepted free-text string that no consumer will ever match."""
    known = _vendored_concept_ids()
    if known is None:
        pytest.skip("cortex organ not vendored in this checkout — KEAP's own gate covers it")
    unknown = sorted(
        {
            f"{name}.{c['key']} -> {c['concept']}"
            for name, doc in _definitions()
            for c in doc["schema"]["columns"]
            if c.get("concept") and c["concept"] not in known
        }
    )
    assert not unknown, (
        "concepts not in the vendored vocabulary — add them to KEAP's "
        "shared/contracts/field-concepts.ts and re-vendor first:\n  " + "\n  ".join(unknown)
    )


# Definitions that exist but are deliberately NOT seeded, with the reason.
# Measured live 2026-08-01: GET /agent/v1/tables/face-{apps,systems} both 404,
# while controls/layouts/wallpapers are 200. So 44 of the 76 columns annotated
# with an L1 concept belong to tables that do not exist on a converged host.
#
# That is not an oversight to paper over: both catalogs are fed from elsewhere
# (the service registry, the app generator), and seeding them here would create
# two empty tables whose rows another writer then has to reconcile against.
# Wiring them is a decision, not a fix. What this allowlist buys is that the
# NEXT definition to drift out of the seeder is caught the day it happens
# instead of being found by hand a release later.
UNSEEDED = {
    "apps": "fed by the app generator, not the playbook seeder — wiring it is a decision",
    "systems": "fed by the service registry — same",
    "roadmap": "rows come from tools/roadmap-seed.py, not the playbook seeder — "
               "same split as apps and systems. The DEFINITION is git-owned here; "
               "wiring the rows through the playbook is a decision, not an oversight.",
}


def test_every_definition_is_either_seeded_or_explicitly_excused():
    src = (REPO / "roles" / "pazny.keap" / "tasks" / "seed-face-tables.yml").read_text()
    orphans = sorted(
        name
        for name, _ in _definitions()
        if f'slug: "face-{name}"' not in src and name not in UNSEEDED
    )
    assert not orphans, (
        "table definitions no seeder entry references — they carry concepts, "
        "columns and GDPR intent for a table that never exists:\n  "
        + "\n  ".join(orphans)
        + "\nAdd a seeder entry, or add it to UNSEEDED with the reason."
    )


def test_the_excuse_list_does_not_outlive_its_reason():
    """An allowlist nobody prunes becomes a permanent blind spot."""
    src = (REPO / "roles" / "pazny.keap" / "tasks" / "seed-face-tables.yml").read_text()
    stale = sorted(n for n in UNSEEDED if f'slug: "face-{n}"' in src)
    assert not stale, (
        "these are seeded now — drop them from UNSEEDED so the gate covers them: "
        + ", ".join(stale)
    )


def test_keap_table_seeder_reconciles():
    """The load-bearing one: the seeder must not gate its create on a 404.

    With `when: probe.status == 404` the definition file was write-once. KEAP's
    POST /agent/v1/tables early-returned "already exists" and there was no
    UPDATE of data_tables.schema_json anywhere, so on every converged install a
    changed definition changed nothing — silently, at exit 0. Retro-check: this
    assertion fails against the pre-2026-08-01 task.
    """
    src = (REPO / "roles" / "pazny.keap" / "tasks" / "seed-face-table.yml").read_text()
    tasks = [t for t in (yaml.safe_load(src) or []) if isinstance(t, dict)]
    create = [t for t in tasks if "/agent/v1/tables" in str(t.get("ansible.builtin.uri", {}).get("url", ""))
              and t.get("ansible.builtin.uri", {}).get("method") == "POST"
              and "rows" not in str(t.get("ansible.builtin.uri", {}).get("url", ""))]
    assert create, "no POST /agent/v1/tables task found — task shape changed; update this gate"
    for t in create:
        cond = str(t.get("when", ""))
        assert "404" not in cond, (
            f"task {t.get('name')!r} still runs only when the table is MISSING; a "
            "changed column definition would never reach a converged install"
        )
        codes = t["ansible.builtin.uri"].get("status_code", [])
        assert 409 in codes, (
            f"task {t.get('name')!r} does not accept 409 — KEAP answers 409 when a "
            "definition asks for a destructive change, and an unlisted status "
            "fails with a bare HTTP error instead of the authoring diagnosis"
        )
