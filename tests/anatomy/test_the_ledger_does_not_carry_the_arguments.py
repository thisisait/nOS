"""A task result reaching the ledger is bounded, and says so when it was.

MEASURED 2026-08-29 with `tools/wing-status.py`, on this estate's own wing.db:

    events        380 248 rows        1.19 GB — 97% of the whole organ
    result_json   921 MB of that      `task_ok` alone is 657 MB
    single rows   up to 4.1 MB        pazny.state_manager introspection
    biggest key   `invocation`        Ansible echoing back the module's ARGUMENTS

Nothing reads a task's `result_json`. The only consumers in the tree are agent
reports, migration payloads and DSAR records. So the shared vein between
Ansible, Bone, Wing, Grafana and the face was carrying most of a gigabyte that
no organ downstream has ever looked at — which is what made every query against
`events` slow and the organ, in the operator's words, hard to get hold of.

`bound_result` drops `invocation` unconditionally and then caps what remains.
On 20 000 real rows the two biggest event types went from 230 MB to 25 MB.

THE HALF THAT MATTERS MORE THAN THE SAVING. A record that quietly lost its
`stdout` is this estate's signature defect wearing a smaller hat: the reader
cannot tell a task that printed nothing from a task whose output was thrown
away. So every omission is named in the row itself, and the tests below spend
more effort on that than on the bytes.

Retro-verified 2026-08-29: each assertion was confirmed to fail with the rule
it pins removed.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGIN = REPO / "callback_plugins/wing_telemetry.py"

_spec = importlib.util.spec_from_file_location("wing_telemetry", PLUGIN)
wt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wt)


def test_invocation_never_reaches_the_ledger() -> None:
    """The input, filed as though it were the outcome — and the single largest
    key by total bytes across 380k rows."""
    got = wt.bound_result({"changed": False, "invocation": {"module_args": {"x": 1}}})
    assert "invocation" not in got
    assert got["_omitted"]["keys"] == ["invocation"]


def test_a_small_result_is_untouched_apart_from_that() -> None:
    """The cap must not be a rewrite. An ordinary result has to arrive whole,
    or the ledger stops being an audit record to buy disk."""
    got = wt.bound_result({"changed": True, "stdout": "ok", "rc": 0})
    assert got == {"changed": True, "stdout": "ok", "rc": 0}


def test_an_oversized_result_is_cut_and_says_what_it_lost() -> None:
    big = {"changed": False, "rc": 0, "files": ["f" * 100] * 400}
    got = wt.bound_result(big, cap=2048)
    assert len(json.dumps(got)) <= 2048 + 200, "the cap did not hold"
    assert "files" in got["_omitted"]["keys"], (
        "the biggest key was dropped and the row does not name it — a reader "
        "cannot tell this from a task that found no files")
    assert got["_omitted"]["bytes"] > 10000 and got["_omitted"]["cap"] == 2048


def test_the_small_keys_survive_the_cut() -> None:
    """Dropping largest-first is the point: `rc` and `changed` are what anyone
    diagnosing a run actually reads, and they cost nothing."""
    got = wt.bound_result({"changed": True, "rc": 7, "stdout": "s" * 40000},
                          cap=1024)
    assert got["rc"] == 7 and got["changed"] is True


def test_redaction_still_happens_first() -> None:
    """`bound_result` replaced `scrub` at three call sites. If it stopped
    scrubbing, a bounded result would be a leaked one."""
    got = wt.bound_result({"api_token": "hunter2", "msg": "ok"})
    assert got["api_token"] == "***"


def test_a_secret_cannot_hide_in_a_dropped_key() -> None:
    """Order matters and is easy to get backwards: bounding before scrubbing
    would put unredacted bytes in the size calculation and — worse — leave the
    surviving keys unscrubbed."""
    got = wt.bound_result({"password": "p", "big": "x" * 40000, "msg": "m"},
                          cap=512)
    assert got["password"] == "***"


def test_every_task_hook_routes_through_it() -> None:
    """ok / changed / failed / unreachable all emit a module result. A hook
    left on the old path would keep writing megabytes and nothing would say so."""
    src = PLUGIN.read_text(encoding="utf-8")
    assert src.count("result=bound_result(res_dict)") == 3, (
        "a task hook emits `scrub(res_dict)` directly again")
    assert "result=scrub(res_dict)" not in src


def test_a_non_dict_result_is_passed_through() -> None:
    """Ansible results are dicts, but the plugin must not crash a converge on
    the day one is not."""
    assert wt.bound_result("plain") == "plain"
    assert wt.bound_result(None) is None
