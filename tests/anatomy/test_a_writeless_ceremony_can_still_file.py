"""Anatomy CI gate — `filed_by: runner` exists, and conductor declares it.

MEASURED 2026-09-02, sessions 7b95d55a + 11f550ec: conductor's manifest owed a
`conductor_report` event while its system.md forbade the ceremony any write
plane ("report to the operator rather than trying to POST") and mcp-bone is
GET-only — the gates passed twice and the run could NEVER satisfy. The old
claude-CLI path had the child signing the event with the HMAC secret; that was
hardened away and the AgentKit path got no replacement.

The f1ddef96 shape: the model writes, the RUNNER files. The reader still reads
the event BACK from the table, still refuses empty, and satisfaction still
requires the gate set — filing is not satisfying.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
AK = REPO / "files" / "anatomy" / "wing" / "app" / "AgentKit"


def _body(path: pathlib.Path) -> str:
    return "\n".join(ln for ln in path.read_text(encoding="utf-8").splitlines()
                     if not ln.lstrip().startswith(("//", "*", "/*", "#")))


def test_the_loader_refuses_an_unknown_filed_by():
    src = _body(AK / "AgentLoader.php")
    assert "filed_by" in src, "the loader no longer parses deliverable.filed_by"
    assert "['agent', 'runner']" in src and "AgentLoadException" in src, (
        "an unknown filed_by must be a LOAD error, not a ceremony that can "
        "never be satisfied and never says why")


def test_the_runner_files_only_under_the_flag_and_reads_back():
    src = _body(AK / "Runner.php")
    assert "deliverableFiledByRunner" in src, (
        "the runner no longer files the write-plane-less deliverable; "
        "conductor is unsatisfiable again (sessions 7b95d55a, 11f550ec)")
    i = src.index("deliverableFiledByRunner")
    guard = src[i - 200:i + 500]
    assert "trim($finalText) !== ''" in guard, (
        "the runner files an EMPTY report — the reader's refusal of empty "
        "bodies (9a5d6d0f) is being satisfied by its own writer")
    # The reader half must survive: the oracle still queries the table.
    assert "result_json" in src and "->query([" in src, (
        "the deliverable reader is gone — the runner would be writing a "
        "marker nobody reads back, the self-reporting shape")


def test_conductor_declares_runner_filing():
    doc = yaml.safe_load((REPO / "files/anatomy/agents/conductor/agent.yml")
                         .read_text(encoding="utf-8"))
    d = doc["outcomes"]["deliverable"]
    assert d["event"] == "conductor_report"
    assert d.get("filed_by") == "runner", (
        "conductor lost filed_by: runner. Its system.md forbids the write "
        "plane, so without it the ceremony owes an event no one may author")


def test_the_schema_names_both_values():
    schema = yaml.safe_load((REPO / "state/schema/agent.schema.yaml")
                            .read_text(encoding="utf-8"))
    deliverable = schema["properties"]["outcomes"]["properties"]["deliverable"]
    assert deliverable["properties"]["filed_by"]["enum"] == ["agent", "runner"]
