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


# Columns deliberately WITHOUT a concept, each with the reason — the same
# idiom as UNSEEDED below, and subject to the same pruning discipline
# (test_the_conceptless_excuse_is_not_stale). Added 2026-08-14 with the
# label-printer fixture (w-fixture), whose EN 16931 tables hold data the
# CLOSED vocabulary has no words for yet: postal geography, tax identifiers,
# measures, counterparties, validity windows. The alternative was stretching
# a neighbour — country as `class.group`, a VAT id as `identity.name` — and a
# WRONG meaning poisons exactly the cross-table queries concepts exist for:
# "every column meaning identity.name" must never return a tax number.
# The vocabulary grows in KEAP (`shared/contracts/field-concepts.ts`), then
# re-vendors, then these rows are PRUNED — that order is this gate's own
# instruction in test_declared_concepts_exist_in_the_vendored_vocabulary,
# and the concepts to propose upstream are named per row.
CONCEPTLESS = {
    "party.trading_name": "secondary name; identity.name is (rightly) the legal name — needs identity.alias",
    "party.country": "no geography concept exists — needs place.country",
    "party-address.street": "no postal concepts exist — needs place.street",
    "party-address.street2": "same — place.street2 or a structured place.address",
    "party-address.city": "same — place.city",
    "party-address.postcode": "same — place.postcode",
    "party-address.subdivision": "same — place.subdivision (NUTS/ISO 3166-2)",
    "party-address.country": "same — place.country",
    "party-contact.value": "one column, three channels (email|phone|web); net.url fits only one of them",
    "party-contact.role": "free-text qualifier of the channel, not a class.* of the row",
    "party-tax-identity.value": "a tax identifier is not identity.name; needs identity.registration",
    "party-tax-identity.valid_to": "an expiry is neither time.target nor time.occurred_at — needs time.valid_to",
    "print-order.customer": "no counterparty concept; graph.parent would claim the order nests under the customer",
    "caddy.value": "the value of an operator setting is not identity.* or lifecycle.status — needs config.value",
    "caddy-sessions.model": "a model URI is not deploy.image (that is a container) — needs llm.model",
    "caddy-sessions.transcript": "a speech transcript is not identity.description — needs media.transcript",
    "caddy-sessions.chain": "a cortex-lang program is not any closed concept — needs lang.program",
    "caddy-sessions.rating_before": "an operator label is not a lifecycle or a measure of the row — needs eval.rating",
    "caddy-sessions.rating_after": "same — eval.rating, with the phase as the column name",
    "print-job.quantity": "no measure concept — needs measure.quantity",
    "print-material.unit": "the measure's unit, not a class.* of the material — needs measure.unit",
    "print-job-step.planned_end": "time.target is claimed by planned_start (once-per-table rule); needs a window pair",
    "print-job-step.actual_start": "time.occurred_at is claimed by actual_end (same) — same window pair",
    "kolben-project.client": "no counterparty concept; graph.parent would claim the project nests under the client — same as print-order.customer",
    "kolben-project.budget": "no money/measure concept — needs measure.amount (a budget is not identity.* or a lifecycle)",
    "kolben-time-entry.hours": "no measure concept — needs measure.duration (hours logged is a quantity, like print-job.quantity)",
}


def test_every_seeded_column_declares_a_concept():
    missing = [
        f"{name}.{c['key']}"
        for name, doc in _definitions()
        for c in doc["schema"]["columns"]
        if not c.get("concept") and f"{name}.{c['key']}" not in CONCEPTLESS
    ]
    assert not missing, (
        "columns with no declared meaning — they carry a storage kind and an "
        "OLAP role, and nothing a cross-table consumer can key on:\n  "
        + "\n  ".join(missing)
        + "\nDeclare a concept from the vendored vocabulary, or — ONLY when "
        "the vocabulary genuinely lacks the meaning — add a CONCEPTLESS row "
        "naming the concept KEAP should grow."
    )


def test_the_conceptless_excuse_is_not_stale():
    """Every excused column must exist and still be concept-less.

    The excuse list is a debt register, not a bypass: a row for a column that
    gained a concept (pay-down) or that no longer exists (ghost) is a stale
    entry hiding future drift — the same pruning contract UNSEEDED carries.
    """
    cols = {
        f"{name}.{c['key']}": c.get("concept")
        for name, doc in _definitions()
        for c in doc["schema"]["columns"]
    }
    stale = [
        key for key in CONCEPTLESS
        if key not in cols or cols[key] is not None
    ]
    assert not stale, (
        "CONCEPTLESS rows that no longer excuse anything — the column gained "
        "a concept or is gone; prune them so the gate covers it again:\n  "
        + "\n  ".join(stale)
    )


#: KEAP's `tableVisibilitySchema` (~/keap/src/shared/contracts/table.ts). Copied,
#: because it lives in another repo and nothing here can import it — which makes
#: this the THIRD instance in one day of the same seam (the `chat` style and the
#: system-table flag are the others; roadmap row `ext-contract`).
KEAP_VISIBILITY = {"private", "tier-managers", "tier-users", "tier-guests", "shared"}


def test_visibility_is_a_value_keap_will_accept():
    """MEASURED THE HARD WAY 2026-08-31: `tier-admins` is not a KEAP visibility.

    It reads like the obvious tightening of `tier-managers`, it passed every
    offline gate here, and it 400'd on the converge — `Invalid enum value.
    Expected 'private' | 'tier-managers' | 'tier-users' | 'tier-guests' |
    'shared', received 'tier-admins'` — after the play had already done 431
    tasks of work. A definition this repo owns and another repo validates is
    exactly the shape that must be checked BEFORE the converge, not by it.
    """
    bad = [
        f"{name}: visibility: {doc.get('visibility')}"
        for name, doc in _definitions()
        if doc.get("visibility") and doc["visibility"] not in KEAP_VISIBILITY
    ]
    assert not bad, (
        "visibility values KEAP's enum does not contain — the seeder will 400 "
        "mid-converge:\n  " + "\n  ".join(bad)
        + f"\nAllowed: {sorted(KEAP_VISIBILITY)}"
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
    "loop-config": "the one row (harness_proposals_enabled) has NO READER — "
                   "ledger.py refuses `harness` unconditionally. Seeding it puts "
                   "a flippable switch in front of the operator that changes "
                   "nothing, which is the fabricated-affordance shape this estate "
                   "keeps paying for. The committed fixture is the value Wing "
                   "/loop-editor renders; wiring the rows through the playbook "
                   "belongs to the cycle that teaches the ledger to read it.",
    "roadmap":"rows come from tools/roadmap-seed.py, not the playbook seeder — "
               "same split as apps and systems. The DEFINITION is git-owned here; "
               "wiring the rows through the playbook is a decision, not an oversight.",
}


def test_every_definition_is_either_seeded_or_explicitly_excused():
    # EVERY seeder, discovered rather than listed (2026-08-31). It named two
    # files — the face tables and the label-printer fixture — and a third
    # (seed-caddy-tables.yml) made the gate report its own blind spot as an
    # orphan table. A hardcoded pair is a detector that goes stale the moment
    # the thing it detects grows, so it now globs: any `seed-*-tables.yml` in
    # the role is a place a definition may land.
    seeders = sorted((REPO / "roles" / "pazny.keap" / "tasks").glob("seed-*-tables.yml"))
    assert seeders, "no seeder task files found — path drift?"
    src = "\n".join(p.read_text() for p in seeders)
    orphans = sorted(
        name
        for name, _ in _definitions()
        if f'slug: "face-{name}"' not in src
        and f'slug: "{name}"' not in src
        and name not in UNSEEDED
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
