"""Anatomy CI gate — the locked-keychain refusal runs on every run that builds.

MEASURED 2026-10-18, client Mac over SSH after a reboot: `nos --tags pulse`
ran ~170 tasks, then the iiab stack build died on the Docker credential helper
("the current session does not allow user interaction"). The refusal existed,
but was tagged like core-up while stack-up's compose up is tagged `always`, so
a service tag reached the build and skipped the refusal.

Pinned end to end: walk main.yml's task order (imports expanded, tags
inherited); the refusal comes before the first compose up/build/pull, runs
whenever any of them runs, and names the unlock command.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = re.compile(r"compose\b.*?\s(up|build|pull)\b", re.S)


def _walk(tasks, tags: frozenset, out: list) -> list:
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        tt = tags | set(t.get("tags") or [])
        for k in ("block", "rescue", "always"):
            _walk(t.get(k), tt, out)
        imp = next((t[k] for k in ("import_tasks", "ansible.builtin.import_tasks",
                                   "include_tasks", "ansible.builtin.include_tasks") if k in t), None)
        if isinstance(imp, dict):
            imp = imp.get("file")
        if isinstance(imp, str) and "{{" not in imp and (REPO / imp).is_file():
            _walk(yaml.safe_load((REPO / imp).read_text(encoding="utf-8")), tt, out)
            continue
        out.append((t, tt))
    return out


def _order() -> list:
    out: list = []
    for play in yaml.safe_load((REPO / "main.yml").read_text(encoding="utf-8")):
        for key in ("pre_tasks", "tasks", "post_tasks"):
            _walk(play.get(key), frozenset(), out)
    return out


def _cmd(t: dict) -> str:
    return str(next((t[k] for k in ("command", "shell", "ansible.builtin.command",
                                    "ansible.builtin.shell") if k in t), ""))


def _runs_whenever(guard: frozenset, task: frozenset) -> bool:
    """Every --tags selection that runs `task` also runs `guard`."""
    return "always" in guard or ("always" not in task and task <= guard)


def test_the_keychain_refusal_runs_before_every_compose_up():
    order = _order()
    refusal = next((i for i, (t, _) in enumerate(order)
                    if "security -v unlock-keychain" in str(t.get("ansible.builtin.fail", t.get("fail", "")))), -1)
    assert refusal >= 0, "no refusal names `security -v unlock-keychain`"
    probe = next((i for i, (t, _) in enumerate(order) if "show-keychain-info" in _cmd(t)), -1)
    assert 0 <= probe < refusal, "the refusal must follow the keychain probe it reads"
    ups = [i for i, (t, _) in enumerate(order)
           if COMPOSE.search(_cmd(t)) or any("docker_compose" in k for k in t)]
    assert ups, "walker found no compose up/build/pull; the gate is blind"
    assert refusal < ups[0], (
        f"first compose up ({order[ups[0]][0].get('name')}) runs before the keychain refusal")
    skipped = [order[i][0].get("name") for i in ups
               if not (_runs_whenever(order[probe][1], order[i][1])
                       and _runs_whenever(order[refusal][1], order[i][1]))]
    assert not skipped, (
        f"a --tags run reaches these compose steps but skips the keychain check: {skipped}")
