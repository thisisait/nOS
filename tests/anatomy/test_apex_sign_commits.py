"""apex-sign --confirm commits the ruling it signed, and nothing else.

2026-10-16 and again 2026-10-17: the operator signed and pushed, the digest was written but not
committed, and origin/dev carried a ruling its signature did not match (CI red on
test_apex_ruling_is_signed). Printing the commit was not enough; the tool makes it.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _git(root, *a):
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, check=True).stdout


def test_confirm_commits_only_the_ruling(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("apex_sign", REPO / "tools/apex-sign.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    ruling = tmp_path / "files/anatomy/apex/ruling.yml"
    ruling.parent.mkdir(parents=True)
    ruling.write_text("nodes: {}\nsigned_digest: 0000\n", encoding="utf-8")
    other = tmp_path / "other.txt"
    other.write_text("x\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    other.write_text("staged, not the operator's signature\n")
    _git(tmp_path, "add", "other.txt")
    monkeypatch.setattr(mod, "REPO", tmp_path)
    monkeypatch.setattr(mod, "RULING", ruling)
    monkeypatch.setattr(sys, "argv", ["apex-sign.py", "--confirm"])
    assert mod.main() == 0
    assert _git(tmp_path, "show", "--name-only", "--format=%s", "HEAD").split() == \
        ["chore(apex):", "re-sign", "files/anatomy/apex/ruling.yml"]
    assert "other.txt" in _git(tmp_path, "diff", "--cached", "--name-only"), "an unrelated staged file stays staged"
    assert _git(tmp_path, "status", "--porcelain", "--", "files/anatomy/apex/ruling.yml") == ""
