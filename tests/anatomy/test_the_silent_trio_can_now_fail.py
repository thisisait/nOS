"""Anatomy CI gate — fees 45, 47, 52: three surfaces that could not fail, can.

One audit (2026-09-02) found three shapes of the same defect:
  45  a task NAMED verify whose every probe was failed_when: false
  47  a watcher that exited 0 on a CRITICAL verdict it could not deliver
  52  D2 declared "no OIDC env in role compose" with no gate, and one remained

Each assertion here reads the ARTIFACT (rendered yaml, script exit paths run
for real, template sweep) and each was retro-verified against its own break.
"""

from __future__ import annotations

import os
import pathlib
import re
import stat
import subprocess

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


# ── 45 ───────────────────────────────────────────────────────────────────────

def test_stack_verify_contains_a_task_that_can_fail():
    doc = yaml.safe_load((REPO / "tasks/iiab/stack_verify.yml").read_text())
    asserts = [t for t in doc if "ansible.builtin.assert" in t]
    assert asserts, (
        "stack_verify.yml has no assert — every probe is failed_when: false "
        "and the summary is a debug, so a converge with dead infra stays green "
        "(fee 45)")
    that = str(asserts[0]["ansible.builtin.assert"]["that"])
    assert "_auto_failed" in that, (
        "the assert does not read _auto_failed — it certifies something other "
        "than the probes' outcome")


# ── 47 ───────────────────────────────────────────────────────────────────────

def _run_drift_watch(
    tmp: pathlib.Path,
    *,
    crit: int = 0,
    high: int = 0,
    age_h: int = 1,
    stale_h: int = 336,
    hmac: str | None = None,
    curl_http: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the real watcher against a stub hook under NOS_REPO."""
    hook_dir = tmp / "hooks" / "playbook-end.d"
    hook_dir.mkdir(parents=True)
    hook = hook_dir / "20-cve-drift-check.sh"
    payload = (
        f'{{"pending_critical": {crit}, "pending_high": {high}, '
        f'"last_full_scan_age_hours": {age_h}}}'
    )
    hook.write_text("#!/bin/sh\nprintf '%s\\n' '" + payload + "'\n")
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
    path = os.environ.get("PATH", "")
    if curl_http is not None:
        bindir = tmp / "bin"
        bindir.mkdir(exist_ok=True)
        curl = bindir / "curl"
        curl.write_text("#!/bin/sh\nprintf '%s' '" + curl_http + "'\n")
        curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
        path = str(bindir) + os.pathsep + path
    env = {
        **os.environ,
        "NOS_REPO": str(tmp),
        "DRIFT_STALE_HOURS": str(stale_h),
        "PATH": path,
        "BONE_API_URL": "http://127.0.0.1:9",
    }
    if hmac:
        env["WING_EVENTS_HMAC_SECRET"] = hmac
    else:
        env.pop("WING_EVENTS_HMAC_SECRET", None)
    return subprocess.run(
        ["bash", str(REPO / "files/anatomy/scripts/drift-watch.sh")],
        capture_output=True, text=True, timeout=60, env=env, cwd=REPO,
    )


def test_an_undeliverable_critical_is_not_a_clean_run(tmp_path):
    r = _run_drift_watch(tmp_path, crit=3, hmac="")
    assert r.returncode != 0, (
        "drift-watch exits 0 on a CRITICAL it could not deliver — fee 07's "
        f"rule, fee 47's file\nstdout={r.stdout!r}\nstderr={r.stderr!r}"
    )


def test_an_undeliverable_high_is_not_a_clean_run(tmp_path):
    """HIGH/stale alert with HMAC unset must not look like a successful watch."""
    r = _run_drift_watch(tmp_path, age_h=400, hmac="")
    assert r.returncode != 0, (
        "drift-watch exits 0 on a HIGH stale alert it could not deliver "
        "(HMAC unset) — fee 07: a step that cannot do its job must not exit 0"
        f"\nstdout={r.stdout!r}\nstderr={r.stderr!r}"
    )


def test_within_thresholds_is_still_a_clean_run(tmp_path):
    r = _run_drift_watch(tmp_path, crit=0, age_h=1, hmac="")
    assert r.returncode == 0, (
        "within-threshold metric refresh must stay exit 0"
        f"\nstdout={r.stdout!r}\nstderr={r.stderr!r}"
    )


def test_an_undeliverable_high_post_is_not_a_clean_run(tmp_path):
    r = _run_drift_watch(tmp_path, age_h=400, hmac="test-hmac", curl_http="500")
    assert r.returncode != 0, (
        "drift-watch exits 0 on a HIGH alert whose Bone POST failed"
        f"\nstdout={r.stdout!r}\nstderr={r.stderr!r}"
    )


# ── 52 ───────────────────────────────────────────────────────────────────────

def test_no_role_compose_carries_an_oidc_client():
    """D2's claim, finally gated: OIDC client id/secret env belongs to plugin
    compose-extensions. nodered was the last holdout (moved 2026-09-03)."""
    offenders = []
    for tpl in sorted(REPO.glob("roles/*/templates/compose.yml.j2")):
        for n, ln in enumerate(tpl.read_text().splitlines(), 1):
            if ln.lstrip().startswith("#"):
                continue
            if re.search(r"OIDC_CLIENT_(ID|SECRET)\s*:", ln):
                offenders.append(f"{tpl.parent.parent.name}:{n}")
    assert not offenders, (
        f"OIDC client env in ROLE compose templates: {offenders}. D2 moved "
        "these to plugin compose-extensions; a role-side copy is the second "
        "declaration D2 exists to forbid")
