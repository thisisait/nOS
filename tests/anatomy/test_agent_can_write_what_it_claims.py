"""An agent that declares a WRITING task_type must hold a matching write scope.

The routing match checks task_type membership and KAM subset, but not that a
writing task_type (code-fix/seed-edit/design/…) is backed by a scope that can
actually WRITE its target. Without this, a read-only agent could carry
`code-fix` in its task_types and MATCH a code-fix assignment it cannot perform —
a fabricated affordance, the shape this estate keeps paying for. This gate seals
it: for every writing task_type an agent authors (state/task-types.yml `writes`),
its capability KAM (tools/agent-capability.py) must cover the write target.

  writes=code  → needs a repo write            (bare `repo`)
  writes=docs  → needs repo write OR the loop   (`repo` or `loop`)
  writes=data  → needs a data store write       (`dtt`, `wing`, or `keap`)
  writes=live  → converge; operator-only (needs_operator), no agent scope

A bare scope (`repo`, not `repo.read`) is the write form; a `.read` verb is not.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))


def _load(mod: str):
    spec = importlib.util.spec_from_file_location(mod, REPO / "tools" / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


cap = _load("agent-capability")
uri = _load("nos_work_uri")

WRITE_TARGETS = {
    "code": {"repo"},
    "docs": {"repo", "loop"},
    "data": {"dtt", "wing", "keap"},
}


def _task_types() -> dict:
    return yaml.safe_load((REPO / "state/task-types.yml").read_text())["task_types"]


def test_a_writing_task_type_has_a_write_scope():
    tt = _task_types()
    problems = []
    for doc in cap._agents():
        addr = cap.capability(doc)
        if addr is None:
            continue  # no capability (ops-* subjects)
        kam = uri.parse(addr).kam  # a set of scope strings
        for t in doc.get("task_types") or []:
            writes = tt.get(t, {}).get("writes")
            target = WRITE_TARGETS.get(writes)
            if target is None:
                continue  # none / live (operator) — no agent write scope required
            if not (kam & target):
                problems.append(
                    f"{doc['name']}: task_type '{t}' writes {writes}, but its scope "
                    f"{sorted(kam)} covers none of {sorted(target)} — it cannot perform "
                    "the work it advertises"
                )
    assert not problems, "agents claiming work they cannot write:\n  " + "\n  ".join(problems)
