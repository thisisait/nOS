"""Anatomy CI gate — a second macOS converge reports changed=0.

MEASURED 2026-10-11, release PR #55, macos-26 run 38147660269: both macOS lanes ended pass 2 with changed=4, the
same four on each. Each was a task whose `changed` came from the attempt, not
from the observed state:

  homebrew  recursive chown ran every pass: root daemons rewrite var/run pid
            files as root, so the mis-owned probe always found something.
  nginx     the "already loaded?" probe asked launchd for homebrew.mxcl.nginx
            while Homebrew 7 loads sh.brew.nginx, so the start always "changed".
  pulse     `pip install <dir>` reinstalled every pass; the fresh mtimes made
            the daemon-age probe read STALE and bounce a current daemon.
  cortex    the volume UUID was read before the data root existed, so pass 1
            recorded '' and pass 2 rewrote the mount sentinel with the UUID.

The live proof is the CI idempotence step, which is continue-on-error on the
macOS lane; this pins the shape offline so the fix cannot quietly regress.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
BREW = REPO / "roles" / "pazny.mac.homebrew" / "tasks" / "main.yml"
NGINX = REPO / "tasks" / "nginx.yml"
PULSE = REPO / "roles" / "pazny.pulse" / "tasks" / "main.yml"
BREW_SVC = REPO / "files" / "brew-svc.sh"
MAIN = REPO / "main.yml"
CORTEX = REPO / "roles" / "pazny.cortex" / "tasks" / "main.yml"


def _task(path: pathlib.Path, name: str) -> dict:
    for t in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
        if t.get("name") == name:
            return t
    raise AssertionError(f"{path.relative_to(REPO)}: no task named {name!r}")


def _cmd(task: dict) -> str:
    for key in ("ansible.builtin.shell", "ansible.builtin.command", "shell", "command"):
        if key in task:
            v = task[key]
            return v.get("cmd", "") if isinstance(v, dict) else str(v)
    return ""


def _brew_label_prefixes() -> list[str]:
    m = re.search(r"^for pfx in ([^;]+);", BREW_SVC.read_text(encoding="utf-8"), re.M)
    assert m, "brew-svc.sh no longer lists its plist label prefixes in a `for pfx in` loop"
    pfxs = m.group(1).split()
    # Floor: Homebrew 7 loads sh.brew.<svc>; dropping it from the loop must not drop the check.
    assert "sh.brew" in pfxs, "brew-svc.sh no longer tries the sh.brew label prefix"
    return pfxs


def test_the_homebrew_chown_runs_only_on_a_misowned_path():
    probe = _task(BREW, "Which files under homebrew_install_path are not owned by homebrew_user:group?")
    chown = _task(BREW, "Ensure proper ownership on homebrew_install_path subdirs.")
    assert "_brew_misowned" in str(chown.get("when", "")), (
        "the recursive chown is not gated on the mis-owned probe: it reports "
        "changed for the whole tree on every converge")
    assert "/var/run" in _cmd(probe) and "-prune" in _cmd(probe), (
        "the probe no longer prunes var/run: root daemons rewrite their pid "
        "files as root, so the chown fires on every converge")


def test_the_nginx_start_reads_launchd_for_every_brew_label():
    probe = _task(NGINX, "Check whether nginx is already loaded in launchd")
    start = _task(NGINX, "Start and enable nginx via brew services")
    assert "nginx_loaded" in str(start.get("changed_when", "")), (
        "the nginx start reports changed from the attempt, not from launchd state")
    for pfx in _brew_label_prefixes():
        assert f"{pfx}.nginx" in _cmd(probe), (
            f"brew-svc.sh loads {pfx}.nginx but the probe never asks launchd "
            "for it, so an already-running nginx reads as not loaded")
    restart = [h for play in yaml.safe_load(MAIN.read_text(encoding="utf-8"))
               for h in play.get("handlers", []) if h.get("name") == "Restart nginx"]
    assert restart and all(f"{p}.nginx" in _cmd(restart[0]) for p in _brew_label_prefixes()), (
        "the Restart nginx handler does not know every brew label prefix")


def test_pulse_reinstalls_only_when_its_source_changed():
    install = _task(PULSE, "[pazny.pulse] Install pulse package into venv")
    record = _task(PULSE, "[pazny.pulse] Record the hash the venv was built from")
    probe = _task(PULSE, "[pazny.pulse] Detect a daemon older than the code it runs")
    assert "_pulse_src_sha" in str(install.get("when", "")), (
        "pip install <dir> runs every converge; its fresh mtimes make the "
        "daemon-age probe bounce a current daemon")
    assert ".nos-source-sha256" in str(record.get("ansible.builtin.copy", {}).get("dest", ""))
    assert "STALE" in str(probe.get("changed_when", "")), (
        "the daemon-age probe must report changed only when it saw STALE")


def test_cortex_reads_the_volume_uuid_after_the_data_root_exists():
    names = [t.get("name") for t in yaml.safe_load(CORTEX.read_text(encoding="utf-8"))]
    create = names.index("[pazny.cortex] Create an ordinary (non-removable) data root")
    uuid = names.index("[pazny.cortex] Read the data root's volume UUID (recorded in the sentinel)")
    assert uuid > create, (
        "the volume UUID is read before the data root exists: pass 1 records '' "
        "and pass 2 rewrites the mount sentinel")
