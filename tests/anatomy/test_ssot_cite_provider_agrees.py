"""Editor cites must agree with harvest_file+resolve — not a second parser.

ssot-cite-editor: the VS Code wrapper only spawns
``python3 tools/doctrine-cite.py --file REL --json``. These five shapes are
the provider contract. A stub ``--file`` that always emits ``resolved``
fails 3/4/5.

Temp citing files, live corpus (ssot.md headings). Not a full-tree harvest.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def tool():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "doctrine_cite_file", REPO / "tools" / "doctrine-cite.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["doctrine_cite_file"] = mod
    spec.loader.exec_module(mod)
    return mod


def _one(tool, tmp_path, name: str, body: str):
    src = tmp_path / name
    src.write_text(body, encoding="utf-8")
    corpus = tool.build_corpus()
    cites = tool.harvest_file(src, f"tests/_ssot_cite_{name}", corpus)
    tool.resolve(cites, corpus)
    sections = [c for c in cites if c.shape == "section"]
    assert sections, f"no section cite in {body!r}"
    return sections[0], corpus


def test_nos_sot_section_resolves(tool, tmp_path):
    c, _ = _one(tool, tmp_path, "a.py", "nos-sot:doctrine/ssot.md#5\n")
    assert c.status == "resolved", (
        "a stub --file that always-resolves is not this test; nos-sot #5 "
        f"must resolve, got {c.status}"
    )
    assert c.doc == "ssot/doctrine/ssot.md"
    assert c.key == "5"


def test_sameline_path_resolves(tool, tmp_path):
    c, _ = _one(tool, tmp_path, "b.py", "ssot/doctrine/ssot.md §1\n")
    assert c.status == "resolved"
    assert c.doc == "ssot/doctrine/ssot.md"
    assert c.key == "1"


def test_missing_section_is_wrong(tool, tmp_path):
    c, _ = _one(tool, tmp_path, "c.py", "ssot/doctrine/ssot.md §99\n")
    assert c.status == "wrong", (
        f"§99 on ssot.md must be wrong, not {c.status} — always-resolved stub"
    )


def test_missing_article_is_missing_doc(tool, tmp_path):
    c, _ = _one(tool, tmp_path, "d.py", "nos-sot:doctrine/no-such-article.md#1\n")
    assert c.status == "missing-doc", (
        f"no-such-article must be missing-doc, not {c.status}"
    )


def test_bare_section_is_unqualified(tool, tmp_path):
    c, _ = _one(tool, tmp_path, "e.py", "bare §5\n")
    assert c.status == "unqualified"
    assert c.doc is None


def test_known_finding_is_not_linted(tool):
    c = tool.Citation(
        "files/anatomy/cortex/server/fs-roots.ts", 1, "section", "12.2",
        "docs/archive/cortex-corpus-parallel.md", "header", status="wrong")
    assert (c.file, c.shape, c.key, c.status) in tool.KNOWN_FINDINGS
    assert tool.cite_lint(c) is False


def test_file_json_is_an_object_with_excerpt():
    proc = subprocess.run(
        [sys.executable, str(REPO / "tools" / "doctrine-cite.py"),
         "--file", "ssot/doctrine/ssot.md", "--json"],
        cwd=REPO, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert isinstance(data, dict) and "citations" in data
    assert data["citations"], "ssot.md names nos-sot / § — harvest_file must see them"
    row = data["citations"][0]
    assert "excerpt" in row and "lint" in row and "col" in row
    assert row["lint"] is False, "corpus md is outside HARVEST_ROOTS — no diagnose"
