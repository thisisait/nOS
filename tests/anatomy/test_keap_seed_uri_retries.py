"""Every KEAP DataTable seed call survives a slow KEAP.

2026-10-10: a starved Docker VM made KEAP answer in 2-20 s and two converges died
on '[pazny.keap] Reconcile DataTable' — one uri, 30 s default timeout, no retries.
Each uri task must retry (>=3, with a delay, until a real status), and a POST may
only retry when repeating it is safe — listed below with the reason.
"""
from __future__ import annotations

from pathlib import Path

import yaml

SEEDER = Path(__file__).resolve().parents[2] / "roles" / "pazny.keap" / "tasks" / "seed-face-table.yml"

# A repeated POST must not duplicate anything. Both agent-door POSTs are keyed on slug.
SAFE_POSTS = {
    "Reconcile DataTable": "re-POST of a table reconciles its columns in place (KEAP additive reconcile)",
    "Retry DataTable": "same reconcile, without `view`",
    "Upsert MISSING system rows": "agent-door row POST upserts on slug, and the rows GET guards it",
}


def _uri_tasks():
    tasks = yaml.safe_load(SEEDER.read_text(encoding="utf-8"))
    return [t for t in tasks if "ansible.builtin.uri" in t]


def test_seeder_has_uri_tasks():
    assert len(_uri_tasks()) >= 5


def test_every_uri_task_retries_until_a_status():
    bad = []
    for t in _uri_tasks():
        reg, until = t.get("register", ""), str(t.get("until", ""))
        if not (int(t.get("retries", 0)) >= 3 and int(t.get("delay", 0)) > 0
                and reg and f"{reg}.status" in until):
            bad.append(t["name"])
    assert not bad, f"uri tasks without retries/delay/until-on-status: {bad}"


def test_a_retried_post_is_declared_safe_to_repeat():
    bad = [t["name"] for t in _uri_tasks()
           if str(t["ansible.builtin.uri"].get("method", "GET")).upper() != "GET"
           and not any(k in t["name"] for k in SAFE_POSTS)]
    assert not bad, f"non-GET uri tasks not declared safe to repeat: {bad}"
