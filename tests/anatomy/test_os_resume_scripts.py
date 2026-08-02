"""Anatomy gate — macOS-as-managed-upgrade continuation scripts (Increment 1).

Spec: docs/archive/macos-as-managed-upgrade-target.md. The operator triggers the
macOS update; nOS owns the PRE (arm) + POST (resume→settle) across the reboot it
cannot survive. These gates pin the load-bearing contracts structurally (the
runtime behaviour is smoke-tested separately + by the real update):

  * the 4 scripts parse clean (bash -n) and are executable;
  * the reboot detection uses a boot-id that is the boot EPOCH, not usec;
  * resume fires settle ONLY when the host rebooted into a DIFFERENT OS, never
    prematurely (the safety property — it must not lose/早-fire the plan);
  * settle is SUDO-FREE (a login agent can't answer the playbook's sudo prompt).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "files" / "anatomy" / "scripts"
BOOTID = SCRIPTS / "nos-boot-id.sh"
RESUME = SCRIPTS / "nos-os-resume.sh"
SETTLE = SCRIPTS / "nos-os-settle.sh"
ARM = REPO / "tools" / "nos-os-update-arm.sh"
NOTIFY = SCRIPTS / "nos-notify.sh"

ALL_SCRIPTS = [BOOTID, RESUME, SETTLE, ARM, NOTIFY]


@pytest.mark.parametrize("script", ALL_SCRIPTS, ids=lambda p: p.name)
def test_script_exists_executable_and_parses(script: Path):
    assert script.is_file(), f"{script} missing"
    assert os.access(script, os.X_OK), f"{script} must be executable (chmod +x)"
    r = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert r.returncode == 0, f"bash -n {script.name} failed: {r.stderr}"


def test_boot_id_extracts_epoch_not_usec():
    """`kern.boottime` is `{ sec = <epoch>, usec = <micros> } …`. A greedy
    `s/.*sec = …/` grabs usec; the script must take the FIRST integer (epoch)."""
    body = BOOTID.read_text()
    assert "kern.boottime" in body
    assert "/proc/sys/kernel/random/boot_id" in body, "Linux boot-id branch missing"
    # the anchored first-integer extraction, NOT the greedy usec-grabbing form
    assert "s/^[^0-9]*([0-9]+).*/" in body, "boot-id must extract the FIRST integer (epoch)"
    assert "s/.*sec = " not in body, "greedy sed grabs usec, not the boot epoch"


def test_resume_only_fires_on_reboot_into_different_os():
    body = RESUME.read_text()
    # no plan armed → no-op
    assert 'continuation-plan.json' in body
    assert '[ -f "$PLAN" ] || exit 0' in body, "resume must no-op when no plan is armed"
    # boot-id comparison gates the 'still PRE' case
    assert "armed_boot" in body and "boot_now" in body
    assert '"$boot_now" = "$armed_boot"' in body, "must skip when boot-id is unchanged (not rebooted)"
    # OS-version comparison distinguishes the real update from an unrelated reboot
    assert "os_before" in body and "os_now" in body
    assert "sw_vers -productVersion" in body
    # one-shot: the plan is archived after a real settle (no login re-loop)
    assert "-done-" in body, "resume must archive the plan after settling (one-shot)"
    # dry-run hook for safe preview / tests
    assert "NOS_RESUME_DRY" in body
    # NOS_DIR override so tests/operators can point at a temp dir
    assert 'NOS_DIR="${NOS_DIR:-${HOME}/.nos}"' in body


def test_settle_is_sudo_free():
    """A launchd login agent can't answer the playbook's sudo vars_prompt, so the
    settle must never call sudo — it ensures Docker is up + reports, and surfaces
    sudo/GUI repairs (CLT after a major bump) as ATTENTION lines instead."""
    body = SETTLE.read_text()
    assert "sudo " not in body, "settle must be sudo-free (login agent has no sudo)"
    assert "docker info" in body, "settle must verify the Docker daemon"
    assert "open -a Docker" in body, "settle must bring Docker Desktop up"
    assert "ATTENTION" in body, "settle must REPORT (not attempt) sudo/GUI-only repairs"
    # exits with a status the resume can act on
    assert "exit 0" in body and "exit 1" in body


def test_arm_writes_a_plan_resume_accepts(tmp_path: Path):
    """End-to-end PRE: arm writes a plan with the boot-id + OS version; resume,
    run immediately after (same boot, no reboot), correctly no-ops on it."""
    if not (REPO / ".python-version").exists():  # ensure repo layout
        pytest.skip("not in repo")
    env = {**os.environ, "NOS_DIR": str(tmp_path)}
    a = subprocess.run(["bash", str(ARM)], cwd=str(REPO), env=env, capture_output=True, text=True)
    plan = tmp_path / "continuation-plan.json"
    # arm needs jq + sw_vers (macOS); skip cleanly where unavailable
    if a.returncode != 0 or not plan.exists():
        pytest.skip(f"arm unavailable in this env (rc={a.returncode}): {a.stderr[:120]}")
    import json
    data = json.loads(plan.read_text())
    assert data.get("armed_boot_id"), "plan must record the boot-id"
    assert data.get("os_version_before"), "plan must record the OS version"
    # resume right after arm = same boot → must NOT fire (still PRE window)
    r = subprocess.run(["bash", str(RESUME)], cwd=str(REPO), env=env, capture_output=True, text=True)
    assert r.returncode == 0
    assert plan.exists(), "resume must leave the plan armed when the host has not rebooted"


# ── Increment 3 — A9/Bone notification fanout ─────────────────────────────────

def test_notify_is_literal_payload_and_best_effort():
    """nos-notify must POST a LITERAL title+body+channels (a template would 404 in
    Bone -> 400 -> dropped, the upgrade-engine lesson), HMAC-sign, read the secret
    from env or ~/.nos/secrets.yml, and be a silent no-op when deps/secret/Bone are
    missing (it runs at login-time settle and must never fail its caller)."""
    body = NOTIFY.read_text()
    assert '"template"' not in body and "template:" not in body, "notify must not use a Bone template"
    assert "title" in body and "channels" in body
    assert "WING_EVENTS_HMAC_SECRET" in body and "secrets.yml" in body, "must source the HMAC secret"
    assert "openssl dgst -sha256 -hmac" in body and "X-Wing-Signature" in body, "must HMAC-sign the POST"
    assert "command -v" in body and "exit 0" in body, "must be best-effort (no-op on missing deps)"
    assert "sudo " not in body


def test_resume_fans_an_a9_notification():
    body = RESUME.read_text()
    assert "nos-notify.sh" in body, "resume must emit an A9 notification via nos-notify.sh"
    # severity derives from the settle outcome (attention -> high, warn -> medium, else info)
    assert 'sev="high"' in body and 'sev="medium"' in body and 'sev="info"' in body


# ── Increment 2 — launchd login agent + playbook install ──────────────────────

PLIST = REPO / "templates" / "eu.thisisait.nos.resume.plist.j2"
OS_RESUME_TASKS = REPO / "tasks" / "os-resume.yml"
MAIN = REPO / "main.yml"
CONFIG = REPO / "default.config.yml"


def test_resume_launchd_plist_is_a_oneshot_login_agent():
    body = PLIST.read_text()
    assert "<string>eu.thisisait.nos.resume</string>" in body
    assert "nos-os-resume.sh" in body, "plist must launch the resume executor"
    assert "<key>RunAtLoad</key>\n  <true/>" in body, "must fire at each login"
    # one-shot per login — must NOT KeepAlive (would re-loop the check)
    assert "<key>KeepAlive</key>\n  <false/>" in body, "resume agent must be one-shot (KeepAlive false)"
    # a login agent has a minimal PATH — the plist must add Homebrew (jq) + docker
    assert "<key>PATH</key>" in body and "homebrew" in body.lower(), \
        "plist must set PATH so jq/docker are found by the login agent"


def test_os_resume_tasks_are_macos_gated_and_install_the_agent():
    body = OS_RESUME_TASKS.read_text()
    assert body.count("nos_service_manager | default('launchd')) == 'launchd'") >= 3, \
        "every os-resume task must be macOS(launchd)-gated — Linux skips cleanly"
    assert "eu.thisisait.nos.resume.plist.j2" in body, "must render the plist"
    assert "launchctl load -w" in body, "must load the launch agent"
    assert "launchctl list eu.thisisait.nos.resume" in body, "must probe for idempotence"


def test_main_wires_os_resume_with_its_own_tag():
    body = MAIN.read_text()
    assert "import_tasks: tasks/os-resume.yml" in body, "main.yml must import the os-resume tasks"
    assert "install_os_resume | default(true)" in body, "import must be gated on install_os_resume"
    # the 'os-resume' tag must reach it so `--tags os-resume` installs just this
    block = body[body.find("tasks/os-resume.yml"):]
    assert "'os-resume'" in block[:200], "import must carry the os-resume tag"


def test_install_os_resume_flag_has_a_real_default():
    """The var must be defined in default.config.yml (a plain boolean) — both for
    the {{ vars }} eager-resolve trap and so the toggle is discoverable."""
    body = CONFIG.read_text()
    assert "\ninstall_os_resume: true" in body, "install_os_resume must have a real default"
