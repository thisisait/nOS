"""D4 — per-client Art-30 mapper: correctness + the leak gate.

`nos_gdpr.controller_records()` is RUNTIME-only: it turns live party rows
(role='client'/'own_firm') into Art-30 records, but must NEVER reach
`all_records()` / the committed `state/dpa-register.md` — that would leak a
client's real identity into public git history. This is the only thing
stopping a future "helpful" merge from doing exactly that.

RETRO-RED evidence (manually verified while authoring this gate, not
re-run by CI): before this commit `nos_gdpr.controller_records` did not
exist -> `AttributeError`. Temporarily adding
`recs += controller_records(_sample_parties())` inside `all_records()`
makes `test_leak_gate_source_never_wires_controller_records_into_all_records`
fail (source scan) AND makes
`test_leak_gate_dpa_register_never_contains_a_client_identity` fail (the
synthetic client's legal_name leaks into the rendered register) -- both
reverted before committing.
"""
from __future__ import annotations

import inspect
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files/anatomy"))
from module_utils import nos_gdpr  # noqa: E402

sys.path.insert(0, str(REPO / "tools"))


def _sample_parties() -> list[dict]:
    return [
        {"slug": "synthetic-consulting-firm", "legal_name": "Synthetic Consulting s.r.o.", "role": "own_firm"},
        {"slug": "synthetic-client-alfa", "legal_name": "Alfa Rizeni s.r.o. (synthetic)", "role": "client"},
        {"slug": "synthetic-alfa-customer", "legal_name": "Alfa Odberatel a.s. (synthetic)", "role": "counterparty"},
        {"slug": "synthetic-nobody", "legal_name": "No Role Party"},
    ]


def test_controller_records_stamps_processor_for_client_controller_for_own_firm():
    recs = nos_gdpr.controller_records(_sample_parties())
    by_slug = {r["id"]: r for r in recs}

    assert "party_synthetic-client-alfa" in by_slug
    assert by_slug["party_synthetic-client-alfa"]["art30_role"] == "processor"

    assert "party_synthetic-consulting-firm" in by_slug
    assert by_slug["party_synthetic-consulting-firm"]["art30_role"] == "controller"

    # counterparty / no-role rows are not GDPR-mapped at all.
    assert "party_synthetic-alfa-customer" not in by_slug
    assert "party_synthetic-nobody" not in by_slug
    assert len(recs) == 2


def test_controller_records_is_pure_and_offline():
    # no filesystem / network access — pure over injected dicts.
    assert nos_gdpr.controller_records([]) == []
    assert nos_gdpr.controller_records([{"slug": "x", "role": "bogus"}]) == []


def test_leak_gate_source_never_wires_controller_records_into_all_records():
    """Static leak gate: all_records()'s body must never call controller_records().

    FAILS (by construction) the moment someone adds
    `recs += controller_records(...)` inside all_records() — proven manually
    while authoring this gate (see module docstring); not left wired in.
    """
    src = inspect.getsource(nos_gdpr.all_records)
    assert "controller_records" not in src, (
        "all_records() must never call controller_records() — that would "
        "leak client identities into the committed DPA register."
    )


def test_leak_gate_dpa_register_never_contains_a_client_identity():
    """Runtime leak gate: render the register the way CI does and check the
    sample fixture client's synthetic name/ICO never appear in it."""
    spec_path = REPO / "tools" / "gdpr-dpa-register.py"
    import importlib.util
    spec = importlib.util.spec_from_file_location("gdpr_dpa_register", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    rendered = mod.render(nos_gdpr.all_records(REPO))

    for leak in ("Alfa Rizeni", "00000131", "Beta Sluzby", "00000132"):
        assert leak not in rendered, f"client identity leaked into rendered DPA register: {leak!r}"

    # and the party-role mapper's own output never sneaks in via all_records()
    for r in nos_gdpr.controller_records(_sample_parties()):
        assert r["id"] not in {x["id"] for x in nos_gdpr.all_records(REPO)}
