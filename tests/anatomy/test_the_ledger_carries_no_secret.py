"""What the telemetry callback hands the audit ledger holds no secret, in the shapes that leaked.

MEASURED 2026-10-25 on the live events table (counts only, row pulse-redact-gaps): a
Wing bearer in results[].invocation.module_args.headers.Authorization (98 copies),
ansible_facts.backup_encryption_passphrase (42 rows), Authentik session cookies and
a JWT in a url (3). `no_log` is the control (test_a_secret_bearing_task_is_no_log);
this is the second net, for the task nobody marked. Values are fake.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("wing_telemetry_ns", REPO / "callback_plugins/wing_telemetry.py")
wt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wt)

BEARER = "f" * 64
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmYWtlIn0.ZmFrZXNpZ25hdHVyZQ"
PASS = "a" * 64


def _ledger(result: dict) -> str:
    return json.dumps(wt.bound_result(result))


def test_a_loop_items_header_never_reaches_the_ledger():
    row = _ledger({"results": [{"item": "x", "status": 200, "invocation": {"module_args": {
        "url": "http://127.0.0.1:9000/api/v1/pulse_jobs/x", "headers": {"Authorization": f"Bearer {BEARER}"}}}}]})
    assert BEARER not in row, row
    assert "results[].invocation" in row, "the omission is named in the row"


def test_a_secret_fact_never_reaches_the_ledger():
    row = _ledger({"ansible_facts": {"backup_encryption_passphrase": PASS, "keep_me": "visible"}})
    assert PASS not in row and "visible" in row, row


def test_cookies_and_a_jwt_never_reach_the_ledger():
    row = _ledger({"results": [{"cookies": {"authentik_session": JWT}, "cookies_string": f"authentik_session={JWT}",
                                "url": f"http://x/flow?token={JWT}", "status": 200}]})
    assert JWT not in row, row


def test_a_bare_header_value_is_scrubbed():
    assert BEARER not in wt.scrub({"msg": f"sent Bearer {BEARER} to wing"})["msg"]
    assert wt.scrub({"msg": "digest sha256:" + "0" * 64})["msg"].endswith("0" * 64), "a digest stays visible"
