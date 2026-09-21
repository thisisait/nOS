"""The consulting-firm fixture: MODEL C data isolation, by measurement.

Third business fixture, first for the consulting-firm-deployment epic (D2).
Tenancy = MODEL C (operator 2026-09-19): the consultant is the sole USER;
each client firm is DATA, never a controller/tenant column
(docs/idea/17: "no tenant column, ever"). The referee this fixture needs is
therefore not "does the schema wire up" alone (that half is a straight clone
of test_kolben_fixture_declares_the_business.py's shape) but "does the
isolation invariant HOLD" — every posting of a balanced entry resolves,
through the account.party rowRef (never a code-string prefix), to exactly the
one client whose book that entry belongs to.

This file is retro-red: on today's tree (no seed, no fixture dir, no gate)
every test below fails on a missing file before it can even assert.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TABLES_DIR = REPO / "state/keap-tables"
SEED = REPO / "state/fixtures/consulting-firm.seed.yml"
DOCS_DIR = REPO / "state/fixtures/consulting-firm"
EXPECTED = DOCS_DIR / "expected.yml"
BUNDLE = REPO / "roles/pazny.keap/tasks/seed-bundle.yml"
CONFIG = REPO / "default.config.yml"

#: Dependency order — must match the seeder's list verbatim (self-contained;
#: no rowRef target outside this fixture's own table set).
ORDER = [
    "party",
    "party-tax-identity",
    "party-address",
    "party-contact",
    "account",
    "invoice",
    "invoice-line",
    "journal-entry",
    "posting",
    "pending-invoice-verify",
    "book-access",
]

CLIENTS = ["synthetic-client-alfa", "synthetic-client-beta", "synthetic-client-gama"]
#: IČOs copied off state/fixtures/vision-fixture/*.pdf — not the 000001xx
#: reserved range. Live absorb without --fixture-mode uses name (Hejsek /
#: Firma, checksum fail) or IČO (Apple, checksum ok).
VISION_PDF_TAX = {"87654321", "28897501", "45126489"}


def _def(slug: str) -> dict:
    return yaml.safe_load((TABLES_DIR / f"{slug}.table.yml").read_text())


def _seed() -> dict:
    return yaml.safe_load(SEED.read_text())


def _expected() -> dict:
    return yaml.safe_load(EXPECTED.read_text())


def _nos_accounting():
    spec = importlib.util.spec_from_file_location(
        "nos_accounting", REPO / "files" / "anatomy" / "module_utils" / "nos_accounting.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── Shape: the seed resolves against its own table defs ─────────────────────

def test_the_seed_key_order_is_the_dependency_order():
    assert list(_seed().keys()) == ORDER, (
        f"consulting-firm.seed.yml key order {list(_seed().keys())} != {ORDER}"
    )
    flag = yaml.safe_load(CONFIG.read_text()).get("keap_seed_consulting_fixture")
    assert flag is False, (
        "keap_seed_consulting_fixture must default false — a public nOS "
        "install does not grow a consulting-firm tenant unasked"
    )
    bundle_text = BUNDLE.read_text()
    assert "seed-bundle.yml" in (REPO / "roles/pazny.keap/tasks/post.yml").read_text(), (
        "post.yml must wire the consulting-firm bundle through the shared seeder"
    )
    assert "state/fixtures/consulting-firm.seed.yml" in (REPO / "roles/pazny.keap/tasks/post.yml").read_text()


def test_the_seed_resolves_against_itself():
    seed = _seed()
    assert set(seed) == set(ORDER), f"seed tables {sorted(seed)} != declared tables"
    slugs = {t: {r["slug"] for r in rows} for t, rows in seed.items()}
    for t, rows in seed.items():
        assert len(slugs[t]) == len(rows), f"{t}: duplicate row slug"
        cols = {c["key"]: c for c in _def(t)["schema"]["columns"]}
        for row in rows:
            for key, value in row.items():
                assert key in cols, f"{t}/{row['slug']}: unknown column {key!r}"
                col = cols[key]
                if col.get("kind") == "rowRef" and value not in (None, ""):
                    assert value in slugs[col["refTable"]], (
                        f"{t}/{row['slug']}.{key} -> {value!r} not seeded in {col['refTable']}"
                    )
                if col.get("kind") == "select":
                    assert value in col["options"], (
                        f"{t}/{row['slug']}.{key}={value!r} not in {col['options']}"
                    )
            for key, col in cols.items():
                if col.get("required") and key != "slug":
                    assert key in row, f"{t}/{row['slug']} missing required {key!r}"


def test_every_invoice_has_lines_that_sum_to_the_header():
    na = _nos_accounting()
    seed = _seed()
    assert na.lines_cover_invoices(seed["invoice"], seed["invoice-line"]) == []
    covered = {ln["invoice"] for ln in seed["invoice-line"]}
    assert covered == {i["slug"] for i in seed["invoice"]}


def test_every_invoice_carries_book_owner():
    """book_owner (D1) is what a per-client filter keys on — every seeded
    invoice must carry one, or the fixture cannot exercise D5's filter."""
    for inv in _seed()["invoice"]:
        assert inv.get("book_owner") in CLIENTS, (
            f"invoice {inv['slug']}: book_owner {inv.get('book_owner')!r} is "
            "not one of the fixture's three clients"
        )


# ── MODEL C: no controller/tenant column anywhere in this fixture ───────────

def test_model_c_no_controller_or_tenant_column():
    for t in ORDER:
        for col in _def(t)["schema"]["columns"]:
            key = col["key"].lower()
            assert "tenant" not in key and "controller" not in key, (
                f"{t}.{col['key']} looks like a tenant/controller column — "
                "MODEL C keeps isolation at the account.party rowRef only "
                "(docs/idea/17: 'no tenant column, ever')"
            )


# ── The isolation invariant itself ───────────────────────────────────────────

def test_every_client_has_at_least_two_balanced_entries():
    """Positive control: >=3 books (one per client), each with >=2 entries,
    so the isolation check below has real subjects, not an empty pass."""
    seed = _seed()
    postings_by_entry: dict[str, list] = {}
    for p in seed["posting"]:
        postings_by_entry.setdefault(p["entry"], []).append(p)

    entries_by_client: dict[str, list] = {c: [] for c in CLIENTS}
    invoice_by_slug = {i["slug"]: i for i in seed["invoice"]}
    for je in seed["journal-entry"]:
        inv = invoice_by_slug.get(je.get("source"))
        assert inv is not None, f"{je['slug']}: no source invoice — cannot attribute to a book"
        owner = inv["book_owner"]
        entries_by_client[owner].append(je["slug"])

    assert len(entries_by_client) >= 3, "fewer than 3 client books — no isolation to prove"
    for client, entries in entries_by_client.items():
        assert len(entries) >= 2, f"{client}: fewer than 2 journal entries — not a real book"


def test_isolation_invariant_via_account_party_rowref():
    """THE invariant (spec, judge criterion 1): nos_accounting.check_entries
    over ALL postings is [] (every entry balances), AND no journal entry's
    postings touch two different clients' analytical accounts — resolved via
    account.party (a rowRef equality), never a code-string prefix. A shared
    account (party is empty/absent) is neutral and never a violation."""
    na = _nos_accounting()
    seed = _seed()

    errors = na.check_entries(seed["posting"])
    assert errors == [], f"an entry does not balance: {errors}"

    account_party = {a["slug"]: a.get("party") for a in seed["account"]}
    invoice_by_slug = {i["slug"]: i for i in seed["invoice"]}
    entry_owner = {
        je["slug"]: invoice_by_slug[je["source"]]["book_owner"]
        for je in seed["journal-entry"]
    }

    violations = []
    for p in seed["posting"]:
        owner = entry_owner.get(p["entry"])
        touched_party = account_party.get(p["account"])
        if touched_party and touched_party != owner:
            violations.append(
                f"posting {p['slug']}: entry {p['entry']} belongs to {owner!r} but "
                f"posts to account {p['account']!r} whose party is {touched_party!r}"
            )
    assert violations == [], (
        "isolation invariant broken — a posting bridges two clients' "
        "analytical accounts:\n  " + "\n  ".join(violations)
    )

    # The cosmetic trap named in the epic's judge question: a code-string
    # 311-<client> prefix must agree with the rowRef, but the rowRef is the
    # thing actually asserted above — this just proves both fixture accounts
    # (dash-analytical, not the dotted 311.001 convention) carry a real party.
    analytical = [a for a in seed["account"] if a.get("parent") in ("acc-311", "acc-321")]
    assert len(analytical) == 2 * len(CLIENTS), (
        f"expected {2 * len(CLIENTS)} analytical accounts (311+321 per client), "
        f"found {len(analytical)}"
    )
    for a in analytical:
        assert a.get("party") in CLIENTS, f"analytical account {a['slug']} has no party rowRef"


def test_expected_yaml_matches_the_isolation_answer_key():
    exp = _expected()
    seed = _seed()
    account_party = {a["slug"]: a.get("party") for a in seed["account"]}
    for client, allowed in exp["isolation"].items():
        assert client in CLIENTS
        for slug in allowed:
            assert slug in account_party, f"expected.yml isolation lists unknown account {slug!r}"
            p = account_party[slug]
            assert p is None or p == client, (
                f"expected.yml claims {client} may touch {slug!r}, whose real "
                f"party is {p!r} — the answer key disagrees with the seed"
            )
    for client, book in exp["books"].items():
        assert book["balanced"] is True
        assert len(book["entries"]) >= 2


# ── Dual intake: ISDOC + image, one multi-rate invoice, one planted mismatch ─

def test_every_client_has_dual_intake_documents():
    isdoc_files = sorted(p.stem.replace(".isdoc", "") for p in DOCS_DIR.glob("*.isdoc.xml"))
    image_files = sorted(p.stem.replace(".image", "") for p in DOCS_DIR.glob("*.image.txt"))
    assert isdoc_files, "no ISDOC documents in state/fixtures/consulting-firm/"
    assert isdoc_files == image_files, (
        f"ISDOC docs {isdoc_files} != image docs {image_files} — every "
        "invoice needs BOTH intake channels (dual-intake unit)"
    )
    prefixes = {name.split("-")[0] for name in isdoc_files}
    short = {"alfa", "beta", "gama"}
    assert short <= prefixes, f"expected client prefixes {short}, found {prefixes}"


def test_one_multi_rate_vat_invoice_is_planted():
    hits = [p for p in DOCS_DIR.glob("*.isdoc.xml") if p.read_text().count("<TaxSubTotal>") >= 2]
    assert len(hits) >= 1, "no multi-rate-VAT (>=2 TaxSubTotal) ISDOC document planted"


def test_one_image_isdoc_mismatch_is_planted():
    exp = _expected()
    mismatches = [k for k, v in exp["crosscheck"].items() if v == "mismatch"]
    assert len(mismatches) >= 1, "no planted crosscheck mismatch in expected.yml"
    agrees = [k for k, v in exp["crosscheck"].items() if v == "agree"]
    assert agrees, "every document mismatches — no positive control that agreement is possible"


# ── Synthetic-by-measurement (same rule as every prior fixture) ─────────────

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
        if r["value"] in VISION_PDF_TAX:
            continue
        if not re.fullmatch(r"(CZ)?000001\d\d", r["value"]):
            problems.append(f"tax {r['slug']}: {r['value']!r} outside the synthetic range")
    assert not problems, (
        "a seeded value stopped looking synthetic:\n  " + "\n  ".join(problems)
    )
    assert any(r["party_kind"] == "person" for r in seed["party"]), (
        "no OSVC/person client seeded — the 2 s.r.o. + 1 OSVC shape is unexercised"
    )
    assert any(r["kind"] == "email" for r in seed["party-contact"])


def test_ico_range_is_130_to_139_and_documented():
    """The def's assigned range is 130-149; this fixture uses 130-139, so a
    future sibling still has 140-149 free. Cross-check against every OTHER
    fixture's seeded tax ids to prove no collision (org_slug() is
    deterministic on the ICO — a collision silently aliases a party)."""
    seed = _seed()
    used = set()
    for r in seed["party-tax-identity"]:
        m = re.search(r"^000001(\d\d)$", r["value"])
        if m:
            used.add(int(m.group(1)))
    assert used and max(used) <= 39 and min(used) >= 30, f"ICO range drifted: {sorted(used)}"

    other_seeds = [
        REPO / "state/fixtures/label-printer.seed.yml",
        REPO / "state/fixtures/kolben-it.seed.yml",
        REPO / "state/fixtures/accounting.seed.yml",
    ]
    collisions = []
    for path in other_seeds:
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text())
        for row in data.get("party-tax-identity", []):
            m = re.search(r"000001(\d\d)$", row["value"])
            if m and int(m.group(1)) in used:
                collisions.append(f"{path.name}: {row['value']!r} collides with the consulting-firm range")
    assert not collisions, "ICO range collides with an existing fixture:\n  " + "\n  ".join(collisions)


def test_hejsek_is_the_vision_pdf_client():
    """Printed IČO 87654321 is checksum-invalid; live absorb matches legal_name."""
    seed = _seed()
    hejsek = next(p for p in seed["party"] if p["slug"] == "synthetic-client-hejsek")
    assert hejsek["legal_name"] == "Bořivoj Hejsek"
    assert hejsek["party_kind"] == "org"
    assert hejsek.get("training_opt_in") is False
    icos = {r["party"]: r["value"] for r in seed["party-tax-identity"] if r["scheme"] == "ICO"}
    assert icos["synthetic-client-hejsek"] == "87654321"
    assert icos["synthetic-hejsek-apple"] == "28897501"
    assert icos["synthetic-hejsek-firma"] == "45126489"
    spec = importlib.util.spec_from_file_location(
        "nos_digest", REPO / "files/anatomy/module_utils/nos_digest.py")
    nd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nd)
    assert nd.normalize_ico("87654321")["checksum_ok"] is False
    assert nd.normalize_ico("28897501")["checksum_ok"] is True
    index = {
        "by_key": {("ICO", v): p for p, v in icos.items()},
        "by_name": {
            nd.normalize_org_name("Bořivoj Hejsek"): ["synthetic-client-hejsek"],
            nd.normalize_org_name("Apple Czech s.r.o."): ["synthetic-hejsek-apple"],
            nd.normalize_org_name("Firma s.r.o."): ["synthetic-hejsek-firma"],
        },
    }
    seller = nd.resolve_party(
        {"kind": "org", "ico": "87654321", "legal_name": "Bořivoj Hejsek"},
        index, fixture_mode=False)
    assert seller["status"] == "resolved" and seller["matched_by"] == "ico"
    buyer = nd.resolve_party(
        {"kind": "org", "ico": "28897501", "legal_name": "Apple Czech s.r.o."},
        index, fixture_mode=False)
    assert buyer["status"] == "resolved" and buyer["matched_by"] == "ico"
