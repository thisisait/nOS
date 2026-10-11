"""Anatomy CI gate — the four tasks a second macOS converge reported changed.

MEASURED 2026-10-11, release PR #55, macos-26 run 38147660269: blank converge
failed=0, second converge failed=0 changed=4. Each one read an attempt, or a
moment, instead of the state:

  * homebrew ownership: the probe listed var/run/dnsmasq/dnsmasq.pid, which a
    root daemon rewrites as root, so every run chowned it again;
  * nginx: the "already loaded?" probe asked for homebrew.mxcl.nginx, but
    Homebrew 7 labels it sh.brew.nginx (dnsmasq already moved), so never loaded;
  * cortex: the volume UUID was read before the run created ~/nos, so the first
    sentinel said null and the second wrote the real UUID;
  * pulse: `pip install <dir>` reinstalls every run, the new mtimes made the
    staleness probe say STALE, and the daemon was bounced on every converge
    (live host too: daemon start 24 s after the 2026-10-10 install).
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def _tasks(rel: str) -> list[dict]:
    return yaml.safe_load((REPO / rel).read_text(encoding="utf-8")) or []


def _named(tasks: list[dict], fragment: str) -> tuple[int, dict]:
    for i, t in enumerate(tasks):
        if fragment in str(t.get("name", "")):
            return i, t
    raise AssertionError(f"no task named like {fragment!r} — update this gate")


def test_root_daemon_runtime_files_are_not_ownership_drift():
    _, t = _named(_tasks("roles/pazny.mac.homebrew/tasks/main.yml"),
                  "are not owned by homebrew_user")
    cmd = str(t.get("command") or t.get("ansible.builtin.command"))
    assert "var/run" in cmd and "-prune" in cmd, (
        "the mis-owned probe walks var/run, where root daemons (dnsmasq) write "
        "root-owned pid files; every converge then chowns them again")


def test_nginx_is_recognised_under_its_homebrew_7_label():
    _, probe = _named(_tasks("tasks/nginx.yml"), "nginx is already loaded")
    assert "sh.brew.nginx" in str(probe), (
        "the loaded probe never asks for sh.brew.nginx, so a running nginx "
        "reads as not loaded and the start reports changed every run")
    plays = yaml.safe_load((REPO / "main.yml").read_text(encoding="utf-8"))
    handler = next(h for p in plays for h in (p.get("handlers") or [])
                   if h.get("name") == "Restart nginx")
    assert "sh.brew.nginx" in str(handler), (
        "the Restart nginx handler only knows homebrew.mxcl.nginx.plist and "
        "silently restarts nothing on Homebrew 7")


def test_the_volume_uuid_is_read_after_the_data_root_exists():
    tasks = _tasks("roles/pazny.cortex/tasks/main.yml")
    probe, _ = _named(tasks, "Read the data root's volume UUID")
    create, _ = _named(tasks, "Create an ordinary (non-removable) data root")
    assert probe > create, (
        "the UUID is read before the first run creates nos_data_root, so the "
        "first sentinel records null and the second converge rewrites it")


def test_pulse_reinstalls_only_when_its_source_changed():
    tasks = _tasks("roles/pazny.pulse/tasks/main.yml")
    _, install = _named(tasks, "Install pulse package into venv")
    assert "_pulse_src_sha" in str(install.get("when", "")), (
        "the pip install runs every converge; its fresh mtimes make the "
        "staleness probe bounce a current daemon on every run")
