"""Anatomy gate — Conductor scheduled Pulse jobs are live + resolvable.

The scheduled closed-loop Conductor is the read-only-health half of the
A8 nerve: three Pulse jobs declared in ``files/anatomy/agents/conductor.yml``
that fire on cron via the Pulse daemon (launchd ``eu.thisisait.nos.pulse``):

  - self-test-001       weekly  Sun 04:00 UTC  (Phase 5 ceremony)
  - security-drift-watch daily      06:00 UTC  (deterministic drift probe)
  - vulnerability-scan   daily      02:00 UTC  (LLM scan-REFRESH)

This finding ("jobs are live and tested") is confirmed-true; the fix is a
REGRESSION GATE that pins the live contract so a rename / dropped schedule /
runner swap / a filter-token slip can't silently de-activate the closed-loop
conductor between playbook runs. It complements:

  - test_phase5_ceremony.py       — operator-driven manual ceremony CLI
  - test_pulse_command_allowlist.py — Wing-side command validator + bare tokens

…neither of which pins the conductor.yml job block itself.

The load-bearing invariant: every command/env token must RESOLVE to a bare
value through discover-pulse-catalog.py's literal-substitution table. A token
the catalog can't render ships ``{{ … }}`` into pulse_jobs and the job
exits 127 / fails at runtime (the silent-failure class caught live 2026-05-07
+ 2026-05-25).
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import re
import stat

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
CONDUCTOR = REPO / "files/anatomy/agents/conductor.yml"
DISCOVER = REPO / "files/anatomy/scripts/discover-pulse-catalog.py"

# Canonical contract — name → (cron schedule, runner). Pinning the cron string
# guards against an accidental cadence change de-activating the watcher.
EXPECTED_JOBS = {
    "self-test-001":        ("0 4 * * 0", "subprocess"),  # weekly Sun 04:00 UTC
    "security-drift-watch": ("0 6 * * *", "subprocess"),  # daily 06:00 UTC
    "vulnerability-scan":   ("0 2 * * *", "subprocess"),  # daily 02:00 UTC
}


def _conductor_jobs() -> dict[str, dict]:
    doc = yaml.safe_load(CONDUCTOR.read_text()) or {}
    jobs = ((doc.get("pulse") or {}).get("jobs")) or []
    return {j["name"]: j for j in jobs}


def _load_discover():
    """Import discover-pulse-catalog.py despite its dash-named filename."""
    spec = importlib.util.spec_from_file_location("_discover_catalog", DISCOVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_three_named_jobs_with_exact_schedule_and_runner():
    jobs = _conductor_jobs()
    for name, (cron, runner) in EXPECTED_JOBS.items():
        assert name in jobs, f"conductor.yml is missing pulse job '{name}'"
        job = jobs[name]
        assert job.get("schedule") == cron, (
            f"job '{name}' schedule drifted: {job.get('schedule')!r} != {cron!r}"
        )
        assert job.get("runner") == runner, (
            f"job '{name}' runner must stay '{runner}' (Pulse subprocess runner)"
        )
        # max_concurrent=1 keeps the closed-loop from stacking overlapping runs.
        assert job.get("max_concurrent") == 1, (
            f"job '{name}' must declare max_concurrent: 1"
        )


def test_job_command_scripts_exist_and_executable():
    """Each command resolves (post {{ playbook_dir }}) to a real chmod+x file —
    a non-existent / non-exec command makes Pulse exit 127 at fire time."""
    jobs = _conductor_jobs()
    for name in EXPECTED_JOBS:
        cmd = str(jobs[name].get("command", ""))
        resolved = cmd.replace("{{ playbook_dir }}", str(REPO))
        path = pathlib.Path(resolved)
        assert path.is_file(), f"job '{name}' command not on disk: {resolved}"
        assert path.stat().st_mode & stat.S_IXUSR, (
            f"job '{name}' command must be executable: {resolved}"
        )


def test_every_token_resolves_through_catalog():
    """The closed-loop invariant: after discover-pulse-catalog.py expansion,
    NO command/env value may still carry a `{{ … }}` literal. Every token the
    conductor jobs reference must live in the substitution table — otherwise
    the job ships an unrendered string into pulse_jobs and fails at runtime."""
    discover = _load_discover()

    # Populate the env the substitution table reads, so resolution is total.
    env = {
        "NOS_PLAYBOOK_DIR":             str(REPO),
        "NOS_AUTHENTIK_DOMAIN":         "auth.dev.local",
        "NOS_TENANT_DOMAIN":            "dev.local",
        "NOS_GLOBAL_PASSWORD_PREFIX":   "nostest",
        "NOS_CONDUCTOR_WING_API_TOKEN": "tok-conductor",
        "NOS_BONE_SECRET":              "hmac-secret",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        subs = discover._build_substitutions()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    token = re.compile(r"\{\{[^}]*\}\}")
    leftover: list[str] = []
    for name, job in _conductor_jobs().items():
        if name not in EXPECTED_JOBS:
            continue
        vals = [str(job.get("command", "")), str(job.get("schedule", ""))]
        vals += [str(v) for v in (job.get("env") or {}).values()]
        for v in vals:
            resolved = discover._expand(v, subs)
            if token.search(str(resolved)):
                leftover.append(f"[{name}] {v!r} -> {resolved!r}")
    assert not leftover, (
        "conductor pulse tokens did not fully resolve through the catalog "
        f"(would ship literal Jinja into pulse_jobs): {leftover}"
    )


def test_env_carries_hmac_and_auth_surface():
    """Each job's env must attribute the run: the HMAC secret (event signing)
    is present on all three; the LLM/agent jobs carry the Authentik/Wing surface
    they read against."""
    jobs = _conductor_jobs()
    for name in EXPECTED_JOBS:
        env = jobs[name].get("env") or {}
        assert "WING_EVENTS_HMAC_SECRET" in env, (
            f"job '{name}' must sign events with WING_EVENTS_HMAC_SECRET"
        )
    # self-test-001 is the agent ceremony — it must reach Wing + Authentik.
    selftest_env = jobs["self-test-001"].get("env") or {}
    assert selftest_env.get("WING_API_TOKEN"), "self-test-001 needs WING_API_TOKEN"
    assert "WING_API_URL" in selftest_env
    assert "NOS_AUTHENTIK_URL" in selftest_env
