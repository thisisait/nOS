"""nos-smoke in a git worktree reads the operator's config.yml from the main
checkout. MEASURED 2026-10-18: config.yml is gitignored, so a worktree has none,
tenant_domain fell back to dev.local and nos-secret --accounts printed
pazny@dev.local for an estate served elsewhere. The main checkout is the parent
of `git rev-parse --git-common-dir`; with no file there, the checkout's own."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _smoke():
    spec = importlib.util.spec_from_file_location("_smoke_worktree", REPO / "tools" / "nos-smoke.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_worktree_resolves_config_from_the_main_checkout(tmp_path, monkeypatch):
    main, wt = tmp_path / "main", tmp_path / "wt"
    git = lambda *a, cwd=main: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a],  # noqa: E731
                                              cwd=cwd, check=True, capture_output=True)
    main.mkdir()
    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "root")
    git("worktree", "add", "-q", str(wt))
    (main / "config.yml").write_text("tenant_domain: example.test\n")
    monkeypatch.setenv("HOME", str(tmp_path))          # no ~/.nos/state.yml leaks in
    smoke = _smoke()
    monkeypatch.setattr(smoke, "REPO", wt)
    assert smoke.load_vars()["tenant_domain"] == "example.test", "a worktree still renders the defaults' TLD"
    (main / "config.yml").unlink()
    (wt / "config.yml").write_text("tenant_domain: own.test\n")
    assert smoke.load_vars()["tenant_domain"] == "own.test", "no main-checkout file: the checkout's own must win"
