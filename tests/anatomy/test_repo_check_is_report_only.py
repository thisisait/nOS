"""repo-check is report-only: it runs the three readers and never applies.

The proving instance of loop-generator (roadmap loop-repo-check). The loop
manifest names the steps; this runner is the pulse argv0. A flag that would
move a forge is refused even if Pulse's arg-regex let it through.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import types

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def _mod():
    spec = importlib.util.spec_from_file_location(
        "repo_check", REPO / "tools/loops/repo-check.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_runner_steps_match_the_manifest():
    m = yaml.safe_load((REPO / "files/anatomy/loops/repo-check.loop.yml").read_text(encoding="utf-8"))
    mod = _mod()
    assert [s["id"] for s in m["steps"]] == [sid for sid, _rel, _gate in mod.STEPS]
    for _sid, rel, _gate in mod.STEPS:
        assert (REPO / rel).is_file(), rel


def test_the_manifest_declares_what_a_gate_returns():
    """The runner can return 3; Pulse must know that means a FINDING.

    Without `findings_exit_codes: [3]` on the manifest, a wording regression is
    recorded as a crashed job rather than a result — and the difference is
    whether anyone reads it.
    """
    m = yaml.safe_load((REPO / "files/anatomy/loops/repo-check.loop.yml").read_text(encoding="utf-8"))
    mod = _mod()
    assert mod.FINDINGS == 3
    assert 3 in ((m.get("pulse") or {}).get("findings_exit_codes") or [])


def test_apply_flags_are_refused():
    mod = _mod()
    assert mod.main(["--apply"]) == 2
    assert mod.main(["--push-github"]) == 2


def _spawn_with(monkeypatch, code_for):
    """Run main() with every step's exit code chosen by `code_for(rel)`."""
    mod = _mod()
    calls = []

    def fake_run(argv, cwd=None):
        calls.append(argv)
        return types.SimpleNamespace(returncode=code_for(argv[-1]))

    monkeypatch.setattr(subprocess, "run", fake_run)
    return mod, mod.main([]), calls


def test_readers_spawn_but_their_findings_are_not_this_exit(monkeypatch):
    """estate-status exits 1 on drift. That is a finding, not a runner crash.

    Still true, and still the reason the runner does not launder codes — but it
    is now true of READERS only, so the fake makes the gate succeed.
    """
    mod = _mod()
    gates = {rel for _sid, rel, is_gate in mod.STEPS if is_gate}
    _m, rc, calls = _spawn_with(monkeypatch, lambda p: 0 if any(p.endswith(g) for g in gates) else 1)
    assert rc == 0, "a reader's non-zero became the loop's exit"
    assert len(calls) == len(mod.STEPS)
    for argv in calls:
        joined = " ".join(argv)
        assert "--apply" not in joined and "--push-github" not in joined


def test_a_failing_gate_is_not_swallowed(monkeypatch):
    """The other half, proven live 2026-09-25: break wording.yml and the bench
    returns 1 while the loop returns 3. A gate exits non-zero to MEAN something;
    treating it like a reader would bury a wording regression in a log."""
    mod = _mod()
    gates = {rel for _sid, rel, is_gate in mod.STEPS if is_gate}
    assert gates, "no gate step declared — the distinction has been lost"
    _m, rc, _calls = _spawn_with(monkeypatch, lambda p: 1 if any(p.endswith(g) for g in gates) else 0)
    assert rc == mod.FINDINGS, f"a failing gate returned {rc}, not {mod.FINDINGS}"
