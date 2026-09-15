"""Anatomy gate — cortex-query is a READER over KEAP recall, never a writer.

WHY THIS IS A GATE. A skill that "queries the cortex" can ship green on an
empty answer: broken RO token, drained embeddings, or a second HTTP client
that never actually called KEAP. Empty recall is a miss, not a pass.

The procedure lives at files/anatomy/skills/cortex-query/SKILL.md. The
machinery is tools/cortex-query.py, which wraps the EXISTING client
(tools/keap-semantic-search.py) and the EXISTING query set
(tools/keap-recall-queries.py). Inventing a second /agent/v1 client is the
defect this file watches for.

T0: a known query from the recall set returns a known passage. Live KEAP is
preferred; when it is unreachable the recorded fixture stands in. An empty
hit list fails either way.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SKILL = REPO / "files" / "anatomy" / "skills" / "cortex-query" / "SKILL.md"
TOOL = REPO / "tools" / "cortex-query.py"
CLIENT = REPO / "tools" / "keap-semantic-search.py"
QUERIES = REPO / "tools" / "keap-recall-queries.py"
FIXTURE = REPO / "tests" / "fixtures" / "cortex-query-recall.json"

SMOKE_Q = "is cortex up"


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cq():
    return _load(TOOL, "cortex_query")


@pytest.fixture(scope="module")
def recall():
    return _load(QUERIES, "keap_recall_queries")


def test_skill_exists_with_frontmatter():
    assert SKILL.is_file(), "files/anatomy/skills/cortex-query/SKILL.md missing"
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---"), "skill has no frontmatter"
    assert "name: cortex-query" in text
    assert "when not to use" in text.lower()


def test_skill_is_read_only_and_names_the_existing_client():
    text = SKILL.read_text(encoding="utf-8")
    assert "tools/keap-semantic-search.py" in text, (
        "skill must wrap the existing semantic-search client, not a new one")
    assert "tools/keap-recall-queries.py" in text, (
        "known queries come from the recall set, not a second list")
    assert "KEAP_AGENT_TOKEN_RO" in text
    assert "tools/cortex-query.py" in text
    lowered = text.lower()
    assert "refus" in lowered
    for banned in ("POST /agent/v1/captures", "KEAP_AGENT_TOKEN_RW"):
        assert banned not in text, f"read-only skill must not teach {banned}"


def test_wrapper_does_not_invent_a_second_client():
    src = TOOL.read_text(encoding="utf-8")
    assert "urllib.request" not in src, (
        "cortex-query.py opened its own HTTP client; wrap "
        "tools/keap-semantic-search.py instead")
    assert "keap-semantic-search.py" in src or "keap_semantic_search" in src
    assert "keap-recall-queries.py" in src or "keap_recall_queries" in src


def test_smoke_query_is_in_the_recall_set(recall):
    cases = {c["q"]: c for c in recall.build()["cases"]}
    assert SMOKE_Q in cases, (
        f"{SMOKE_Q!r} is not in tools/keap-recall-queries.py — pick a query "
        "the SKILLS.md trigger set already owns")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["q"] == SMOKE_Q
    assert fixture["expect"] == cases[SMOKE_Q]["expect"]
    assert fixture["results"], "recorded fixture must not be empty (empty ≠ pass)"


def test_known_query_returns_known_passage(cq, recall):
    expect = next(c["expect"] for c in recall.build()["cases"] if c["q"] == SMOKE_Q)
    hits = cq.recall_hits(SMOKE_Q, fixture_path=FIXTURE)
    matched = cq.grade(hits, expect)
    assert matched, f"none of {expect} in ranked passages"


def test_empty_recall_is_red(cq, recall):
    expect = next(c["expect"] for c in recall.build()["cases"] if c["q"] == SMOKE_Q)
    with pytest.raises(cq.EmptyRecall):
        cq.grade([], expect)


def test_write_is_refused():
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--write", SMOKE_Q],
        cwd=REPO, capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "REFUSING" in (proc.stderr + proc.stdout)
    assert "read-only" in (proc.stderr + proc.stdout).lower()
