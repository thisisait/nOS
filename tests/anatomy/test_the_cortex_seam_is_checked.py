"""The validator and the executor must agree on the opcode registry.

The cortex organ runs in two runtimes: `files/anatomy/cortex/` (Node, :8098)
tokenises, parses and analyses a chain for `POST /agent/v1/validate`, and
`files/anatomy/wing/app/Cortex/` (PHP, inside Wing) executes it. Both publish
the registry they were built against — `opcodeRegistryHash` on one side,
`registry_hash` on the other — and on 2026-08-31 both said
`cx1:1fe4e8517d0b2b7f`.

NOTHING COMPARED THEM. That is the failure this file exists for, and it is the
worst-shaped one available: if the halves drift, every chain still VALIDATES
and some then fail at execution. The symptom appears at the model — "the LLM
emitted a bad chain" — and the cause is that the two halves of one organ were
built against different registries. A defect that blames the wrong actor
survives much longer than one that blames itself.

WHY A READER AND NOT A GATE ON THE SOURCE. The two registries are built at
different times, in different languages, and deployed by different roles; the
question is only answerable against what is RUNNING. So `tools/cortex-status.py`
asks both live surfaces, and this pins the reader's verdict logic — which is
where a comparison can quietly become a tick that always shows green.

Retro-verified 2026-08-31 by handing the reader two different hashes.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
READER = REPO / "tools/cortex-status.py"
PANE = REPO / "tools/cc/panes/cortex.py"


def _mod(path: pathlib.Path, name: str):
    sys.path.insert(0, str(REPO / "tools"))
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _report(monkeypatch, vhash, ehash, **over):
    m = _mod(READER, "cortex_status")
    monkeypatch.setattr(m, "validate_half", lambda: dict(
        {"reachable": True, "version": "0.1.0", "surface": "enabled",
         "registry_hash": vhash, "ontology": "o", "spine_in_sync": True},
        **over.get("v", {})))
    monkeypatch.setattr(m, "execute_half", lambda: dict(
        {"reachable": True, "handlers": ["get"], "registry_hash": ehash,
         "covers_keap": True, "uncovered": [], "runtime": "wing (php)"},
        **over.get("e", {})))
    monkeypatch.setattr(m, "traffic", lambda: {"readable": True, "stages_7d": 0,
                                               "chains_7d": 0, "by_length": {}})
    return m.report()


def test_matching_hashes_agree(monkeypatch) -> None:
    seam = _report(monkeypatch, "cx1:same", "cx1:same")["seam"]
    assert seam["agree"] is True


def test_divergent_hashes_are_reported_as_broken(monkeypatch) -> None:
    """The measured danger: chains validate and then fail to execute."""
    seam = _report(monkeypatch, "cx1:aaa", "cx1:bbb")["seam"]
    assert seam["agree"] is False, (
        "the reader calls two DIFFERENT registry hashes agreement; a chain "
        "would validate and then fail to execute, and the blame would land on "
        "the model that emitted it")
    assert "DISAGREE" in seam["detail"]


def test_an_absent_hash_is_never_agreement(monkeypatch) -> None:
    """`None == None` is True in Python and must not read as a matching seam —
    two halves that publish nothing are not two halves that agree."""
    seam = _report(monkeypatch, None, None)["seam"]
    assert seam["agree"] is not True, (
        "two empty hashes compared equal and the seam reported agreement")


def test_an_unreachable_half_is_unknown_not_agreement(monkeypatch) -> None:
    m = _mod(READER, "cortex_status")
    monkeypatch.setattr(m, "validate_half",
                        lambda: {"reachable": False, "detail": "refused"})
    monkeypatch.setattr(m, "execute_half", lambda: {
        "reachable": True, "handlers": [], "registry_hash": "cx1:x",
        "covers_keap": True, "uncovered": [], "runtime": "wing (php)"})
    monkeypatch.setattr(m, "traffic", lambda: {"readable": False, "detail": "x"})
    r = m.report()
    assert r["seam"]["agree"] is None, "a half that did not answer read as a verdict"


def test_the_pane_ranks_a_broken_seam_first() -> None:
    """A pane is a glance. The row that would ruin the morning goes on top."""
    pane = _mod(PANE, "cortex_pane")
    rows = pane.build_rows({
        "seam": {"agree": False, "validate": "a", "execute": "b", "detail": "THE HALVES DISAGREE"},
        "validate": {"reachable": True, "version": "0.1.0", "surface": "enabled",
                     "spine_in_sync": True},
        "execute": {"reachable": True, "runtime": "wing (php)", "handlers": ["get"],
                    "covers_keap": True, "uncovered": []},
        "traffic": {"readable": True, "stages_7d": 1, "chains_7d": 1, "by_length": {"1": 1}},
    })
    assert rows[0]["part"] == "seam" and rows[0]["state"] == "BROKEN", (
        f"a broken seam is not the first row: {rows[0]}")
