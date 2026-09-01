"""Anatomy CI gate — a test must not write the estate's live metrics.

MEASURED 2026-09-01. `TEXTFILE_DIR` in hooks/playbook-end.d/20-cve-drift-check.sh
defaults to `$HOME/.nos/metrics/textfile` — ONE global path shared by every
checkout on the host. Three checkouts held three different remediation queues
(1 CRITICAL here, 2 in the other two), and the live
`nos_security_pending_total` flipped between them within seconds while sibling
worktrees ran their suites. The firing CVE alerts described whichever ran last.

Under pytest the hook now refuses the write unless TEXTFILE_DIR was set
explicitly — a test that wants it names its own directory.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks/playbook-end.d/20-cve-drift-check.sh"


def test_the_hook_refuses_the_global_textfile_under_pytest():
    src = HOOK.read_text(encoding="utf-8")
    assert "PYTEST_CURRENT_TEST" in src, (
        "the hook no longer notices it is running under pytest, so any suite on "
        "this host overwrites the estate's live security metric with its own "
        "checkout's queue")
    assert "TEXTFILE_DIR_EXPLICIT" in src, (
        "the pytest guard has no opt-in, so a test that legitimately wants the "
        "write (with its own TEXTFILE_DIR) cannot have it")


def test_the_guard_actually_holds(tmp_path):
    """Executes the hook rather than reading it: with PYTEST_CURRENT_TEST set and
    no explicit dir, the named file must not appear."""
    home = tmp_path / "home"
    (home / ".nos" / "metrics" / "textfile").mkdir(parents=True)
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
           "HOME": str(home), "NOS_REPO": str(REPO),
           "PYTEST_CURRENT_TEST": "gate::test"}
    subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=env)
    written = list((home / ".nos" / "metrics" / "textfile").iterdir())
    assert not written, (
        f"the hook wrote {[p.name for p in written]} under pytest with no "
        "explicit TEXTFILE_DIR")

    env["TEXTFILE_DIR"] = str(tmp_path / "own")
    (tmp_path / "own").mkdir()
    subprocess.run(["bash", str(HOOK)], capture_output=True, text=True, env=env)
    assert (tmp_path / "own" / "nos_security_drift.prom").is_file(), (
        "an explicit TEXTFILE_DIR was ignored; the opt-in does not work and "
        "every drift test now measures nothing")
