"""A `-cloud` measurement cell keeps its local sibling's definition byte for byte.

WHY (2026-10-07, roadmap row `cell-level-words-and-capability-map`). The ops
harness compares ops-triage with ops-triage-cloud (and ops-extract with its
-cloud sibling) to learn what the BACKEND changes. That reading holds only while
the prompt and the one-shot schema are the same bytes; one edited byte makes it
a comparison of two definitions. There is no `definition_from` field on purpose:
a definition is the cell's own, so each cell keeps its own copy and this gate
keeps the copies equal. jeff/jeff-cloud are not a pair: their prompts differ.
"""

from __future__ import annotations

import pathlib

import pytest

AGENTS = pathlib.Path(__file__).resolve().parents[2] / "files/anatomy/agents"
PAIRS = ("ops-triage", "ops-extract")
DEFINITION = ("system.md", "one-shot.schema.json")


def _diverged(local: pathlib.Path, cloud: pathlib.Path) -> list[str]:
    return [f for f in DEFINITION if (local / f).read_bytes() != (cloud / f).read_bytes()]


@pytest.mark.parametrize("name", PAIRS)
def test_the_cloud_sibling_keeps_the_same_definition(name):
    diff = _diverged(AGENTS / name, AGENTS / f"{name}-cloud")
    assert not diff, f"{name} and {name}-cloud differ in {diff}; edit both or neither"


def test_one_byte_is_enough_to_fail(tmp_path):
    for side in ("a", "b"):
        (tmp_path / side).mkdir()
        for f in DEFINITION:
            (tmp_path / side / f).write_bytes((AGENTS / "ops-triage" / f).read_bytes())
    (tmp_path / "b/system.md").write_bytes((tmp_path / "b/system.md").read_bytes() + b" ")
    assert _diverged(tmp_path / "a", tmp_path / "b") == ["system.md"]
