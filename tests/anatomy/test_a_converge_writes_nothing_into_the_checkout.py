"""No Ansible copy/template/file task writes under the checkout's state/ or events/.

WHY (repo-body-plan I-11, 2026-10-07). apps_runner wrote
state/smoke-catalog.runtime.yml into the checkout: a runtime fact in the
source tree, one `git status` away from being committed. ~/.nos is the
runtime home. The task YAML is parsed (not grepped) and each task's dest/path
is read.
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
MODULES = {"copy", "template", "file"}
INTO_CHECKOUT = re.compile(
    r"\{\{\s*(playbook_dir|nos_main_checkout)\s*\}\}/(state|events)(/|$)")


def _tasks(node):
    if isinstance(node, list):
        for x in node:
            yield from _tasks(x)
    elif isinstance(node, dict):
        yield node
        for key in ("block", "rescue", "always", "tasks", "pre_tasks", "post_tasks", "handlers"):
            yield from _tasks(node.get(key))


def _task_files():
    for base in ("roles", "tasks", "handlers"):
        yield from (REPO / base).rglob("*.yml")
    yield from REPO.glob("*.yml")


def offenders(paths) -> list[str]:
    out = []
    for f in paths:
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except (yaml.YAMLError, UnicodeDecodeError):
            continue
        for task in _tasks(doc):
            for mod, args in task.items():
                if mod.rsplit(".", 1)[-1] not in MODULES or not isinstance(args, dict):
                    continue
                dest = str(args.get("dest") or args.get("path") or "")
                if INTO_CHECKOUT.search(dest):
                    out.append(f"{f}: {task.get('name', mod)} -> {dest}")
    return out


def test_the_parser_sees_a_write_into_the_checkout(tmp_path):
    """Positive control: the shape this gate exists for is found."""
    bad = tmp_path / "t.yml"
    bad.write_text("- block:\n  - ansible.builtin.copy:\n      dest: '{{ playbook_dir }}/state/x.yml'\n")
    assert offenders([bad])


def test_no_task_writes_into_checkout_state_or_events():
    found = offenders(_task_files())
    assert not found, (
        "a converge writes runtime state into the checkout; write it under "
        f"{{{{ nos_state_dir }}}} (~/.nos) instead: {found}")
