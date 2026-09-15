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
    assert [s["id"] for s in m["steps"]] == [sid for sid, _rel in mod.STEPS]
    for _sid, rel in mod.STEPS:
        assert (REPO / rel).is_file(), rel


def test_apply_flags_are_refused():
    mod = _mod()
    assert mod.main(["--apply"]) == 2
    assert mod.main(["--push-github"]) == 2


def test_readers_spawn_but_their_findings_are_not_this_exit(monkeypatch):
    """estate-status exits 1 on drift. That is a finding, not a runner crash."""
    mod = _mod()
    calls = []

    def fake_run(argv, cwd=None):
        calls.append(argv)
        return types.SimpleNamespace(returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert mod.main([]) == 0
    assert len(calls) == 3
    for argv in calls:
        joined = " ".join(argv)
        assert "--apply" not in joined and "--push-github" not in joined
