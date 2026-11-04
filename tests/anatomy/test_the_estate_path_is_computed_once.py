"""The estate path is computed once per language: NOS_ESTATE_DIR, else ~/.nos/estate.

WHY (operator ruling 2026-11-04, row estate-dir-one-source): the default was
spelled at nine sites (five in one preflight file, three readers, the CLI, two
spore scripts), and germinate.sh ignored NOS_ESTATE_DIR. Two names stay
(NOS_ESTATE_DIR in shell, nos_estate_dir in Ansible); the fallback lives only in
the declaring sites below. Comments are prose and not scanned.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPELLING = re.compile(r"""\.nos['"]?\s*[/,]\s*['"]?estate\b""")
COMMENT = re.compile(r"^\s*(#|//|\*|/\*)")
DECLARING = {
    "default.config.yml": "nos_estate_dir, for Ansible",
    "tools/nos_identity.py": "estate_dir(), for every Python reader",
    "tools/nos": "the CLI; shell cannot import Python",
    "tools/spore/nos-spore.sh": "runs from a spore image, without the repo",
    "tools/spore/germinate.sh": "runs on a fresh host, without the repo",
    "files/anatomy/wing/app/AgentKit/Tools/BashReadOnlyTool.php": "a HOME-relative secret-dir exception, not a path",
}
SKIP = re.compile(r"(^tests/|^docs/|\.md$|\.jsonl?$|^state/)")


def test_no_spelling_of_the_estate_default_outside_the_declaring_sites():
    files = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True).stdout.split()
    hits = []
    for rel in files:
        if rel in DECLARING or SKIP.search(rel):
            continue
        try:
            text = (REPO / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits += [f"{rel}:{n}: {ln.strip()}" for n, ln in enumerate(text.splitlines(), 1)
                 if SPELLING.search(ln) and not COMMENT.match(ln)]
    assert not hits, "use nos_estate_dir / nos_identity.estate_dir() / $NOS_ESTATE_DIR:\n  " + "\n  ".join(hits)


def test_the_declaring_sites_honour_nos_estate_dir():
    shells = [s for s in DECLARING if s.endswith(".sh") or s == "tools/nos"]
    for rel in shells:
        lines = [ln for ln in (REPO / rel).read_text(encoding="utf-8").splitlines()
                 if SPELLING.search(ln) and not COMMENT.match(ln)]
        assert lines and all("${NOS_ESTATE_DIR:-$HOME/.nos/estate}" in ln for ln in lines), (rel, lines)
    cfg = (REPO / "default.config.yml").read_text(encoding="utf-8")
    assert re.search(r"^nos_estate_dir: .*NOS_ESTATE_DIR", cfg, re.M), "nos_estate_dir must derive from NOS_ESTATE_DIR"


def test_the_python_reader_honours_the_env(monkeypatch, tmp_path):
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity
    monkeypatch.setenv("NOS_ESTATE_DIR", str(tmp_path))
    assert nos_identity.estate_dir() == tmp_path
    monkeypatch.delenv("NOS_ESTATE_DIR")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert nos_identity.estate_dir() == tmp_path / ".nos" / "estate"
