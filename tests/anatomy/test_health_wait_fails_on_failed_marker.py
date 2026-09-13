"""The STRICT health-wait must fail on FAILED/UNKNOWN, not wait them out.

WHY. `stack-health-probe.py` used to print `0/0 ready (no containers — stack
empty)` and mark ALL_READY whenever docker ps was empty. Hidden fee 08: Linux
CI's `docker compose up infra` returned rc=1 (no rendered compose file) and
the wait still passed. The probe now distinguishes empty-by-config /
bring-up-failed / UNKNOWN, but `health-tick.yml` only short-circuited on
ALL_READY — FAILED and UNKNOWN kept polling until `stack_up_wait_timeout`
and only then failed. That is not a silent green, but it is the same class:
the wait does not *read the marker that already says this will not recover*.

WHAT IS PINNED. The tick file contains a real `ansible.builtin.fail` that
fires when the probe's last stdout line is FAILED or UNKNOWN, after the
tick records state and before the settle sleep. PENDING still polls.
ALL_READY still short-circuits via `_wait_done`. No Docker, no network —
YAML structure only.

The complementary layer (core-up fail-fast on a non-zero `up`) is
`test_core_up_fails_fast_on_bring_up.py`. This gate is the wait half.
"""
from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TICK = REPO / "tasks" / "stacks" / "health-tick.yml"


def _tasks() -> list:
    data = yaml.safe_load(TICK.read_text(encoding="utf-8"))
    assert isinstance(data, list), f"{TICK} did not parse to a task list"
    return data


def _name(task: dict) -> str:
    return str(task.get("name", ""))


def _flatten_when(when) -> str:
    if when is None:
        return ""
    if isinstance(when, list):
        return " && ".join(str(w) for w in when)
    return str(when)


def _indices() -> dict:
    idx = {}
    for i, t in enumerate(_tasks()):
        if not isinstance(t, dict):
            continue
        n = _name(t)
        if "Record health-wait state" in n:
            idx["record"] = i
        elif "Abort health-wait on FAILED/UNKNOWN" in n:
            idx["abort"] = i
        elif n.startswith("[Stacks] Settle"):
            idx["sleep"] = i
    return idx


def test_abort_task_is_present_and_is_a_fail():
    idx = _indices()
    assert "abort" in idx, (
        "health-tick.yml must abort the wait when the probe marker is "
        "FAILED or UNKNOWN — otherwise empty-stack-as-green / missing "
        "compose burns the full budget (docs/hidden_fees/08)"
    )
    t = _tasks()[idx["abort"]]
    assert "ansible.builtin.fail" in t or "fail" in t, (
        f"abort task must be ansible.builtin.fail, got keys: {list(t.keys())}"
    )


def test_abort_runs_after_record_and_before_sleep():
    idx = _indices()
    missing = [k for k in ("record", "abort", "sleep") if k not in idx]
    assert not missing, f"health-tick.yml missing task(s): {missing}"
    assert idx["record"] < idx["abort"] < idx["sleep"], (
        "order must be record marker -> abort on FAILED/UNKNOWN -> sleep, "
        f"got {idx}"
    )


def test_abort_when_keys_off_failed_and_unknown_markers():
    idx = _indices()
    when = _flatten_when(_tasks()[idx["abort"]].get("when"))
    assert "FAILED" in when and "UNKNOWN" in when, (
        f"abort `when:` must key off the FAILED and UNKNOWN markers, got: {when!r}"
    )
    assert "_wait_done" in when, (
        f"abort must stay silent after ALL_READY (_wait_done), got: {when!r}"
    )
    assert "last" in when, (
        f"abort must read the probe's last stdout line (the marker), got: {when!r}"
    )
