"""The playbook_end recap counts failures, read from real Ansible stats.

AggregateStats.summarize() returns `failures`, not `failed`; the callback
read `failed` and reported 0 for every failed run, so the playbook-end
notify hook titled a failed leave "done" (2026-09-30).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from ansible.executor.stats import AggregateStats

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("wing_telemetry", REPO / "callback_plugins/wing_telemetry.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_a_failed_host_is_counted() -> None:
    st = AggregateStats()
    for _ in range(3):
        st.increment("ok", "127.0.0.1")
    st.increment("failures", "127.0.0.1")
    st.increment("changed", "127.0.0.1")
    recap = mod.recap_from_stats(st)
    assert recap["failed"] == 1 and recap["ok"] == 3 and recap["changed"] == 1, recap


def test_a_clean_run_reports_zero() -> None:
    st = AggregateStats()
    st.increment("ok", "127.0.0.1")
    assert mod.recap_from_stats(st)["failed"] == 0


def test_a_leave_is_recognised_from_the_cli_extra_vars() -> None:
    assert mod.leaving_estate(["remove=all", "confirm=true", "leave=true"]) is True
    assert mod.leaving_estate(['{"remove": "all", "leave": true}']) is True
    assert mod.leaving_estate(["remove=all"]) is False, "remove=all without leave reinstalls"
    assert mod.leaving_estate(["remove=data", "leave=true"]) is False
    assert mod.leaving_estate(["@profiles/all-on.yml"]) is False


def test_a_leave_writes_nothing_under_the_home_it_removes(tmp_path, monkeypatch) -> None:
    """Build the callback as Ansible would, with a leave's extra vars, and fire
    the lifecycle event: the JSONL must not appear, telemetry must not start."""
    from ansible import context
    from ansible.module_utils.common.collections import ImmutableDict
    monkeypatch.setattr(context, "CLIARGS", ImmutableDict(extra_vars=("remove=all", "leave=true")))
    jsonl = tmp_path / ".nos/events/playbook.jsonl"
    monkeypatch.setenv("NOS_PLAYBOOK_JSONL_PATH", str(jsonl))
    monkeypatch.setenv("WING_EVENTS_SQLITE_FALLBACK", str(tmp_path / ".nos/events-fallback.db"))
    cb = mod.CallbackModule()
    cb._finalize_activation({"wing_telemetry_enabled": True})
    cb._publish_lifecycle("playbook_start", {"type": "playbook_start"})
    assert not (tmp_path / ".nos").exists() and cb._active is False
