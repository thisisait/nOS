"""The Kolben IT fixture: real structure, synthetic people — by measurement.

The SECOND business fixture (docs/idea/15-business-fixture.md), a synthetic
Czech IT-services shop. Same referee as the label printer
(test_fixture_tables_declare_the_business.py) — that gate is hardcoded to the
label-printer ORDER, so a new fixture is a CLONE with its own ORDER/SEED/SEEDER,
not an entry appended to a list. Every rule a converge would enforce with a
400 three seconds too late is refereed here offline, plus the one rule no
runtime enforces: synthetic people.

Kolben's core object is a TICKET with an SLA deadline (one level up from a
print job). The two domain invariants below replace the label printer's
billing/delivery + pinch-machine ones: the fixture exists to answer "which
OPEN tickets breach their due date if engineer X is out", so there must be a
deadline-bearing open ticket, and an engineer whose absence slips more than one
deadline (a discriminating pinch — otherwise the cortex question is a per-row
lookup a document could answer).
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TABLES_DIR = REPO / "state/keap-tables"
SEED = REPO / "state/fixtures/kolben-it.seed.yml"
SEEDER = REPO / "roles/pazny.keap/tasks/seed-kolben-fixture-tables.yml"
CONFIG = REPO / "default.config.yml"

#: Dependency order — must match the seeder's list verbatim. The shared party
#: spine leads (Kolben re-seeds it, idempotent by slug) so every rowRef target
#: is a member of this fixture's own ORDER (self-contained; design-doc proof 3).
ORDER = [
    "party",
    "party-tax-identity",
    "party-address",
    "party-contact",
    "kolben-engineer",
    "kolben-project",
    "kolben-ticket",
    "kolben-time-entry",
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
        assert "slug" in keys, f"{slug} has no slug column (the row id the upsert keys on)"
        assert len(keys) == len(set(keys)), f"{slug} declares a duplicate column key"


def test_every_rowref_is_restrict_and_points_backward():
    for slug in ORDER:
        for col in _def(slug)["schema"]["columns"]:
            if col.get("kind") != "rowRef":
                continue
            ref = col.get("refTable")
            assert ref in ORDER, (
                f"{slug}.{col['key']} references {ref!r}, not a fixture table — "
                "the fixture must be self-contained or a blank cannot recreate it"
            )
            assert ORDER.index(ref) < ORDER.index(slug), (
                f"{slug}.{col['key']} references {ref!r}, seeded AFTER it — "
                "KEAP validates refTable at create, so this order 400s the converge"
            )
            assert col.get("onDelete") == "restrict", (
                f"{slug}.{col['key']}: onDelete must be 'restrict' — a ticket "
                "whose project vanished is a corrupt record, not an orphan to tidy"
            )
            assert col.get("refDisplay"), (
                f"{slug}.{col['key']} has no refDisplay — the cell renders as a bare slug"
            )


def test_the_junction_is_a_real_junction():
    refs = [c for c in _def("kolben-time-entry")["schema"]["columns"] if c.get("kind") == "rowRef"]
    assert len(refs) == 2, (
        f"kolben-time-entry carries {len(refs)} rowRef columns, not 2. The N:N "
        "junction is ticket × engineer, and the EDGE carries the attributes "
        "(hours, date, billable)"
    )


def test_the_seeder_walks_the_same_order():
    text = SEEDER.read_text()
    declared = re.findall(r'^\s+- slug: "([a-z-]+)"$', text, re.MULTILINE)
    assert declared == ORDER, (
        f"seed-kolben-fixture-tables.yml order {declared} != the dependency "
        "order this gate checks refs against — a different order 400s the converge"
    )
    assert "{% for" not in text and "{%- for" not in text, (
        "the seeder builds its table list with a Jinja for-loop — under "
        "non-native Jinja that is a string, and the loop iterates characters"
    )
    flag = yaml.safe_load(CONFIG.read_text()).get("keap_seed_kolben_fixture")
    assert flag is False, (
        "keap_seed_kolben_fixture must default false — a public nOS install "
        "does not grow an IT shop unasked"
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


def test_a_deadline_bearing_open_ticket_exists():
    """The SLA object the fixture exists to reason about."""
    tickets = _seed()["kolben-ticket"]
    live = [
        t for t in tickets
        if t["status"] != "done" and t.get("due") and t["priority"] in ("high", "critical")
    ]
    assert live, (
        "no open high/critical ticket carries a due date — the SLA-breach "
        "shape the whole fixture exists to exercise is unexercised, and "
        "'which tickets breach if engineer X is out' has no subject"
    )


def test_an_engineer_is_a_discriminating_pinch():
    """An engineer whose absence slips MORE THAN ONE deadline, and engineers
    whose absences differ — or the cortex question collapses to a per-row lookup
    (the print-shop pinch-machine invariant, in ticket terms)."""
    tickets = [t for t in _seed()["kolben-ticket"] if t["status"] != "done"]
    by_eng: dict[str, set] = {}
    for t in tickets:
        by_eng.setdefault(t["assignee"], set()).add(t["slug"])
    pinch = [e for e, ts in by_eng.items() if len(ts) >= 2]
    assert pinch, (
        "no engineer is assigned two or more open tickets — 'which deadlines "
        "slip if engineer X is out' collapses to a per-ticket lookup"
    )
    assert any(len(ts) == 1 for ts in by_eng.values()), (
        "every engineer carries the same load — the absence questions all have "
        "the same answer and the fixture cannot show a query DISCRIMINATING"
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
        "fixture's own Article-30 register entry AND the company's written yes "
        "(docs/idea/15-business-fixture.md):\n  " + "\n  ".join(problems)
    )
    # Positive controls — the loops above must have had subjects.
    assert any(r["party_kind"] == "person" for r in seed["party"])
    assert any(r["kind"] == "email" for r in seed["party-contact"])
