"""Anatomy gate — core-up.yml fails AT the failed `up`, not 8 minutes later.

WHY: `files/anatomy/scripts/stack-health-probe.py` cannot distinguish "every
service in this stack is toggled off" (0 containers, legitimate) from "the
stack's `docker compose up -d` never created a single container" (0
containers, catastrophic) — both print `0/0 ready (no containers — stack
empty)` and the STRICT health-wait treats both as ALL_READY. Measured on the
Linux CI runner 2026-07-22: `infra: rc=1 open .../docker-compose.yml: no such
file or directory` immediately followed by `infra: 0/0 ready (no containers —
stack empty)` — the run then provisioned for 8 more minutes on an estate with
no MariaDB/PostgreSQL/Authentik/Traefik. docs/hidden_fees/08.

`tasks/stacks/core-up.yml` registers `_core_infra_result` / `_core_obs_result`
with `failed_when: false` — deliberate, so a dedicated task owns the failure
message instead of Ansible's generic "non-zero return code" (the same reason
`tasks/stacks/stack-up.yml`'s remaining-stacks `up -d` carries it, see the
fail-fast assert there, "[Stacks] Assert all stacks started"). But nothing
ever consumed the rc `core-up.yml` captured — DB post-start, the infra
health-wait, and the observability stack all ran regardless.

This gate pins the fix: a fail-fast task for EACH of infra and observability
that (a) exists, (b) triggers when that stack's `up -d` returned non-zero AND
the stack is enabled, (c) runs BEFORE anything downstream that assumes the
stack is reachable (DB post-start / the stack's own health-wait), (d) leaves
`failed_when: false` in place on the `up -d` tasks (the message-ownership
reason above still holds), and (e) does NOT fire when the stack is legitimately
disabled (`_core_infra_enabled`/`_core_observability_enabled` False) — a
disabled core stack has no `up -d` result to fail on, and must stay silent.

No network, no docker — pure YAML-structure assertions against the task list.
"""
from __future__ import annotations

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CORE_UP = REPO_ROOT / "tasks" / "stacks" / "core-up.yml"


def _load_tasks() -> list:
    docs = list(yaml.safe_load_all(CORE_UP.read_text()))
    tasks = docs[0] if docs else None
    assert isinstance(tasks, list), f"{CORE_UP} did not parse to a task list"
    return tasks


def _flatten_when(when) -> str:
    if when is None:
        return ""
    if isinstance(when, list):
        return " && ".join(str(w) for w in when)
    return str(when)


def _find(tasks: list, *, name_contains: str, module: str | None = None) -> int:
    """Index of the first task whose name contains a substring."""
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            continue
        if name_contains in str(t.get("name", "")):
            if module is None or module in t:
                return i
    return -1


def _get(tasks: list, idx: int) -> dict:
    assert idx >= 0
    return tasks[idx]


# ── Fixed points every assertion below is relative to ──────────────────────
def _indices(tasks: list) -> dict:
    return {
        "infra_up": _find(tasks, name_contains="Start INFRA stack"),
        "infra_result": _find(tasks, name_contains="Infra stack start result"),
        "infra_failfast": _find(tasks, name_contains="Infra bring-up failed"),
        "mariadb_post": _find(tasks, name_contains="MariaDB post-start"),
        "postgresql_post": _find(tasks, name_contains="pazny.postgresql post-start"),
        "infra_wait": _find(tasks, name_contains="Wait for INFRA stack healthy"),
        "obs_up": _find(tasks, name_contains="Start OBSERVABILITY stack"),
        "obs_result": _find(tasks, name_contains="Observability stack start result"),
        "obs_failfast": _find(tasks, name_contains="Observability bring-up failed"),
        "obs_wait": _find(tasks, name_contains="Wait for OBSERVABILITY stack healthy"),
    }


def test_all_anchor_tasks_present():
    idx = _indices(_load_tasks())
    missing = [k for k, v in idx.items() if v < 0]
    assert not missing, f"core-up.yml is missing expected task(s): {missing}"


# ── The fail-fast tasks exist and are real ansible.builtin.fail tasks ──────
def test_infra_failfast_is_a_fail_task():
    tasks = _load_tasks()
    idx = _indices(tasks)
    t = _get(tasks, idx["infra_failfast"])
    assert "ansible.builtin.fail" in t or "fail" in t, (
        "'Infra bring-up failed' must be an ansible.builtin.fail task, "
        f"got keys: {list(t.keys())}"
    )


def test_observability_failfast_is_a_fail_task():
    tasks = _load_tasks()
    idx = _indices(tasks)
    t = _get(tasks, idx["obs_failfast"])
    assert "ansible.builtin.fail" in t or "fail" in t, (
        "'Observability bring-up failed' must be an ansible.builtin.fail task, "
        f"got keys: {list(t.keys())}"
    )


# ── Ordering: fail-fast runs BEFORE anything that assumes the stack is up ──
def test_infra_failfast_runs_before_db_post_start_and_health_wait():
    tasks = _load_tasks()
    idx = _indices(tasks)
    assert idx["infra_up"] < idx["infra_result"] < idx["infra_failfast"], (
        "expected order: up -d -> result debug -> fail-fast, got "
        f"{idx['infra_up']} / {idx['infra_result']} / {idx['infra_failfast']}"
    )
    assert idx["infra_failfast"] < idx["mariadb_post"], (
        "infra fail-fast (#{}) must run BEFORE MariaDB post-start (#{}) — "
        "DB setup must not attempt to reach infra that never came up".format(
            idx["infra_failfast"], idx["mariadb_post"]
        )
    )
    assert idx["infra_failfast"] < idx["postgresql_post"], (
        "infra fail-fast must run BEFORE PostgreSQL post-start"
    )
    assert idx["infra_failfast"] < idx["infra_wait"], (
        "infra fail-fast must run BEFORE the infra health-wait — the whole "
        "point is to stop before the probe ever reports on a stack that "
        "never got containers"
    )


def test_observability_failfast_runs_before_its_health_wait():
    tasks = _load_tasks()
    idx = _indices(tasks)
    assert idx["obs_up"] < idx["obs_result"] < idx["obs_failfast"] < idx["obs_wait"], (
        "expected order: up -d -> result debug -> fail-fast -> health-wait, got "
        f"{idx['obs_up']} / {idx['obs_result']} / {idx['obs_failfast']} / {idx['obs_wait']}"
    )


# ── Trigger condition: rc != 0 AND the stack is enabled ─────────────────────
def test_infra_failfast_when_references_rc_and_enabled_flag():
    tasks = _load_tasks()
    idx = _indices(tasks)
    when = _flatten_when(_get(tasks, idx["infra_failfast"]).get("when"))
    assert "_core_infra_result" in when and "rc" in when, (
        f"infra fail-fast `when:` must key off _core_infra_result.rc, got: {when!r}"
    )
    assert "_core_infra_enabled" in when, (
        f"infra fail-fast `when:` must respect _core_infra_enabled (a "
        f"legitimately disabled infra has no up -d result to fail on), got: {when!r}"
    )
    assert "!= 0" in when.replace(" ", "") or "!=0" in when.replace(" ", ""), (
        f"infra fail-fast must trigger on rc != 0, got: {when!r}"
    )


def test_observability_failfast_when_references_rc_and_enabled_flag():
    tasks = _load_tasks()
    idx = _indices(tasks)
    when = _flatten_when(_get(tasks, idx["obs_failfast"]).get("when"))
    assert "_core_obs_result" in when and "rc" in when, (
        f"observability fail-fast `when:` must key off _core_obs_result.rc, got: {when!r}"
    )
    assert "_core_observability_enabled" in when, (
        f"observability fail-fast `when:` must respect _core_observability_enabled, "
        f"got: {when!r}"
    )


# ── failed_when: false on the `up -d` tasks is preserved (message-ownership) ─
def test_up_tasks_keep_failed_when_false():
    tasks = _load_tasks()
    idx = _indices(tasks)
    for key in ("infra_up", "obs_up"):
        t = _get(tasks, idx[key])
        assert t.get("failed_when") is False, (
            f"'{t.get('name')}' must keep failed_when: false — the dedicated "
            "fail-fast task (not Ansible's generic rc-check) owns the message"
        )
