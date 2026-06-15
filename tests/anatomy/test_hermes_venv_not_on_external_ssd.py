"""Anatomy gate — Hermes launchd venv must NOT live on the external SSD.

Hermes runs as a launchd web-UI daemon (hermes_daemon_mode). A launchd-spawned
interpreter reads its venv (pyvenv.cfg + the site module) at startup, and macOS
TCC DENIES launchd reads of the external removable volume (/Volumes/SSD1TB). The
interpreter died with "PermissionError ... pyvenv.cfg -> init_import_site" before
any code ran, so nothing bound 127.0.0.1:18790 and the gated hermes.<tld> upstream
was dead behind a healthy Authentik gate (the "Cloudflare error after login" the
operator hit, root-caused 2026-06-15).

Two halves of the fix are pinned here:
  1. external-paths.yml must NOT move hermes_venv (or any *_venv a daemon reads at
     startup) onto external_storage_root.
  2. The Hermes launchd reload must be a real bootout+bootstrap (NOT kickstart -k),
     because kickstart -k re-runs the EXISTING definition and never re-reads a
     changed ProgramArguments — which is exactly why a corrected plist sat
     un-applied while the live job kept the stale SSD venv path.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
EXT = (REPO / "tasks/stacks/external-paths.yml").read_text(encoding="utf-8")
HANDLER = (REPO / "roles/pazny.hermes/handlers/main.yml").read_text(encoding="utf-8")
TASKS = (REPO / "roles/pazny.hermes/tasks/main.yml").read_text(encoding="utf-8")


def test_no_venv_on_external_storage():
    # No *_venv may be set onto external_storage_root — a launchd interpreter
    # cannot read its venv from the TCC-blocked external volume at startup.
    import re
    for m in re.finditer(r"(\w*_venv)\s*:\s*\"?\{\{\s*external_storage_root", EXT):
        raise AssertionError(
            f"{m.group(1)} is set onto external_storage_root in external-paths.yml — "
            "a launchd venv on the external SSD is TCC-denied at startup"
        )


def test_hermes_paths_not_overridden_to_ssd():
    # The whole Hermes SSD override is gone (home + venv stay under $HOME).
    assert "hermes_venv: \"{{ external_storage_root }}" not in EXT
    assert "hermes_home: \"{{ external_storage_root }}" not in EXT


def test_restart_handler_does_a_real_reload():
    # The handler must bootout+bootstrap, never the no-op-on-changed kickstart -k.
    assert "launchctl bootout" in HANDLER and "launchctl bootstrap" in HANDLER, \
        "Restart hermes must bootout+bootstrap so a changed ProgramArguments reloads"
    assert "launchctl kickstart" not in HANDLER, \
        "kickstart never re-reads a changed plist — use bootout+bootstrap (a doc " \
        "comment mentioning kickstart is fine; the launchctl kickstart COMMAND is not)"


def test_bootstrap_task_reloads_on_changed_plist():
    # The bootstrap task must reload (not short-circuit 'already-loaded') when the
    # rendered plist changed.
    assert "_hermes_plist is changed" in TASKS, \
        "the bootstrap task must key its reload off the plist render's changed state"
    assert "reloaded" in TASKS and "launchctl bootout" in TASKS, \
        "a changed plist must trigger a bootout+bootstrap reload, not 'already-loaded'"
