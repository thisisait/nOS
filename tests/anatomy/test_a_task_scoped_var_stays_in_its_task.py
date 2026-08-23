"""A `vars:` block belongs to ONE task, and reading it from another is silent.

WHAT HAPPENED, 2026-08-23, twice in one hour. `tasks/tofu-authentik.yml` loads
the Authentik service registry with a task-scoped `vars:` block, deliberately,
with the reason written above it:

    # TASK-SCOPED registry load — NOT include_vars (play-scoped). The registry
    # values carry raw Jinja; persisting them into the play namespace makes
    # nos_state's `role_vars: "{{ vars }}"` eager-finalize choke.

A new task 140 lines further down was given
`tofu_authentik_services | default([])`. The name is undefined there, so the
fallback answered — with an EMPTY LIST. The task's job was to decide which
planned destroys a disabled service explains; with no registry, every one came
back *"not in the registry — un-authored"*, the verdict that refuses hardest,
and a converge died on a removal the operator had authorised two days earlier.

It failed twice for the same reason at two levels. The fix was verified against
the registry FILE, which of course contains the service — while the code reads
a VARIABLE that did not. That is `docs/hidden_fees/23` again: the template said
one thing and the render said another, and only the render matters.

WHAT THIS GATE ENFORCES. Within one task file, a name defined only in some
task's `vars:` may not be referenced by a different task. Play-scope names are
exempt (they resolve everywhere by definition); a task re-declaring the name in
its own `vars:` is exempt, which is the correct fix and the one applied here.

WHY IT IS WORTH A GATE. There is no error. Ansible resolves an undefined name to
whatever `| default()` says, and the estate's own review habit — check the
source file — confirms the wrong thing. The failure mode is a confident wrong
answer, which is this repository's most expensive recurring shape.

WHAT IT CANNOT SEE. A task-scoped var read from a DIFFERENT file (via
`include_tasks`), and whether a `| default()` value is a sensible fallback where
the name genuinely is optional.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TASK_DIRS = ("tasks",)
PLAY_SCOPE_FILES = ("default.config.yml", "default.credentials.yml")

_REFERENCE = re.compile(r"\{\{(.*?)\}\}|\{%(.*?)%\}", re.S)
_IDENT = re.compile(r"\b([a-z_][a-z0-9_]{2,})\b")


def _play_scope() -> set[str]:
    names: set[str] = set()
    for name in PLAY_SCOPE_FILES:
        data = yaml.safe_load((REPO / name).read_text(encoding="utf-8")) or {}
        names |= set(data)
    return names


def _walk(tasks, out: list[dict], inherited: frozenset = frozenset()) -> None:
    """Collect LEAF tasks with the var names visible to each.

    A `vars:` on a **block** is in scope for every task inside it — that is
    Ansible's rule and it is load-bearing here (`_tf_dir` is declared once on
    the drift-check block and used by eight tasks within). The first cut of
    this gate flattened blocks away and reported fifteen of those as offenders.

    A `vars:` on a LEAF task is not inherited by anything, and that is the case
    this gate is about: the registry load sits on the tfvars-render task, so a
    sibling 140 lines later saw nothing.
    """
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if not isinstance(task, dict):
            continue
        own = frozenset(task.get("vars") or {})
        nested = [k for k in ("block", "rescue", "always") if task.get(k)]
        if nested:
            for key in nested:
                _walk(task.get(key), out, inherited | own)
            continue                                  # a block is not a leaf
        out.append({"task": task, "visible": inherited | own})


def _names_referenced(task: dict) -> set[str]:
    """Every identifier inside a Jinja expression anywhere in the task, minus
    its own `vars:` block — a task may of course use what it declares."""
    body = {k: v for k, v in task.items() if k not in ("vars", "block", "rescue", "always")}
    text = yaml.safe_dump(body, default_flow_style=False, allow_unicode=True)
    names: set[str] = set()
    for a, b in _REFERENCE.findall(text):
        names |= set(_IDENT.findall(a or b or ""))
    return names


def _task_files():
    for directory in TASK_DIRS:
        yield from sorted((REPO / directory).rglob("*.yml"))


def test_no_task_reads_another_tasks_vars_block():
    play = _play_scope()
    offenders: list[str] = []

    for path in _task_files():
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue                                  # not our call
        leaves: list[dict] = []
        _walk(doc if isinstance(doc, list) else [], leaves)
        if not leaves:
            continue

        # Only names a LEAF declares for itself. A block's vars are inherited
        # and therefore never task-local.
        declared: dict[str, str] = {}
        for leaf in leaves:
            for name in (leaf["task"].get("vars") or {}):
                declared.setdefault(str(name), str(leaf["task"].get("name", "?")))

        scoped = {n: owner for n, owner in declared.items() if n not in play}
        if not scoped:
            continue

        for leaf in leaves:
            task = leaf["task"]
            for name in _names_referenced(task) & set(scoped):
                if name in leaf["visible"]:
                    continue                          # declared here or by a block
                offenders.append(
                    f"{path.relative_to(REPO)}: task {str(task.get('name', '?'))[:52]!r} "
                    f"reads `{name}`, which only task {scoped[name][:44]!r} declares")

    assert not offenders, (
        "these tasks read a name that lives in ANOTHER task's vars: block, so it "
        "resolves to whatever `| default()` supplies and nothing errors:\n  "
        + "\n  ".join(offenders)
        + "\n(this is how the tofu destroy guard got an empty service registry "
          "and refused a removal the operator had authorised — fix by giving "
          "the task its own vars: block, not by widening the default)")


def test_the_task_this_gate_was_written_for_declares_what_it_reads():
    """Named explicitly, because the general rule above would also pass if the
    task simply stopped consulting the registry — which would make the guard
    refuse everything again, quietly."""
    doc = yaml.safe_load((REPO / "tasks/tofu-authentik.yml").read_text(encoding="utf-8"))
    leaves: list[dict] = []
    _walk(doc if isinstance(doc, list) else [], leaves)
    split = [leaf["task"] for leaf in leaves
             if "Attribute each destroy" in str(leaf["task"].get("name", ""))]
    assert split, "the destroy-attribution task is gone"
    assert "tofu_authentik_services" in (split[0].get("vars") or {}), (
        "the destroy-attribution task no longer loads the registry itself; it "
        "would see an empty one and call every destroy un-authored")
    rendered = yaml.safe_dump(split[0])
    assert "default([])" not in rendered.replace(" ", ""), (
        "a `| default([])` on the registry turns 'I could not read it' into "
        "'nothing is authorised' — the exact substitution that failed live")
