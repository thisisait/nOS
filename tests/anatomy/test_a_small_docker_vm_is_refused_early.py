"""Anatomy CI gate — a Docker VM too small for the estate is refused before any stack.

MEASURED 2026-10-10: the all-on estate (65 containers, 7.7 GiB resident) on a
10 GB Docker Desktop VM ran the VM at 600-800 % CPU; KEAP answered /api/health
in 2-20 s and two converges died an hour in, on a 30 s uri timeout in an
unrelated KEAP task. At 11.5 GB (MemTotal 11.17 GiB) the same run was failed=0.
Nothing said "the VM is too small"; the failure named a table.

Pinned: the readiness probe reads MemTotal; main.yml refuses below the declared
minimum, next to the no-Docker refusal and with the same tags; the minimum is
declared once in default.config.yml and the message names both numbers.
"""

from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402
MAIN = REPO / "main.yml"
PREREQS = REPO / "tasks" / "iiab" / "docker-prereqs.yml"
VAR = "docker_min_memory_gib"
FACT = "nos_docker_memory_gib"


def _main_tasks() -> list[dict]:
    out = []
    for play in yaml.safe_load(MAIN.read_text(encoding="utf-8")):
        for key in ("pre_tasks", "tasks", "post_tasks"):
            out.extend(play.get(key) or [])
    return out


def _mod(t: dict, name: str):
    return t.get(name, t.get(f"ansible.builtin.{name}"))


def _refusal() -> dict | None:
    return next((t for t in _main_tasks()
                 if _mod(t, "fail") and VAR in str(t.get("when", ""))), None)


def test_the_probe_records_the_vm_memory():
    tasks = yaml.safe_load(PREREQS.read_text(encoding="utf-8"))
    facts = [_mod(t, "set_fact") for t in tasks
             if FACT in str(_mod(t, "set_fact") or "")]
    assert facts, (
        f"docker-prereqs.yml no longer sets {FACT}. Without it the playbook "
        "cannot tell a 10 GB VM from a 12 GB one and fails an hour later on "
        "whatever task first times out")
    assert "MemTotal" in str(facts[0][FACT]), (
        f"{FACT} is not read from `docker info` MemTotal, the number Docker "
        "itself reports for the VM")


def test_the_playbook_refuses_a_vm_below_the_minimum():
    t = _refusal()
    assert t is not None, (
        f"main.yml has no refusal keyed on {VAR}; a small VM converges for an "
        "hour and dies on an unrelated timeout (measured 2026-10-10)")
    when = str(t["when"])
    assert FACT in when, f"the refusal does not compare {FACT}"
    msg = str(_mod(t, "fail").get("msg", ""))
    assert FACT in msg and VAR in msg, (
        "the refusal must print the measured size AND the minimum, so the "
        "operator knows what to set in Docker Desktop")


def test_the_refusal_has_the_no_docker_refusals_tags():
    t = _refusal()
    sibling = next(t for t in _main_tasks()
                   if _mod(t, "fail") and "nos_docker_ready" in str(t.get("when", ""))
                   and VAR not in str(t.get("when", "")))
    assert set(t.get("tags") or []) == set(sibling.get("tags") or []), (
        "the memory refusal must fire on exactly the runs the no-Docker "
        "refusal fires on; tag filtering decides both")


def test_the_minimum_is_declared_once_with_its_measurement():
    text = ni.default_config_text()
    m = re.search(rf"^{VAR}:\s*(\d+)", text, re.M)
    assert m, f"{VAR} is not declared in default.config.yml"
    assert int(m.group(1)) >= 11, (
        f"{VAR} is {m.group(1)}; 10 GB (MemTotal ~9.7 GiB) was measured too "
        "small for the all-on estate on 2026-10-10")
