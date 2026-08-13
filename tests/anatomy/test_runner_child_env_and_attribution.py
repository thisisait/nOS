"""What the spawned `claude` inherits, and what the run-end event records.

TWO MEASUREMENTS, 2026-08-13, both against the live estate's runner path.

1. THE CHILD HELD THE KEY THAT MINTS ITS OWN IDENTITY. `pulse-run-agent.sh`
   exchanges `NOS_AGENT_CLIENT_SECRET` for a scoped Authentik token BEFORE
   spawning claude, and passes the token — but the secret itself rode along in
   the inherited env, into a process running `--permission-mode
   bypassPermissions` with no `--allowedTools` anywhere in the repo
   (docs/minimax-groundwork.md, "what must happen before arming" item 3).
   The same doc claims `WING_EVENTS_HMAC_SECRET` is equally withholdable, and
   that half is FALSE today, measured: the conductor profile
   (files/anatomy/agents/conductor.yml:43) instructs the ceremony to POST its
   own events, Bone's /api/v1/events accepts only HMAC, and the live
   conductor_report row of 2026-08-09T04:04:25Z sits between agent_run_start
   (04:01:16) and agent_run_end (04:04:57) — the CHILD signed it. So this gate
   pins the asymmetry deliberately: client secret withheld, HMAC secret
   still present until the events POST accepts the child's bearer.

2. NOTHING RECORDED WHICH MODEL SERVED A RUN. `agent_sessions.model_uri` is
   the sentinel `cli:unrecorded` by design (the shell bridge did not report
   what NOS_AGENT_MODEL pinned), and ruling 3 in docs/minimax-groundwork.md
   requires the effective backend and model stamped into the run-end event —
   the events table is WORM hash-chained, so a label wrong at write time is
   wrong forever, and there is no relabelling later.

HOW THIS MEASURES: the real script runs end to end with a fake `claude` (dumps
its env, answers a canned JSON envelope) and a fake `curl` (answers the token
exchange, captures every Wing event body). No live estate, no network, no real
secret. What is asserted is the EFFECT — the env the child observed, the JSON
the event carried — not the script's text.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "files/anatomy/scripts/pulse-run-agent.sh"

_FAKE_CLAUDE = """#!/usr/bin/env bash
env > "$NOS_PROBE_DIR/claude-env"
printf '%s\\n' "$@" > "$NOS_PROBE_DIR/claude-args"
printf '%s' '{"result":"probe ran clean","usage":{"input_tokens":11,"output_tokens":7,"cache_read_input_tokens":3},"total_cost_usd":0.0123}'
"""

_FAKE_CURL = """#!/usr/bin/env bash
# Answers the two shapes pulse-run-agent.sh sends:
#   token exchange  -> a JSON access_token + HTTP 200
#   Wing event POST -> capture the -d body, answer 201
body=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -d) body="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
case "$url" in
  */token/*) printf '{"access_token":"fake-authentik-token"}\\n200\\n' ;;
  */events*) printf '%s\\n' "$body" >> "$NOS_PROBE_DIR/event-bodies.jsonl"
             printf 'ok\\n201\\n' ;;
  *) printf '201\\n' ;;
esac
"""


@pytest.fixture()
def harness(tmp_path):
    if shutil.which("jq") is None:  # the script itself requires jq
        pytest.skip("jq not installed — the runner cannot execute at all here")
    probe = tmp_path / "probe"
    probe.mkdir()
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    for name, src in (("claude", _FAKE_CLAUDE), ("curl", _FAKE_CURL)):
        p = fakes / name
        p.write_text(src)
        p.chmod(p.stat().st_mode | stat.S_IXUSR)

    def run(extra_env: dict[str, str]) -> subprocess.CompletedProcess:
        env = {
            "PATH": f"{fakes}:{os.environ['PATH']}",
            "HOME": os.environ.get("HOME", str(tmp_path)),
            "NOS_PROBE_DIR": str(probe),
            "NOS_AGENT_LOCK_DIR": str(tmp_path / "lock"),
            "NOS_AUTHENTIK_URL": "http://127.0.0.1:1",  # fake curl answers it
            "NOS_AGENT_NAME": "probe-agent",
            "NOS_AGENT_CLIENT_SECRET": "fake-client-secret-runner-only",
            "WING_API_TOKEN": "fake-wing-bearer-for-the-child",
            "WING_EVENTS_HMAC_SECRET": "fake-hmac-conductor-still-needs",
            "NOS_AGENT_TASK": "probe task",
            "PULSE_RUN_ID": "probe-run-1",
        }
        env.update(extra_env)
        return subprocess.run(
            ["bash", str(SCRIPT)], env=env, capture_output=True, text=True,
            timeout=60,
        )

    return run, probe


def _run_end(probe: Path) -> dict:
    rows = [
        json.loads(line)
        for line in (probe / "event-bodies.jsonl").read_text().splitlines()
    ]
    ends = [r for r in rows if r.get("type") == "agent_run_end"]
    assert ends, f"no agent_run_end was posted; got types {[r.get('type') for r in rows]}"
    return ends[-1]


def test_the_client_secret_stays_with_the_runner(harness):
    run, probe = harness
    proc = run({"NOS_AGENT_MODEL": "haiku"})
    assert proc.returncode == 0, f"runner failed:\n{proc.stderr[-800:]}"

    child_env = (probe / "claude-env").read_text()
    assert "NOS_AGENT_CLIENT_SECRET" not in child_env, (
        "the Authentik client secret reached the spawned claude. The runner "
        "already exchanged it for a scoped token before the spawn — the child "
        "needs the token, never the secret that mints the agent's identity "
        "(and the child runs bypassPermissions with no --allowedTools)."
    )
    assert "fake-client-secret-runner-only" not in child_env, (
        "the client secret VALUE leaked into the child env under another name"
    )
    # Positive controls: what the child legitimately needs did arrive.
    assert "WING_API_TOKEN=fake-wing-bearer-for-the-child" in child_env
    assert "NOS_AUTHENTIK_TOKEN=fake-authentik-token" in child_env
    # Deliberate, and documented in the module docstring: the HMAC secret
    # still flows, because the conductor ceremony signs its own event POSTs
    # with it (Bone /api/v1/events is HMAC-only). When the events POST learns
    # bearer auth, flip this assertion to `not in` and move the secret into
    # the withheld set in pulse-run-agent.sh.
    assert "WING_EVENTS_HMAC_SECRET" in child_env


def test_the_run_end_event_records_model_and_backend(harness):
    run, probe = harness
    proc = run({"NOS_AGENT_MODEL": "haiku"})
    assert proc.returncode == 0, f"runner failed:\n{proc.stderr[-800:]}"
    result = _run_end(probe)["result"]
    assert result["model"] == "haiku", (
        f"run-end recorded model {result.get('model')!r}, not the tier "
        "NOS_AGENT_MODEL pinned. agent_sessions.model_uri is 'cli:unrecorded' "
        "by design, so this field is the ONLY record of what served the run — "
        "and the events table is WORM: wrong at write time is wrong forever."
    )
    assert result["backend"] == "anthropic"
    assert result["cost_usd"] == 0.0123  # priced against the right table


def test_a_foreign_backend_is_stamped_not_assumed(harness):
    """The armed-MiniMax shape, simulated without arming anything."""
    run, probe = harness
    proc = run({
        "ANTHROPIC_BASE_URL": "https://api.minimax.example/anthropic",
        "ANTHROPIC_MODEL": "MiniMax-M2",
    })
    assert proc.returncode == 0, f"runner failed:\n{proc.stderr[-800:]}"
    result = _run_end(probe)["result"]
    assert result["backend"] == "api.minimax.example"
    assert result["model"] == "MiniMax-M2", (
        "with no --model flag, ANTHROPIC_MODEL is what drives the CLI "
        "(ruling 3) — the stamp must follow the same precedence the CLI does"
    )
    assert result["cost_basis"] == "foreign:api.minimax.example"
    assert result["cost_usd"] is None, (
        "the CLI's dollar figure is priced against Anthropic's table; on a "
        "foreign backend it must be dropped, not recorded as fact"
    )
