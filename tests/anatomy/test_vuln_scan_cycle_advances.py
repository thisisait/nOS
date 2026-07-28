"""Anatomy gate: the vulnerability scan's cycle counter must actually advance.

`files/vuln-scan/scan-runner.sh` rotates the nightly attack probe with

    PROBE_INDEX=$((SCAN_CYCLE % 8))

so `scan_cycle` is not a statistic — it is the only thing that decides which of
the eight probes runs tonight. The counter is advanced by exactly one jq call,
and that call carried a precedence bug:

    .scan_cycle += 1 | .last_full_scan = now | todate      # WRONG

`|` is jq's pipe. This assigns the epoch to `.last_full_scan` and then pipes the
whole OBJECT into `todate`, which dies with *"strftime/1 requires parsed datetime
inputs"*. `> "$TMP" && mv` then never ran the mv, so the write silently did not
happen. `scan_cycle` froze at 16, `16 % 8 == 0`, and
`unauthenticated_endpoint_scan` ran every night while the other seven probes —
default credentials, SSRF, docker escape, TLS weakness, resource exhaustion,
version leakage, supply-chain freshness — had not run since the freeze.

Nothing surfaced it. The script exits 0, Pulse recorded exit_code 0 every night,
and the message went to stderr where only `pulse_runs.stderr_tail` kept it. The
documented "drift baseline staleness" tech-debt item was this bug's shadow.

Found 2026-07-28 by reading a green run's stderr.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
RUNNER = REPO / "files" / "vuln-scan" / "scan-runner.sh"
STATE = REPO / "docs" / "llm" / "security" / "scan-state.json"


def test_probe_rotation_still_depends_on_the_counter() -> None:
    """If the probe stops being keyed on scan_cycle, this gate loses its teeth."""
    src = RUNNER.read_text()
    assert re.search(r"PROBE_INDEX=\$\(\(\s*SCAN_CYCLE\s*%", src), (
        "the attack probe is no longer selected by `scan_cycle % N`. Re-read this "
        "gate: a frozen counter may no longer mean a frozen probe rotation."
    )


def test_the_counter_update_parenthesises_now_todate() -> None:
    """The literal shape of the bug, pinned so it cannot come back by edit."""
    src = RUNNER.read_text()
    for ln, line in enumerate(src.splitlines(), 1):
        if "scan_cycle += 1" not in line:
            continue
        assert "now | todate" not in line or "(now | todate)" in line, (
            f"{RUNNER.relative_to(REPO)}:{ln} pipes the whole object into `todate`. "
            "Write `.last_full_scan = (now | todate)` — unparenthesised, jq assigns the "
            "epoch and then applies todate to the object, the write fails, and the "
            "attack-probe rotation freezes on whichever index the counter last held."
        )


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_the_update_expression_actually_runs_under_jq() -> None:
    """Run the real expression through the real jq — shape-matching is not proof."""
    src = RUNNER.read_text()
    m = re.search(r"jq '(\.scan_cycle \+= 1[^']*)'", src)
    assert m, "could not find the scan_cycle update expression to execute"
    proc = subprocess.run(
        ["jq", m.group(1)],
        input=json.dumps({"scan_cycle": 16, "last_full_scan": None}),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"the cycle-advance expression fails under jq: {proc.stderr.strip()}"
    )
    out = json.loads(proc.stdout)
    assert out["scan_cycle"] == 17, f"the counter did not advance: {out}"
    assert isinstance(out["last_full_scan"], str), (
        f"last_full_scan should be an ISO string after `todate`, got {out['last_full_scan']!r}"
    )


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_a_failed_update_is_reported_rather_than_swallowed() -> None:
    """`> tmp && mv` hid this for thirteen nights. The failure branch must log."""
    src = RUNNER.read_text()
    window = src[src.index("scan_cycle += 1") : src.index("scan_cycle += 1") + 600]
    assert "log " in window and "ERROR" in window, (
        "the scan_cycle update has no failure branch. A silent `&& mv` is exactly how a "
        "frozen probe rotation stayed invisible behind exit code 0 — if the write cannot "
        "happen, say so in the log."
    )


def test_every_probe_in_the_schedule_is_reachable() -> None:
    """`% 8` must match the schedule length, or the tail is unreachable by design."""
    src = RUNNER.read_text()
    m = re.search(r"PROBE_INDEX=\$\(\(\s*SCAN_CYCLE\s*%\s*(\d+)", src)
    assert m, "no probe modulus found"
    modulus = int(m.group(1))
    schedule = json.loads(STATE.read_text()).get("attack_probe_schedule", [])
    assert len(schedule) == modulus, (
        f"the probe schedule holds {len(schedule)} entries but rotation is modulo "
        f"{modulus}. Probes beyond index {modulus - 1} can never be selected."
    )
