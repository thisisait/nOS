"""The runner's token ledger must account for the money it records.

WHAT WAS MEASURED (2026-08-25, upgrade-architect run 8c52551a). The run-end
event carried in=29 out=27110 cache_read=1179022 cost=$2.317929. Priced at
the backend's own rates those three counters explain $1.27 — the other $1.05
was ~168K cache-CREATION tokens the extraction dropped on the floor. The
runner's own comment promises "the tokens survive either way, so a future
rate table can price them honestly"; without cache_creation_input_tokens
that promise covered 55% of the bill.

WHAT IS PINNED. The usage extraction in pulse-run-agent.sh is executed HERE,
verbatim as it appears in the script (parsed out, not re-typed — a copy in
the test would drift), against a fixture claude JSON envelope: five fields,
in order, cache_write included. And the agent_run_end event body carries
tokens_cache_write, so wing.db's WORM ledger holds the whole bill.

PROVEN IN THE BROKEN DIRECTION against the pre-change script: the extracted
snippet printed four fields and the event body had no tokens_cache_write —
both asserts here failed.

WHAT IT CANNOT SEE. Whether claude's envelope ever renames the field, and
whether any surface reads the new number.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

RUNNER = pathlib.Path(__file__).resolve().parents[2] / \
    "files/anatomy/scripts/pulse-run-agent.sh"

FIXTURE = json.dumps({
    "result": "## Upgrade architect report\nNOS_AGENT_EXIT: 1",
    "usage": {
        "input_tokens": 29,
        "output_tokens": 27110,
        "cache_read_input_tokens": 1179022,
        "cache_creation_input_tokens": 168068,
    },
    "total_cost_usd": 2.317929,
})


def _usage_snippet() -> str:
    """The exact python3 -c body the runner feeds CLAUDE_JSON into — the one
    that follows the TOK_IN read. Parsed from the artifact so this gate tests
    what ships, not a copy of it."""
    src = RUNNER.read_text(encoding="utf-8")
    read_line = src[src.index("read -r TOK_IN"):]
    m = re.search(r"python3 -c '(.*?)'\s*2>/dev/null\)", read_line, re.S)
    assert m, "could not locate the usage-extraction python snippet in the runner"
    return m.group(1)


def test_the_extraction_yields_all_five_counters():
    out = subprocess.run(
        [sys.executable, "-c", _usage_snippet()],
        input=FIXTURE, capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, out.stderr
    fields = out.stdout.split()
    assert fields == ["29", "27110", "1179022", "168068", "2.317929"], (
        "expected in/out/cache_read/cache_write/cost in order; got "
        f"{fields} — a dropped counter is money the ledger cannot price")


def test_a_partial_usage_never_shifts_the_cost():
    """The regression the runner-attribution gate caught on first contact: a
    usage object WITHOUT cache_creation_input_tokens printed an empty middle
    field, `read` collapsed it under IFS, and the dollar figure landed in the
    cache-write slot (cost recorded null). Counters must default to 0 so
    every later field keeps its position."""
    partial = json.dumps({"result": "ok", "usage": {
        "input_tokens": 11, "output_tokens": 7, "cache_read_input_tokens": 3,
    }, "total_cost_usd": 0.0123})
    out = subprocess.run(
        [sys.executable, "-c", _usage_snippet()],
        input=partial, capture_output=True, text=True, timeout=60,
    )
    assert out.stdout.split() == ["11", "7", "3", "0", "0.0123"], (
        f"got {out.stdout.split()} — a collapsed empty field shifts the cost "
        "one slot left and the ledger records null for a priced run")


def test_a_usage_free_envelope_stays_empty_not_fatal():
    out = subprocess.run(
        [sys.executable, "-c", _usage_snippet()],
        input="not json at all", capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, "a parse failure must yield empties, not a crash"
    assert out.stdout.split() == [], out.stdout


def test_the_run_end_event_carries_cache_writes():
    src = RUNNER.read_text(encoding="utf-8")
    assert "tokens_cache_write:$t_cache_w" in src, (
        "agent_run_end no longer carries tokens_cache_write — the WORM ledger "
        "is back to pricing 55% of the bill")
    assert '--argjson t_cache_w "${TOK_CACHE_W:-0}"' in src, (
        "t_cache_w is not bound from the extraction — the event would carry "
        "a literal or nothing")
