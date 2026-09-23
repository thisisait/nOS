"""The pipeline-exercise loop's decisions, without a VLM.

The loop's VALUE is in what it asserts after the model — identity, uniqueness,
a balanced entry — and in never letting a model judge its own extraction. Those
are the parts that can rot silently, so they are the parts pinned here. The
cycle itself needs a live estate and ~2 minutes of VLM per document; it is
exercised by running it, not by a unit test pretending to.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "files" / "anatomy" / "module_utils"))
pytest.importorskip("PIL.Image", reason="Pillow not installed")

_spec = importlib.util.spec_from_file_location(
    "pipeline_exercise", REPO / "tools" / "loops" / "pipeline-exercise.py")
LOOP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(LOOP)
import nos_digest  # noqa: E402


def test_there_is_something_to_exercise():
    """Positive control — no fixtures would make every assertion vacuous."""
    assert LOOP.DOCS, "no *.image.txt fixtures"
    assert "clean" in LOOP.DEGRADATIONS and "crumple" in LOOP.DEGRADATIONS
    assert "combo" not in LOOP.DEGRADATIONS, (
        "combo expands to a random pair, so a coverage CELL for it would count "
        "visits to something different every time")


def test_the_matrix_planner_goes_where_it_has_not_been():
    cov = {f"{d}|{g}": 5 for d in LOOP.DOCS for g in LOOP.DEGRADATIONS}
    cov[f"{LOOP.DOCS[1]}|stains"] = 0
    assert LOOP.thinnest_cell(cov) == (LOOP.DOCS[1], "stains")


def test_the_matrix_planner_is_reproducible():
    """Same coverage in, same cell out — a run that cannot be repeated cannot
    be debugged from its own record."""
    cov = {}
    assert LOOP.thinnest_cell(cov) == LOOP.thinnest_cell(dict(cov))


def test_a_forced_cell_skips_the_planner():
    plan = LOOP.plan_cycle("matrix", {}, 7, [], "x", ("beta-002", "crumple"))
    assert (plan["doc"], plan["degrade"], plan["seed"]) == ("beta-002", "crumple", 7)


def test_the_agent_planner_refuses_an_unusable_answer(monkeypatch):
    """It must not fall back to the matrix: coverage would then record a cell
    the model never chose, and the report would describe a run that did not
    happen."""
    class Out:
        stdout = '{"result": {"doc": "no-such-doc", "degrade": "crumple"}}'
        stderr = ""
    monkeypatch.setattr(LOOP, "_run", lambda *a, **k: Out())
    with pytest.raises(SystemExit) as e:
        LOOP.plan_cycle("agent", {}, 1, [], "pipeline-clerk", (None, None))
    assert "did not answer usably" in str(e.value)


def test_the_agent_planner_accepts_a_good_answer(monkeypatch):
    class Out:
        stdout = ('noise before {"result": {"doc": "%s", "degrade": "stains", '
                  '"seed": 3, "reason": "thin"}} after' % LOOP.DOCS[0])
        stderr = ""
    monkeypatch.setattr(LOOP, "_run", lambda *a, **k: Out())
    plan = LOOP.plan_cycle("agent", {}, 1, [], "pipeline-clerk", (None, None))
    assert plan == {"doc": LOOP.DOCS[0], "degrade": "stains", "seed": 3, "reason": "thin"}


def test_the_oracle_decides_the_verdict_not_a_model():
    """A mismatching extraction must be rejected even when the sidecar claims
    to be verified — the model's own confidence is not evidence."""
    truth = LOOP.truth_for(LOOP.DOCS[0])
    hits = LOOP.BENCH.score_extraction({"id": "WRONG"}, truth)
    assert not all(hits.values())
    # ...and the truth agrees with itself, so the oracle is not simply strict.
    same = {"id": truth["id"], "issue": truth["issue"], "due": truth["due"],
            "currency": truth["currency"], "payable": truth["payable"],
            "net": sum(r["base"] for r in truth["rates"]),
            "vat": sum(r["vat"] for r in truth["rates"]),
            "seller": {"ico": truth["seller_ico"]}, "buyer": {"ico": truth["buyer_ico"]},
            "vat_breakdown": truth["rates"]}
    assert all(LOOP.BENCH.score_extraction(same, truth).values())


def test_a_booked_document_must_carry_the_derived_identity(monkeypatch):
    truth = LOOP.truth_for(LOOP.DOCS[0])
    doc_no = truth["id"]
    rows = {
        "invoice": [{"slug": "hand-picked-id", "document_number": doc_no,
                     "seller": "s", "book_owner": "b"}],
        "posting": [],
    }
    monkeypatch.setattr(LOOP.digest_absorb, "read_rows", lambda t: rows.get(t, []))
    out = LOOP.assert_books(truth, "b", expect_booked=True)
    assert out["ok"] is False and out["identity_ok"] is False


def test_one_document_twice_is_a_finding(monkeypatch):
    truth = LOOP.truth_for(LOOP.DOCS[0])
    doc_no = truth["id"]
    good = nos_digest.invoice_slug("b", "s", doc_no)
    rows = {"invoice": [{"slug": good, "document_number": doc_no, "seller": "s",
                         "book_owner": "b"},
                        {"slug": "inv-legacy", "document_number": doc_no,
                         "seller": "s", "book_owner": "b"}],
            "posting": []}
    monkeypatch.setattr(LOOP.digest_absorb, "read_rows", lambda t: rows.get(t, []))
    out = LOOP.assert_books(truth, "b", expect_booked=True)
    assert out["ok"] is False and "2 rows" in out["detail"]


def test_a_rejected_document_must_not_reach_the_books(monkeypatch):
    truth = LOOP.truth_for(LOOP.DOCS[0])
    rows = {"invoice": [{"slug": "x", "document_number": truth["id"]}], "posting": []}
    monkeypatch.setattr(LOOP.digest_absorb, "read_rows", lambda t: rows.get(t, []))
    out = LOOP.assert_books(truth, "b", expect_booked=False)
    assert out["ok"] is False and "rejected" in out["detail"]


def test_a_clean_book_holds(monkeypatch):
    """A detector that cannot report green is no detector."""
    truth = LOOP.truth_for(LOOP.DOCS[0])
    slug = nos_digest.invoice_slug("b", "s", truth["id"])
    rows = {"invoice": [{"slug": slug, "document_number": truth["id"], "seller": "s",
                         "book_owner": "b"}],
            "posting": [{"slug": "p1", "entry": f"je-{slug}", "direction": "debit",
                         "amount": 121},
                        {"slug": "p2", "entry": f"je-{slug}", "direction": "credit",
                         "amount": 100},
                        {"slug": "p3", "entry": f"je-{slug}", "direction": "credit",
                         "amount": 21}]}
    monkeypatch.setattr(LOOP.digest_absorb, "read_rows", lambda t: rows.get(t, []))
    out = LOOP.assert_books(truth, "b", expect_booked=True)
    assert out["ok"] is True and out["balanced"] is True
