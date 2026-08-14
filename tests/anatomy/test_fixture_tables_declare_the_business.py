"""The label-printer fixture: real structure, synthetic people — by measurement.

WHAT THIS GUARDS (w-fixture increment 1, docs/idea/15-business-fixture.md).
Nine DataTable definitions in state/keap-tables/ plus one seed file in
state/fixtures/ become a live tenant only at a converge — so every rule a
converge would enforce with a 400 three seconds too late is refereed here,
offline, plus the one rule no runtime enforces at all.

THE ONE RULE NO RUNTIME ENFORCES: synthetic people. The fixture's design doc
ships exactly one rule — "Real structure, synthetic people — until an Article
30 register entry exists" and the company has said yes in writing. The
register that shipped 2026-08-13 (88 records) covers the AGENT ceremonies'
processors; it does NOT cover label-printer customer data, so "unblocked"
licenses building the structure, not loading people. KEAP will happily store
a real customer; only this gate refuses one. It is measurement, not vibes:
emails must end in `.invalid` (RFC 2606 reserved — undeliverable by
standard), phones must sit in the +420 000 reserved shape, tax identifiers in
the 000001xx range no registry issues, and party slugs must say `synthetic-`
so no query result can quietly read as real. Loading real customers first and
documenting later is, in the doc's words, the sequence that cannot be undone.

THE OFFLINE REFEREE HALF, in converge order:
  * defs parse and mirror the catalog shape (title/driver/visibility/schema,
    slug column — the row id the seeder's WHERE-guard keys on)
  * every rowRef declares refTable + refDisplay + onDelete: restrict (a
    legal record's party vanishing is corruption, not an orphan to tidy —
    docs/archive/datatables-relations.md), and refTable points INSIDE the
    fixture set, at a table seeded EARLIER (KEAP validates refTable at
    create; a forward reference 400s the converge)
  * the N:N junction is a real junction: print-job-step carries exactly two
    rowRef columns (the doctrine's "never an array cell")
  * the seed resolves: every rowRef value is a seeded slug of its refTable,
    every select value is in options, every required column is present
  * the EN 16931 ask the design doc names outright: a billing address and a
    delivery address for the same party that actually differ
  * the pinch is real: one machine is on the path of EVERY job, so "which
    jobs miss their deadline if it stops" has a non-trivial answer — the
    fixture's whole reason to exist as a cortex subject

Verified live only at converge: KEAP's own schema validation and referential
integrity, and proof 3 (blank → converge recreates the tenant). Named here so
the converge operator knows this gate's green is necessary, not sufficient.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TABLES_DIR = REPO / "state/keap-tables"
SEED = REPO / "state/fixtures/label-printer.seed.yml"
SEEDER = REPO / "roles/pazny.keap/tasks/seed-fixture-tables.yml"
CONFIG = REPO / "default.config.yml"

#: Dependency order — must match the seeder's _fixture_table_order verbatim.
ORDER = [
    "party",
    "party-tax-identity",
    "party-address",
    "party-contact",
    "print-machine",
    "print-material",
    "print-order",
    "print-job",
    "print-job-step",
]


def _def(slug: str) -> dict:
    return yaml.safe_load((TABLES_DIR / f"{slug}.table.yml").read_text())


def _seed() -> dict:
    return yaml.safe_load(SEED.read_text())


def test_the_defs_mirror_the_catalog_shape():
    for slug in ORDER:
        d = _def(slug)
        for key in ("title", "description", "driver", "visibility", "schema"):
            assert key in d, f"{slug}.table.yml missing top-level '{key}'"
        assert d["driver"] == "libsql"
        cols = d["schema"]["columns"]
        keys = [c["key"] for c in cols]
        assert "slug" in keys, (
            f"{slug} has no slug column — the seeder's idempotency WHERE-guard "
            "and KEAP's slug-as-row-id upsert both key on it; without it every "
            "re-seed inserts duplicates"
        )
        assert len(keys) == len(set(keys)), f"{slug} declares a duplicate column key"


def test_every_rowref_is_restrict_and_points_backward():
    for slug in ORDER:
        for col in _def(slug)["schema"]["columns"]:
            if col.get("kind") != "rowRef":
                continue
            ref = col.get("refTable")
            assert ref in ORDER, (
                f"{slug}.{col['key']} references {ref!r}, which is not a "
                "fixture table — the fixture must be self-contained or a blank "
                "cannot recreate it (design-doc proof 3)"
            )
            assert ORDER.index(ref) < ORDER.index(slug), (
                f"{slug}.{col['key']} references {ref!r}, seeded AFTER it — "
                "KEAP validates refTable at create, so this order 400s the "
                "converge"
            )
            assert col.get("onDelete") == "restrict", (
                f"{slug}.{col['key']}: onDelete must be 'restrict' — a job "
                "whose order vanished is a corrupt record, not an orphan to "
                "tidy (datatables-relations doctrine)"
            )
            assert col.get("refDisplay"), (
                f"{slug}.{col['key']} has no refDisplay — every reference "
                "cell renders as a bare uuid/slug in the face grid"
            )


def test_the_junction_is_a_real_junction():
    refs = [c for c in _def("print-job-step")["schema"]["columns"] if c.get("kind") == "rowRef"]
    assert len(refs) == 2, (
        f"print-job-step carries {len(refs)} rowRef columns, not 2. The N:N "
        "doctrine is a junction with two refs whose EDGE carries the "
        "attributes (step order, window) — one ref is a 1:N in disguise, "
        "three is a different relation"
    )


def test_the_seeder_walks_the_same_order():
    text = SEEDER.read_text()
    declared = re.findall(r'^\s+- slug: "([a-z-]+)"$', text, re.MULTILINE)
    assert declared == ORDER, (
        f"seed-fixture-tables.yml order {declared} != the dependency order "
        "this gate checks refs against — KEAP validates refTable at create, "
        "so the seeder walking a different order 400s the converge"
    )
    # The assembled list must be literal YAML, not a Jinja-rendered string:
    # without jinja2_native a {% for %}-built list lands in set_fact as its
    # repr and the include loop iterates CHARACTERS. Caught at authoring time
    # (2026-08-14) — this pin keeps the shortcut from coming back.
    assert "{% for" not in text and "{%- for" not in text, (
        "seed-fixture-tables.yml builds its table list with a Jinja for-loop "
        "— under non-native Jinja that is a string, and the seeder loops "
        "over characters instead of tables"
    )
    flag = yaml.safe_load(CONFIG.read_text()).get("keap_seed_business_fixture")
    assert flag is False, (
        "keap_seed_business_fixture must default false — a public nOS install "
        "does not grow a label printer unasked"
    )


def test_the_seed_resolves_against_itself():
    seed = _seed()
    assert set(seed) == set(ORDER), (
        f"seed tables {sorted(seed)} != declared tables — a def without rows "
        "or rows without a def is half a fixture"
    )
    slugs = {t: {r["slug"] for r in rows} for t, rows in seed.items()}
    for t, rows in seed.items():
        assert len(slugs[t]) == len(rows), f"{t}: duplicate row slug"
        cols = {c["key"]: c for c in _def(t)["schema"]["columns"]}
        for row in rows:
            for key, value in row.items():
                assert key in cols, f"{t}/{row['slug']}: unknown column {key!r}"
                col = cols[key]
                if col.get("kind") == "rowRef":
                    assert value in slugs[col["refTable"]], (
                        f"{t}/{row['slug']}.{key} -> {value!r} not seeded in "
                        f"{col['refTable']} — the converge's row upsert 400s"
                    )
                if col.get("kind") == "select":
                    assert value in col["options"], (
                        f"{t}/{row['slug']}.{key}={value!r} not in {col['options']}"
                    )
            for key, col in cols.items():
                if col.get("required") and key != "slug":
                    assert key in row, f"{t}/{row['slug']} missing required {key!r}"


def test_billing_and_delivery_differ_for_the_same_party():
    """The EN 16931 case the design doc names outright."""
    rows = _seed()["party-address"]
    by_party: dict[str, dict[str, dict]] = {}
    for r in rows:
        by_party.setdefault(r["party"], {})[r["purpose"]] = r
    split = [
        p for p, a in by_party.items()
        if "billing" in a and "delivery" in a
        and (a["billing"]["street"], a["billing"]["city"])
        != (a["delivery"]["street"], a["delivery"]["city"])
    ]
    assert split, (
        "no party bills to one address and takes delivery at another — the "
        "one EN 16931 shape the fixture exists to exercise is unexercised, "
        "and the schema degenerates back into the flat Business-partners form"
    )


def test_the_pinch_machine_exists():
    seed = _seed()
    jobs = {r["slug"] for r in seed["print-job"]}
    on_machine: dict[str, set] = {}
    for step in seed["print-job-step"]:
        on_machine.setdefault(step["machine"], set()).add(step["job"])
    pinch = [m for m, js in on_machine.items() if js == jobs]
    assert pinch, (
        "no machine sits on the path of every job — 'which jobs miss their "
        "deadline if it stops' collapses to a per-job lookup and the fixture "
        "stops asking the cortex anything a document could not answer"
    )
    assert any(js < jobs for js in on_machine.values()), (
        "every machine touches every job — the two stop-questions have the "
        "same answer and the fixture cannot show a query DISCRIMINATING"
    )


def test_the_people_are_synthetic_by_measurement():
    seed = _seed()
    problems = []
    for r in seed["party"]:
        if not r["slug"].startswith("synthetic-"):
            problems.append(f"party {r['slug']}: slug does not say synthetic-")
    for r in seed["party-contact"]:
        v = r["value"]
        if r["kind"] == "email" and not v.endswith(".invalid"):
            problems.append(f"contact {r['slug']}: email {v!r} is deliverable")
        if r["kind"] == "phone" and not v.startswith("+420 000"):
            problems.append(f"contact {r['slug']}: phone {v!r} outside the reserved range")
        if r["kind"] == "web" and not v.endswith(".invalid"):
            problems.append(f"contact {r['slug']}: url {v!r} resolves")
    for r in seed["party-tax-identity"]:
        if not re.fullmatch(r"(CZ)?000001\d\d", r["value"]):
            problems.append(f"tax {r['slug']}: {r['value']!r} outside the synthetic range")
    assert not problems, (
        "a seeded value stopped looking synthetic. Real people require the "
        "fixture's own Article-30 register entry AND the company's written "
        "yes (docs/idea/15-business-fixture.md) — neither exists, and the "
        "agent-processor register entries of 2026-08-13 do not cover this "
        "data:\n  " + "\n  ".join(problems)
    )
    # Positive controls — the loops above must have had subjects, or every
    # rule passes by absence.
    assert any(r["party_kind"] == "person" for r in seed["party"])
    assert any(r["kind"] == "email" for r in seed["party-contact"])
