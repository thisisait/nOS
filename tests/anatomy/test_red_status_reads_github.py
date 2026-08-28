"""CI and Dependabot are a STATE red-status can be asked for, not just events.

CI on `dev` was red for two days and the Linux wet-test had been failing at
preflight for four weeks; both surfaced only when a human opened a PR. The two
properties that make the reader honest, pinned here against stubbed `gh` output
rather than the network: a branch's CI state is the NEWEST run per workflow (an
older failure under a newer success is history), and an unreachable `gh` is
UNKNOWN — reported as an unread source, never as green.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _mod():
    spec = importlib.util.spec_from_file_location("_red", REPO / "tools" / "red-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUNS = [
    {"name": "CI", "conclusion": "success", "status": "completed",
     "headSha": "aaaaaaaa", "createdAt": "2026-08-28T10:00:00Z"},
    {"name": "CI", "conclusion": "failure", "status": "completed",
     "headSha": "bbbbbbbb", "createdAt": "2026-08-27T10:00:00Z"},
    {"name": "Nightly", "conclusion": "failure", "status": "completed",
     "headSha": "cccccccc", "createdAt": "2026-08-28T09:00:00Z"},
]


def test_newest_run_per_workflow_is_the_branch_state(monkeypatch) -> None:
    mod = _mod()
    monkeypatch.setattr(mod, "_gh", lambda *a: RUNS)
    failures = mod.ci_runs()["dev"]
    assert [f["workflow"] for f in failures] == ["Nightly"], (
        "the superseded CI failure must not read as red; the newest Nightly must"
    )


def test_unreachable_gh_is_unknown_not_green(monkeypatch) -> None:
    mod = _mod()
    monkeypatch.setattr(mod, "_gh", lambda *a: None)
    assert mod.ci_runs() is None and mod.dependabot() is None
    report = {"sources_missing": ["gh run list"]}
    assert any("UNKNOWN" in line for line in mod.reds(report))


def test_open_alerts_are_counted_by_severity(monkeypatch) -> None:
    mod = _mod()
    monkeypatch.setattr(mod, "_gh", lambda *a: [
        {"sev": "high", "pkg": "js-yaml"},
        {"sev": "low", "pkg": "cookie"},
    ])
    dep = mod.dependabot()
    assert dep["counts"] == {"high": 1, "low": 1}
    assert dep["serious_packages"] == ["js-yaml"]
    assert any("Dependabot" in line for line in mod.reds({"dependabot": dep}))
