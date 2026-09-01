"""Anatomy CI gate — the mount repair must precede the gate that a broken mount fails.

MEASURED 2026-09-01. Ansible's `template:` writes a temp file and RENAMES it
into place. A single-FILE bind mount binds the INODE, so the rename does not
merely leave the container reading stale content — it leaves the container's
path at ENOENT:

    in-place write (`> f`)   container sees the new bytes immediately
    atomic rename            container gets `No such file or directory`
    docker restart           re-binds; container sees the new bytes

Loki's healthcheck is `loki -verify-config` against exactly such a mount. A
converge that changed one line of `local-config.yaml` therefore took the
observability stack to `8/9 ready FAILED: loki-1` — and because the reconciler
that repairs this ran at the END of main.yml, AFTER the STRICT health-wait, the
run that caused the damage could never reach its own fix. That is a deadlock,
not a slow path: the wait burns its whole budget and then fails.

So the ordering is load-bearing, and this gate pins it:

  1. `tools/reload-stale-config.py --apply` runs INSIDE wait-stacks-healthy.yml,
     BEFORE the poll loop — every bring-up flow (core-up, stack-up, apps-up)
     routes through that one file, which is why the repair lives there and not
     in three callers.
  2. The end-of-run pass survives and still FAILS the play. The pre-wait call is
     the repair; the final one is the verdict, and only one of them may judge.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
WAIT = REPO / "tasks" / "stacks" / "wait-stacks-healthy.yml"
MAIN = REPO / "main.yml"
TOOL = "tools/reload-stale-config.py"


def _tasks(path: pathlib.Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def _index_of(tasks: list[dict], pred) -> int:
    for i, t in enumerate(tasks):
        if pred(t):
            return i
    return -1


def test_the_repair_precedes_the_poll_loop():
    tasks = _tasks(WAIT)
    repair = _index_of(
        tasks, lambda t: TOOL in str(t.get("ansible.builtin.command", "")))
    poll = _index_of(
        tasks, lambda t: "health-tick.yml" in str(t.get("ansible.builtin.include_tasks", "")))

    assert repair >= 0, (
        f"{WAIT.name} no longer repairs stale config mounts. A converge that "
        f"rewrites a bind-mounted config file leaves the container at ENOENT, "
        f"and the poll loop below then waits out its entire budget on damage "
        f"this run caused.")
    assert poll >= 0, f"{WAIT.name}: the health poll loop is gone"
    assert repair < poll, (
        f"{WAIT.name}: the repair is at task {repair} and the health poll at "
        f"{poll}. Repairing after the gate is the deadlock this file was "
        f"changed to end.")


def test_the_repair_does_not_also_judge():
    """Two callers, one verdict. The pre-wait call must not fail the play — the
    poll loop immediately after it is what decides whether the repair worked,
    and a hard failure here would pre-empt the diagnosis with a worse message."""
    tasks = _tasks(WAIT)
    repair = next(t for t in tasks
                  if TOOL in str(t.get("ansible.builtin.command", "")))
    assert repair.get("failed_when") is False, (
        f"{WAIT.name}: the pre-wait repair now fails the play itself. That "
        "steals the verdict from the health poll below and from the "
        "authoritative pass at the end of main.yml")


def test_the_end_of_run_pass_still_judges():
    """The repair being early must not have been a way to stop the run failing
    on config a container never picked up. That assertion lives at the end of
    main.yml and `failed_when: false` there was itself a fixed defect."""
    src = MAIN.read_text(encoding="utf-8")
    assert TOOL in src, (
        "main.yml no longer runs the config-reload reconciler at all; the "
        "pre-wait repair is best-effort and cannot be the only pass")
    tasks = None
    for play in yaml.safe_load(src):
        for key in ("tasks", "post_tasks"):
            for t in play.get(key) or []:
                if TOOL in str(t.get("ansible.builtin.command", "")):
                    tasks = t
    assert tasks is not None, "main.yml's reconciler task could not be parsed"
    fw = tasks.get("failed_when")
    assert fw is not None and fw is not False, (
        "main.yml's reconciler is back to `failed_when: false`, which reports "
        "failed=0 over exactly the condition it exists to end: a container "
        "still serving config that was replaced under it")


def test_the_repair_is_not_gated_on_a_fact_its_tags_cannot_set():
    """`nos_docker_ready` is set by a probe in tasks/iiab/docker-prereqs.yml,
    imported under tags ['iiab','docker','stacks']. A run selecting any other
    tag never sets it — so `| default(false)` is not caution, it is a silent
    no-op, and ansible.cfg's `display_skipped_hosts = false` means a task
    skipped on every host prints NO BANNER AT ALL.

    That is how the first version of this repair ran a full converge doing
    nothing and produced a log indistinguishable from one where it worked. The
    end-of-run reconciler carried the same defect while being tagged `always`
    specifically so it could not be skipped.

    Assuming docker is present is the safe direction: the tool answers
    `UNKNOWN — could not read docker` and exits 0 when it is not there.
    """
    offenders = []
    for path in (WAIT, MAIN):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "nos_docker_ready" in line and "default(false)" in line:
                offenders.append(f"  {path.relative_to(REPO)}:{n}  {line.strip()}")
    assert not offenders, (
        "a docker-gated task defaults nos_docker_ready to false. The fact is "
        "unset on any run that does not carry the iiab/docker/stacks tags, so "
        "this skips silently rather than degrading honestly:\n"
        + "\n".join(offenders))


def test_skipped_tasks_are_invisible_here_which_is_why_the_rule_above_exists():
    """Positive control. If display_skipped_hosts ever becomes true, a silent
    skip stops being silent and the rule above is merely tidy rather than
    load-bearing — but the gate should then be re-argued, not quietly kept."""
    cfg = (REPO / "ansible.cfg").read_text(encoding="utf-8")
    assert "display_skipped_hosts = false" in cfg, (
        "ansible.cfg no longer hides skipped tasks. Re-read "
        "test_the_repair_is_not_gated_on_a_fact_its_tags_cannot_set — its "
        "premise has changed")
