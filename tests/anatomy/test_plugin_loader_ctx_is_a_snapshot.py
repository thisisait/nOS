"""Plugin-loader template_vars is a snapshot, not live `vars`.

MEASURED 2026-09-14: post_compose paid ~113s of silence templating the live
`vars` dict after core-up stuffed it with compose/register payloads. pre_compose
on the same module was 2.4s — the difference is the size of `vars`. Ansible
eager-finalizes `template_vars` BEFORE the TASK line.

The cut: snapshot `nos_plugin_ctx: "{{ vars }}"` once (config-sized) and pass
that fact. The 190-var generator is the ansible-core 2.24 track
(tools/loader-vars-report.py); this gate pins the snapshot, not that generator.

Retro-red: on the pre-fix tree every loader still has `template_vars: "{{ vars }}"`
and there is no `nos_plugin_ctx` set_fact, so these assertions fail there.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
LOADER_PLAYS = (
    REPO / "tasks" / "stacks" / "core-up.yml",
    REPO / "tasks" / "stacks" / "stack-up.yml",
    REPO / "tasks" / "blank-reset.yml",
)
CORE_UP = LOADER_PLAYS[0]
BLANK_RESET = LOADER_PLAYS[2]


def _tasks(path: pathlib.Path) -> list[dict]:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, list), f"{path} must be a task list"
    return data


def _loader(task: dict) -> dict | None:
    body = task.get("nos_plugin_loader")
    return body if isinstance(body, dict) else None


def _set_fact(task: dict) -> dict | None:
    body = task.get("ansible.builtin.set_fact") or task.get("set_fact")
    return body if isinstance(body, dict) else None


def test_every_plugin_loader_passes_the_snapshot_not_live_vars():
    hits = []
    for path in LOADER_PLAYS:
        for i, task in enumerate(_tasks(path)):
            loader = _loader(task)
            if loader is None:
                continue
            tv = loader.get("template_vars")
            if tv != "{{ nos_plugin_ctx }}":
                hits.append(f"{path.name} task[{i}] {task.get('name')!r}: {tv!r}")
    assert not hits, (
        "nos_plugin_loader must pass template_vars: nos_plugin_ctx, not live "
        "`vars` (post_compose eager-finalize of bloated vars is ~113s):\n  "
        + "\n  ".join(hits)
    )


def test_core_up_snapshots_ctx_before_first_loader():
    seen_loader = False
    seen_snapshot = False
    for task in _tasks(CORE_UP):
        fact = _set_fact(task)
        if fact is not None and fact.get("nos_plugin_ctx") == "{{ vars }}":
            seen_snapshot = True
        if _loader(task) is not None:
            assert seen_snapshot, (
                "core-up.yml first nos_plugin_loader runs before nos_plugin_ctx "
                "is snapshotted — post_compose would still eager-finalize live vars"
            )
            seen_loader = True
            break
    assert seen_loader, "core-up.yml has no nos_plugin_loader task"


def test_blank_reset_snapshots_ctx_before_its_loader():
    seen_snapshot = False
    seen_loader = False
    for task in _tasks(BLANK_RESET):
        fact = _set_fact(task)
        if fact is not None and fact.get("nos_plugin_ctx") == "{{ vars }}":
            seen_snapshot = True
        if _loader(task) is not None:
            assert seen_snapshot, (
                "blank-reset.yml loader runs before a nos_plugin_ctx snapshot; "
                "removal can reach this file before core-up"
            )
            seen_loader = True
            break
    assert seen_loader, "blank-reset.yml has no nos_plugin_loader task"


def test_stack_up_snapshots_ctx_before_compose_if_core_did_not():
    """nos-stacks.sh can skip core-up; snapshot must not wait until post_compose."""
    stack = REPO / "tasks" / "stacks" / "stack-up.yml"
    seen_snapshot = False
    for task in _tasks(stack):
        fact = _set_fact(task)
        if fact is not None and fact.get("nos_plugin_ctx") == "{{ vars }}":
            seen_snapshot = True
            cond = str(task.get("when", ""))
            assert "nos_plugin_ctx is not defined" in cond, (
                "stack-up must not re-snapshot after core-up — that would "
                "eager-finalize the bloated vars the snapshot exists to avoid"
            )
            break
        if _loader(task) is not None:
            break
    assert seen_snapshot, (
        "stack-up.yml has no nos_plugin_ctx snapshot before its first loader"
    )
