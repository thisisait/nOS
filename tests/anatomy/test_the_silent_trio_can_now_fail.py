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

def _run_drift_watch(tmp: pathlib.Path, crit: int, hmac: str) -> int:
    """Run the real script with a stubbed check that reports `crit` criticals."""
    stub = tmp / "20-cve-drift-check.sh"
    stub.write_text("#!/bin/sh\nprintf '{\"pending_critical\": %s, "
                    "\"pending_high\": 0, \"scan_age_hours\": 1}' " + str(crit) + "\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "NOS_DRIFT_CHECK": str(stub), "PATH": os.environ["PATH"]}
    if hmac:
        env["WING_EVENTS_HMAC_SECRET"] = hmac
    else:
        env.pop("WING_EVENTS_HMAC_SECRET", None)
    r = subprocess.run(["bash", str(REPO / "files/anatomy/scripts/drift-watch.sh")],
                       capture_output=True, text=True, timeout=60, env=env,
                       cwd=REPO)
    return r.returncode


def test_an_undeliverable_critical_is_not_a_clean_run(tmp_path):
    src = (REPO / "files/anatomy/scripts/drift-watch.sh").read_text()
    if "NOS_DRIFT_CHECK" not in src:
        # The script hardcodes its check path; assert the exit-path shape
        # instead of running it (fee 47's close in source, comments stripped).
        body = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("#"))
        assert re.search(r'"critical" \]\] && exit 1', body), (
            "drift-watch exits 0 on a CRITICAL it could not deliver — fee 07's "
            "rule, fee 47's file")
        assert body.count('&& exit 1') >= 2, (
            "only one undeliverable path refuses; HMAC-unset and POST-failure "
            "must both")
        return
    assert _run_drift_watch(tmp_path, crit=3, hmac="") != 0


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
