"""The local-model bench asks for the v3 opcodes and scores them, offline.

Increment 2 of iris-speaks-cortex-lang: four tasks a table question really
needs (sum-by-track, kpi-total, top3-desc, edit-set). Each carries a reference
chain; the vendored analyzer must accept it (on the v2 registry it does not:
unknown_opcode / unknown_param), and the bench's own scorer must credit it.
No model and no KEAP: the analyzer is pure.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CORTEX = REPO / "files/anatomy/cortex"
TASKS = REPO / "state/fixtures/local-model-bench.yml"
TOOL = REPO / "tools/local-model-bench.py"

V3_TASKS = {"sum-by-track": "aggregate", "kpi-total": "show",
            "top3-desc": "rank", "edit-set": "update"}

needs_tsx = pytest.mark.skipif(
    not (CORTEX / "node_modules/.bin/tsx").exists(),
    reason="cortex node_modules absent — run `npm ci` in files/anatomy/cortex",
)


def _spec() -> dict:
    return yaml.safe_load(TASKS.read_text(encoding="utf-8"))


def _tasks() -> dict[str, dict]:
    return {t["id"]: t for t in _spec()["tasks"]}


def _bench():
    spec = importlib.util.spec_from_file_location("local_model_bench", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _analyze(chains: list[str]) -> dict:
    code = (
        'import {analyzeCortex} from "./server/cortex-lang";'
        'import {CORTEX_OPCODES} from "./server/cortex-opcodes";'
        'const chains = JSON.parse(process.argv[1]);'
        'console.log(JSON.stringify({opcodes: CORTEX_OPCODES.map(o => o.name),'
        ' errors: chains.map(c => analyzeCortex(c).errors.map(e => e.code))}));'
    )
    done = subprocess.run(["npx", "tsx", "-e", code, json.dumps(chains)],
                          capture_output=True, text=True, timeout=120, cwd=CORTEX)
    assert done.returncode == 0, done.stderr[-600:]
    return json.loads(done.stdout)


def test_the_v3_tasks_are_in_the_set() -> None:
    tasks = _tasks()
    for tid, op in V3_TASKS.items():
        assert tid in tasks, f"bench has no {tid} task"
        assert tasks[tid]["expect_opcode"] == op
        assert tasks[tid].get("reference"), f"{tid} carries no reference chain"


@needs_tsx
def test_every_reference_chain_passes_the_analyzer() -> None:
    refs = {tid: t["reference"] for tid, t in _tasks().items() if t.get("reference")}
    got = _analyze(list(refs.values()))
    bad = {tid: errs for tid, errs in zip(refs, got["errors"]) if errs}
    assert not bad, f"reference chains the registry refuses: {bad}"


@needs_tsx
def test_the_primer_names_every_registry_opcode() -> None:
    system = _spec()["system"]
    missing = [op for op in _analyze([])["opcodes"] if op not in system.split()]
    assert not missing, f"the primer never teaches {missing}"


def test_the_scorer_credits_the_reference_and_not_a_neighbour() -> None:
    bench, tasks = _bench(), _tasks()
    for tid in V3_TASKS:
        task = tasks[tid]
        assert bench.intent_ok(task, task["reference"]), f"{tid}: own reference not credited"
        for other in V3_TASKS:
            if other != tid:
                assert not bench.intent_ok(task, tasks[other]["reference"]), (
                    f"{tid} credits {other}'s chain — the scorer checks too little")
