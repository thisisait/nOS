"""docs/systems cites law; it does not restate SHALL/MUST uncited.

nos-sot:doctrine/ssot.md#6 — reuse recipes cite nos-sot:doctrine/<file>#<id>
and do not restate the rule. tools/doctrine-cite.py already classifies
nos-sot; this gate asks it about docs/systems only (docs/ is not a harvest
root). RFC 2119 voice in a runbook without that cite is the failure.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SYSTEMS = REPO / "docs" / "systems"

#: Uppercase RFC 2119. Lowercase "must" is ordinary English, not a restatement.
RFC2119 = re.compile(r"\b(?:SHALL|MUST)(?:\s+NOT)?\b")


def _tool():
    spec = importlib.util.spec_from_file_location(
        "doctrine_cite_systems", REPO / "tools" / "doctrine-cite.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["doctrine_cite_systems"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def tool():
    return _tool()


@pytest.fixture(scope="module")
def corpus(tool):
    return tool.build_corpus()


def _systems_md():
    return sorted(p for p in SYSTEMS.rglob("*.md") if p.is_file())


def _doctrine_cites(tool, corpus, path: Path, rel: str):
    cites = tool.harvest_file(path, rel, corpus)
    tool.resolve(cites, corpus)
    return [
        c for c in cites
        if c.how == "nos-sot"
        and c.status == "resolved"
        and (c.doc or "").startswith("ssot/doctrine/")
        and c.key
    ]


def restates_without_cite(tool, corpus, path: Path, rel: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if not RFC2119.search(text):
        return False
    return not _doctrine_cites(tool, corpus, path, rel)


def test_a_systems_page_restating_shall_without_cite_fails(tool, corpus, tmp_path):
    src = tmp_path / "README.md"
    src.write_text("Operators SHALL enable MFA.\n", encoding="utf-8")
    assert restates_without_cite(tool, corpus, src, "docs/systems/_plant/README.md")


def test_live_systems_pages_do_not_restate_without_a_cite(tool, corpus):
    bad = [
        path.relative_to(REPO).as_posix()
        for path in _systems_md()
        if restates_without_cite(tool, corpus, path, path.relative_to(REPO).as_posix())
    ]
    assert not bad, (
        "systems page restates SHALL/MUST without nos-sot:doctrine/<file>#<id>:\n  "
        + "\n  ".join(bad)
    )
