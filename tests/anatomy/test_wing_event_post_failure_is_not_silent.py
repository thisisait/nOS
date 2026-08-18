"""Anatomy CI gate — a pulse agent run whose audit events never landed must
not exit 0, and the WARN it prints must be a status, not stderr debris
(2026-08-18).

WHY THIS EXISTS
---------------
The 2026-08-17 surveyor run completed its ceremony ($0.96, a full report),
exited 0 — and left ZERO events in wing.db. Both HMAC event POSTs had died at
curl exit 3 (URL glob parse: `-w` never printed), so the runner's
`tail -n 1` "HTTP code" was the caret line of curl's own stderr:

    WARN: Wing event POST returned HTTP                   ^

Two defects, one rule (docs/hidden_fees/07 + agent-run-lock.sh's own words:
"a run that could not do its job must not report success"):

  1. The runner's declared job includes POSTing agent_run_start/end. When it
     cannot, it must exit 2 (its own contract: 2 = Wing error) — otherwise a
     ceremony that cost real dollars is invisible to the audit surface and
     the estate reads as quiet.
  2. An error message must report what happened, not parade unparsed stderr
     as an HTTP status the operator will try to look up.

This gate is FUNCTIONAL: it runs the real script with a stubbed PATH (curl
that grants the Authentik token but kills every events POST the way the
incident did; claude that returns a canned envelope) and asserts on the
process exit code — the success marker is written by this reader, not by the
attempting code.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "files" / "anatomy" / "scripts" / "pulse-run-agent.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None or shutil.which("openssl") is None,
    reason="functional harness needs jq + openssl on PATH",
)

CURL_STUB_EVENTS_DEAD = """#!/bin/bash
# Stub curl: token exchange succeeds; every Wing events POST dies the way the
# 2026-08-17 incident did — curl exit 3 before any request, no -w output,
# stderr ending in a caret line.
args="$*"
case "$args" in
  */application/o/token/*)
    printf '{"access_token":"stub-token"}\\n200\\n'
    exit 0 ;;
  */api/v1/events*)
    printf 'curl: (3) bad range in URL position 22:\\nhttp://[::1]:9000/api/v1/events\\n      ^\\n' >&2
    exit 3 ;;
  *)
    printf '000'
    exit 7 ;;
esac
"""

CURL_STUB_ALL_OK = """#!/bin/bash
args="$*"
case "$args" in
  */application/o/token/*)
    printf '{"access_token":"stub-token"}\\n200\\n'
    exit 0 ;;
  */api/v1/events*)
    printf '{"ok":true}\\n201\\n'
    exit 0 ;;
  *)
    printf '201'
    exit 0 ;;
esac
"""

CLAUDE_STUB = """#!/bin/bash
printf '{"result":"stub ceremony report","usage":{"input_tokens":10,"output_tokens":20,"cache_read_input_tokens":0},"total_cost_usd":0.01}'
"""


def _run(tmp_path: Path, curl_stub: str) -> subprocess.CompletedProcess:
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    for name, body in (("curl", curl_stub), ("claude", CLAUDE_STUB)):
        p = stub_bin / name
        p.write_text(body)
        p.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{stub_bin}:{env['PATH']}",
            "NOS_AUTHENTIK_URL": "http://auth.stub.local",
            "NOS_AGENT_NAME": "gate-stub",
            "NOS_AGENT_CLIENT_SECRET": "stub-secret",
            "NOS_AGENT_TASK": "say nothing",
            "WING_API_URL": "http://127.0.0.1:9",  # never contacted: curl is stubbed
            "WING_API_TOKEN": "stub",
            "WING_EVENTS_HMAC_SECRET": "stub",
            "NOS_AGENT_LOCK_DIR": str(tmp_path / "agent.lock"),
        }
    )
    env.pop("NOS_AGENT_PROFILE", None)
    env.pop("ANTHROPIC_BASE_URL", None)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_dead_audit_posts_escalate_a_clean_run_to_exit_2(tmp_path):
    res = _run(tmp_path, CURL_STUB_EVENTS_DEAD)
    assert res.returncode == 2, (
        "ceremony succeeded but both audit POSTs died — the runner must exit 2 "
        f"(Wing error), got {res.returncode}\nstderr:\n{res.stderr}"
    )
    assert "invisible to the audit surface" in res.stderr


def test_the_warn_reports_curl_not_stderr_debris(tmp_path):
    res = _run(tmp_path, CURL_STUB_EVENTS_DEAD)
    # The incident line: "returned HTTP" followed by caret debris. The fixed
    # runner must name curl's exit instead of presenting stderr as a status.
    for line in res.stderr.splitlines():
        if "Wing event POST returned HTTP" in line:
            code = line.rsplit("HTTP", 1)[1].strip()
            assert code.isdigit() and len(code) == 3, (
                f"WARN presented non-status text as an HTTP code: {line!r}"
            )
    assert "curl exit 3" in res.stderr


def test_a_clean_run_with_landed_events_still_exits_0(tmp_path):
    res = _run(tmp_path, CURL_STUB_ALL_OK)
    assert res.returncode == 0, (
        f"regression: healthy path no longer exits 0 (got {res.returncode})\n"
        f"stderr:\n{res.stderr}"
    )
    assert "invisible to the audit surface" not in res.stderr
