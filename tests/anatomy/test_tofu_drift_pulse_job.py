"""Anatomy gate — read-only tofu drift Pulse job (ADR-0001 P2 / W6.1).

The authentik-tofu-drift-base plugin schedules a daily READ-ONLY `tofu plan`
over terraform/authentik/ and notifies the operator on drift. Two invariants
make the job safe to auto-fire on every install:

  1. PLAN-ONLY — the script must never invoke any tofu subcommand other than
     `plan` (the apply path stays in tasks/tofu-authentik.yml, destroy-guarded),
     and the plan must run -lock=false so a stale state lock can neither wedge
     the scheduled job nor make it contend with an operator's interactive run.
  2. INERT PRE-CUTOVER — the Pulse catalog registers jobs unconditionally
     (gdpr-breach-base precedent), so the script itself must exit 0 with a
     skip line when the tofu binary or nos.auto.tfvars.json is absent.

Pins (mirrors test_gitleaks_scan_command.py — static analysis over the shell
script + manifest, no live tofu needed):
  - script exists, is executable, and is the exact path the pulse_jobs block
    wires (after the catalog's literal {{ playbook_dir }} substitution);
  - the plan invocation carries -input=false -no-color -detailed-exitcode
    -lock=false, and `plan` is the ONLY tofu subcommand in the script;
  - the manifest's pulse block parses with the catalog's expected shape;
  - the tfvars-absent skip path actually exits 0 (executed hermetically).
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO / "files/anatomy/plugins/authentik-tofu-drift-base"
MANIFEST = PLUGIN_DIR / "plugin.yml"
SCRIPT = PLUGIN_DIR / "skills/run-tofu-drift.sh"


def _job() -> dict:
    doc = yaml.safe_load(MANIFEST.read_text())
    jobs = (doc.get("pulse") or {}).get("jobs") or []
    assert len(jobs) == 1, "authentik-tofu-drift-base must declare exactly one pulse job"
    return jobs[0]


def test_script_exists_and_is_executable():
    assert SCRIPT.is_file(), f"{SCRIPT} missing"
    assert os.access(SCRIPT, os.X_OK), (
        f"{SCRIPT} must carry the executable bit — Pulse subprocess runner "
        f"execs it directly (no shell wrapper; `bash` is a banned basename)")


def test_pulse_block_wires_the_committed_script():
    """The job command must resolve to the committed script after the
    catalog's LITERAL `{{ playbook_dir }}` substitution (bare token —
    discover-pulse-catalog.py does no Jinja parsing)."""
    job = _job()
    assert job.get("runner", "subprocess") == "subprocess"
    cmd = job["command"]
    assert cmd.startswith("{{ playbook_dir }}/"), (
        "command must be rooted at the bare {{ playbook_dir }} token so the "
        "catalog substitution lands it under an allowlisted prefix")
    rendered = pathlib.Path(cmd.replace("{{ playbook_dir }}", str(REPO)))
    assert rendered == SCRIPT, (
        f"pulse job command renders to {rendered}, expected {SCRIPT}")


def test_pulse_schedule_is_daily_cron():
    """Five-field cron, daily cadence (fixed hour/minute, wildcard the rest)."""
    schedule = _job()["schedule"]
    fields = schedule.split()
    assert len(fields) == 5, f"schedule {schedule!r} is not 5-field cron"
    minute, hour, dom, month, dow = fields
    assert minute.isdigit() and hour.isdigit(), \
        f"daily job needs a fixed minute+hour, got {schedule!r}"
    assert (dom, month, dow) == ("*", "*", "*"), \
        f"daily cadence expected (dom/month/dow = '*'), got {schedule!r}"


def test_internal_watchdog_fires_before_pulse_sigkill():
    """The script's default TOFU_PLAN_TIMEOUT_S must be BELOW the job's
    max_runtime_s — a Pulse SIGKILL never reaches the error-notify path."""
    job = _job()
    m = re.search(r'TOFU_PLAN_TIMEOUT_S:-(\d+)', SCRIPT.read_text())
    assert m, "TOFU_PLAN_TIMEOUT_S default not found in script"
    assert int(m.group(1)) < int(job["max_runtime_s"]), (
        "internal watchdog default must be < pulse max_runtime_s so the "
        "high-severity plan_error notification fires before Pulse SIGKILLs")


def test_plan_invocation_is_read_only_and_lockless():
    """The tofu invocation must be `plan` with the read-only flag set:
    -detailed-exitcode (drift signalling), -lock=false (a stale operator
    lock must never wedge the scheduled job), -input=false -no-color."""
    src = SCRIPT.read_text()
    m = re.search(r'"\$TOFU_BIN"\s+plan\s+(.*?)(?:\\\n\s*.*?)?\n', src)
    assert m, 'no `"$TOFU_BIN" plan ...` invocation found in run-tofu-drift.sh'
    # Collect the full (possibly line-continued) invocation.
    inv = re.search(r'"\$TOFU_BIN"\s+plan[^\n]*(?:\\\n[^\n]*)*', src).group(0)
    for flag in ("-input=false", "-no-color", "-detailed-exitcode", "-lock=false"):
        assert flag in inv, f"tofu plan invocation must carry {flag}: {inv!r}"


def test_plan_is_the_only_tofu_subcommand():
    """NEVER applies — `plan` must be the only subcommand ever passed to the
    resolved tofu binary (the destroy-guarded apply stays in
    tasks/tofu-authentik.yml)."""
    src = SCRIPT.read_text()
    subcommands = set(re.findall(r'"?\$TOFU_BIN"?\s+([a-z-]+)', src))
    assert subcommands == {"plan"}, (
        f"run-tofu-drift.sh invokes tofu subcommands {sorted(subcommands)}; "
        f"only 'plan' is permitted (plan-only/read-only contract)")
    # Belt-and-braces against a bare PATH-resolved invocation evading the
    # $TOFU_BIN regex: mutating verbs must not appear in any code line.
    code_lines = [
        l for l in src.splitlines() if not l.lstrip().startswith("#")
    ]
    for verb in ("tofu apply", "tofu destroy", " apply ", " destroy "):
        offenders = [l for l in code_lines if verb in l]
        assert not offenders, (
            f"mutating tofu verb {verb!r} found outside comments: {offenders!r}"
        )


def test_env_tokens_are_bare():
    """Catalog does LITERAL token replace — no `| filter` forms allowed
    (global guard exists in test_pulse_command_allowlist; pinned locally so
    a drift-job edit fails next to its own gate)."""
    job = _job()
    filtered = re.compile(r"\{\{[^}]*\|[^}]*\}\}")
    values = [job["command"], str(job["schedule"])] + \
        [str(v) for v in (job.get("env") or {}).values()]
    offenders = [v for v in values if filtered.search(v)]
    assert not offenders, f"pulse tokens must be bare: {offenders}"


def test_script_skips_cleanly_pre_cutover(tmp_path):
    """Hermetic execution of the skip path: with NOS_TOFU_DIR pointing at a
    dir without nos.auto.tfvars.json the script must exit 0 and say so
    (covers the tofu-binary-absent branch too on hosts without tofu —
    either gate short-circuits to the same quiet exit 0)."""
    proc = subprocess.run(
        [str(SCRIPT)],
        env={**os.environ, "NOS_TOFU_DIR": str(tmp_path)},
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, (
        f"pre-cutover skip must exit 0, got rc={proc.returncode}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
    assert "skipping drift check" in proc.stdout, \
        f"expected a skip log line, got: {proc.stdout!r}"
