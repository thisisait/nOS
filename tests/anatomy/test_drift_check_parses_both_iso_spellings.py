"""Anatomy gate: the CVE drift hook must parse both ISO-8601 spellings it is fed.

`hooks/playbook-end.d/20-cve-drift-check.sh` is the probe behind the nightly
`conductor:security-drift-watch` job. Two writers put timestamps into
`docs/llm/security/scan-state.json` and they do not agree on a spelling:

  * `files/vuln-scan/scan-runner.sh` writes UTC with a trailing Z (jq `todate`)
  * the security agent writes LOCAL time with a numeric offset, e.g.
    `2026-07-15T04:08:29+02:00`

jq's `fromdateiso8601` accepts only the Z form. Fed an offset it does not return
null — it ABORTS, so the hook emitted nothing at all, the downstream `--argjson`
received invalid JSON, and `drift-watch.sh` logged *"drift-check produced no JSON
— skip"* and exited 0. The nightly job had therefore never once produced a
verdict, while CLAUDE.md recorded this hook as the manual path that "works
today".

The bash side had the mirror defect: `date -j -f '%Y-%m-%dT%H:%M:%SZ'` rejects the
offset form and the GNU `date -d` fallback does not exist on macOS, so every
agent-written timestamp scored epoch 0 and reported age -1 ("unreadable").

What it cost, measured the morning it was fixed (2026-07-28): the hook's first
successful run reported `pending_critical: 1` — REM-137, a 36-CVE Gitea 1.27.0
cluster with two CVSS-9.x CRITICALs, filed by the previous night's scan. That is
precisely the input the job exists to alert on, at the severity that routes to
wing-inbox, ntfy and mail.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "playbook-end.d" / "20-cve-drift-check.sh"
WATCH = REPO / "files" / "anatomy" / "scripts" / "drift-watch.sh"
STATE = REPO / "docs" / "llm" / "security" / "scan-state.json"

BOTH_SPELLINGS = ["2026-07-15T04:08:29+02:00", "2026-07-28T04:02:27Z"]


def test_the_hook_does_not_use_bare_fromdateiso8601_on_state_timestamps() -> None:
    """Bare `fromdateiso8601` aborts the whole program on an offset timestamp."""
    src = HOOK.read_text()
    offenders = [
        f"{ln}: {line.strip()}"
        for ln, line in enumerate(src.splitlines(), 1)
        if "fromdateiso8601" in line
        and not line.lstrip().startswith("#")
        and "epoch_of" not in line
        and ".b + " not in line
    ]
    assert not offenders, (
        "a state timestamp is parsed with bare `fromdateiso8601`, which accepts only the "
        "trailing-Z spelling and ABORTS (does not return null) on the numeric-offset form "
        "the security agent writes. An abort here empties the hook's stdout and the nightly "
        f"drift-watch degrades to a silent skip. Offenders:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_the_jq_helper_handles_offset_and_z_and_skips_garbage() -> None:
    """Execute the real helper — a regex match on the source is not proof."""
    src = HOOK.read_text()
    m = re.search(r"(def epoch_of:.*?end;)", src, re.S)
    assert m, "could not find the epoch_of helper to execute"
    prog = m.group(1) + '\n[.[] | (epoch_of? // null)]'
    proc = subprocess.run(
        ["jq", "-c", prog],
        input=json.dumps(BOTH_SPELLINGS + ["not-a-date", ""]),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"the helper aborts instead of skipping: {proc.stderr.strip()}"
    got = json.loads(proc.stdout)
    assert got[0] is not None and got[1] is not None, f"a valid spelling was dropped: {got}"
    # 2026-07-15T04:08:29+02:00 is 02:08:29 UTC. Verified against
    # datetime.fromisoformat, not computed by hand — the first draft of this
    # constant was wrong and the gate caught the test rather than the code.
    assert got[0] == 1784081309, f"offset not applied correctly: {got[0]}"
    assert got[2] is None and got[3] is None, f"garbage should skip, not abort: {got}"


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_the_hook_emits_parseable_json_against_the_real_state() -> None:
    """End to end: drift-watch's only contract is that this prints one JSON object."""
    proc = subprocess.run(
        ["bash", str(HOOK)],
        capture_output=True,
        text=True,
        env={"NOS_REPO": str(REPO), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
    )
    assert proc.stdout.strip(), (
        "the hook printed nothing. drift-watch.sh treats empty stdout as 'produced no JSON' "
        f"and skips the night silently. stderr:\n{proc.stderr}"
    )
    snap = json.loads(proc.stdout)
    assert snap.get("last_full_scan_age_hours", -1) >= 0, (
        "last_full_scan_age_hours is negative, meaning the timestamp did not parse. "
        f"snapshot: {snap}"
    )


def test_drift_watch_still_treats_empty_stdout_as_skip() -> None:
    """Pin the consumer contract, so this gate cannot outlive its reason."""
    src = WATCH.read_text()
    assert "produced no JSON" in src, (
        "drift-watch.sh no longer skips on unparseable stdout. Re-read this gate: the "
        "silent-skip path is the reason the hook's output shape is load-bearing."
    )


def test_the_state_file_really_does_carry_both_spellings() -> None:
    """If one writer is ever normalised away, say so rather than guessing."""
    state = json.loads(STATE.read_text())
    stamps = [
        v.get("last_cve_scan")
        for v in state.get("components", {}).values()
        if isinstance(v, dict) and v.get("last_cve_scan")
    ]
    stamps.append(state.get("last_full_scan"))
    stamps = [s for s in stamps if isinstance(s, str)]
    assert stamps, "no timestamps in scan-state.json — this gate is measuring nothing"
    offset = [s for s in stamps if re.search(r"[+-]\d{2}:\d{2}$", s)]
    assert offset, (
        "no offset-form timestamps remain in scan-state.json. If both writers now emit UTC "
        "with a trailing Z, the dual-spelling parsing is still correct but is no longer "
        "exercised by real data — keep it, and note here that the coverage is synthetic."
    )
