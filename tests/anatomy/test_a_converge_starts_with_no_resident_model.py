"""Gate: a converge drops resident local models before services come up.

A 14 GB resident model starved KEAP and failed the release converge twice
(dtt ollama-residency-as-a-pausable-resource). Live 2026-10-02: hermes3:8b
resident -> the task file unloaded it (keep_alive 0) -> /api/ps empty.
"""
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
TASKS = yaml.safe_load((REPO / "tasks/models-unload.yml").read_text())


def test_it_runs_before_the_stacks_and_always():
    main = (REPO / "main.yml").read_text()
    assert main.index("import_tasks: tasks/models-unload.yml") < main.index("import_tasks: tasks/stacks/core-up.yml")
    blk = main[main.index("tasks/models-unload.yml") - 200: main.index("tasks/models-unload.yml") + 80]
    assert "'always'" in blk


def test_it_unloads_with_keep_alive_zero_and_never_blocks():
    unload = next(t for t in TASKS if "Unload" in t["name"])
    assert unload["ansible.builtin.uri"]["body"]["keep_alive"] == 0
    assert all(t.get("failed_when") is False for t in TASKS if "ansible.builtin.uri" in t), \
        "an absent Ollama must not fail the converge"
