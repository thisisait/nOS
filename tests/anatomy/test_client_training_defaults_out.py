"""v1 contract: client-data training is optional, default OUT, per book_owner.

The consulting firm is processor for client books. A growable agency must not
mix Alfa invoices into Beta's weights. The PIPELINE stays off until offboarding
can honour Art-17 against a model; Art-7 capture is still unwired.

RETRO-RED: a tree without party.training_opt_in, or a book_owner seeded true,
or a Pulse job that trains on invoices, fails before any trainer exists.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PARTY_DEF = REPO / "state/keap-tables/party.table.yml"
CONSULTING = REPO / "state/fixtures/consulting-firm.seed.yml"
CONSENT = REPO / "state/gdpr-consent-map.yml"
PULSE_SOURCES = ("files/anatomy/plugins/*/plugin.yml", "files/anatomy/agents/*/agent.yml")

TRAIN = re.compile(r"\btrain(?:ing|er|s|ed)?\b", re.I)
INVOICE = re.compile(r"\binvoice", re.I)
HOSTED = re.compile(r"\b(?:lora|fakturoid|rossum|typesafe)\b", re.I)


def _party_cols() -> dict:
    cols = yaml.safe_load(PARTY_DEF.read_text())["schema"]["columns"]
    return {c["key"]: c for c in cols}


def _consulting() -> dict:
    return yaml.safe_load(CONSULTING.read_text())


def _pulse_jobs() -> list[tuple[str, str, dict]]:
    out = []
    for pattern in PULSE_SOURCES:
        for path in sorted(REPO.glob(pattern)):
            doc = yaml.safe_load(path.read_text()) or {}
            if not isinstance(doc, dict):
                continue
            jobs = (doc.get("pulse") or {}).get("jobs") or []
            owner = str(doc.get("name") or doc.get("agent_id") or path.stem)
            for job in jobs:
                if isinstance(job, dict) and job.get("name"):
                    out.append((str(path.relative_to(REPO)), f"{owner}:{job['name']}", job))
    return out


def test_training_opt_in_is_an_optional_boolean_on_party():
    col = _party_cols()["training_opt_in"]
    assert col["kind"] == "boolean"
    assert not col.get("required"), (
        "training_opt_in must stay optional — omitted = OUT; a required column "
        "would force every existing party seed to declare a training stance"
    )


def test_book_owners_seed_explicit_false():
    seed = _consulting()
    owners = {inv["book_owner"] for inv in seed["invoice"]}
    assert owners, "consulting-firm fixture has no book_owner invoices"
    by_slug = {p["slug"]: p for p in seed["party"]}
    for owner in sorted(owners):
        row = by_slug[owner]
        assert row.get("training_opt_in") is False, (
            f"{owner} is a book_owner but training_opt_in={row.get('training_opt_in')!r}; "
            "v1 default is OUT (YAML boolean false)"
        )


def test_no_committed_party_opts_in():
    opted = []
    for path in sorted((REPO / "state/fixtures").glob("*.seed.yml")):
        for row in (yaml.safe_load(path.read_text()) or {}).get("party") or []:
            if row.get("training_opt_in") is True:
                opted.append(f"{path.name}:{row.get('slug')}")
    assert not opted, f"committed training_opt_in:true — pipeline must stay off: {opted}"


def test_art7_capture_is_still_unwired():
    rows = yaml.safe_load(CONSENT.read_text())["activities"]
    wired = [r["id"] for r in rows if r.get("capture_wired") is True]
    assert not wired, (
        f"gdpr-consent-map.yml flipped capture_wired true for {wired} — "
        "do not claim Art-7 consent is live"
    )


def test_no_pulse_job_trains_on_client_invoices():
    jobs = _pulse_jobs()
    assert len(jobs) >= 25, f"pulse walk found only {len(jobs)} jobs — coverage collapsed"
    hits = []
    for src, jid, job in jobs:
        blob = yaml.dump(job, default_flow_style=False)
        if TRAIN.search(blob) and INVOICE.search(blob):
            hits.append(jid)
        elif HOSTED.search(blob) and INVOICE.search(blob):
            hits.append(jid)
    assert not hits, f"Pulse job trains (or hosts a trainer) on invoices: {hits}"
