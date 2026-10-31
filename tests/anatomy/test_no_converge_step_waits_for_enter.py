"""A converge never waits for ENTER unless the operator asked for the step.

2026-10-30: the converge after a blank stopped at "[Verify] Manual onboarding
required ... press ENTER" (Kiwix, ZIM dir wiped). A blank needs zero manual
steps. Parsed, not grepped: every `pause` task without seconds/minutes in
tasks/, roles/*/tasks|handlers and main.yml is an interactive prompt, and each
one must be a named confirmation of an operation the operator chose.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]

# (file, task name) -> why it may wait. Each is a confirm gate with its own
# opt-out (nos_assume_yes / auto_* / *_confirm), or a failure path (open).
ALLOWED = {
    ("main.yml", "[Prefix] Prompt for password prefix (interactive confirmed removal)"):
        "remove=… --confirm, skipped by nos_assume_yes",
    ("tasks/blank-reset.yml", "[BLANK/FLUSH] Confirm destructive operation"):
        "remove=… --confirm, skipped by nos_assume_yes",
    ("tasks/remove-source.yml", "[Remove:source] Final interactive confirmation"):
        "remove=all, skipped by nos_assume_yes",
    ("tasks/restore.yml", "[Restore] Interactive confirmation (operator must press ENTER)"):
        "restore is operator-invoked, skipped by restore_auto_confirm",
    ("tasks/pre-migrate.yml", "[pre-migrate] Confirm breaking migrations"):
        "breaking migration, skipped by auto_migrate",
    ("tasks/upgrade-engine.yml", "[Upgrade] Confirm breaking upgrades"):
        "breaking upgrade, skipped by auto_upgrade",
    ("tasks/upgrade-engine.yml", "[Upgrade] Confirm session-risk upgrades (host_app / host_reboot)"):
        "host app / reboot upgrade, skipped by auto_migrate / upgrade_confirmed",
    ("tasks/iiab/docker-prereqs.yml", "[Docker] Docker binary not found - waiting for manual fix"):
        "failure path (no Docker); should fail instead — open",
    ("tasks/iiab/docker-prereqs.yml", "[Docker] Docker daemon not responding - waiting for manual fix"):
        "failure path (daemon down); should fail instead — open",
    ("roles/pazny.mariadb/tasks/post.yml", "[pazny.mariadb Post] Connection failed - diagnostics"):
        "failure path (root pw mismatch); should fail instead — open",
}


def _files():
    yield REPO / "main.yml"
    yield from (REPO / "tasks").rglob("*.yml")
    for sub in ("tasks", "handlers"):
        yield from (REPO / "roles").glob(f"*/{sub}/**/*.yml")


def _tasks(node):
    if isinstance(node, list):
        for t in node:
            yield from _tasks(t)
    elif isinstance(node, dict):
        yield node
        for k in ("block", "rescue", "always", "tasks", "pre_tasks", "post_tasks", "handlers"):
            yield from _tasks(node.get(k))


def _interactive_pauses():
    found = set()
    for f in _files():
        for t in _tasks(yaml.safe_load(f.read_text(encoding="utf-8"))):
            if "ansible.builtin.pause" not in t and "pause" not in t:
                continue
            args = t.get("ansible.builtin.pause", t.get("pause"))
            if isinstance(args, dict) and ("seconds" in args or "minutes" in args):
                continue  # a timed sleep, not a prompt
            found.add((str(f.relative_to(REPO)), t.get("name")))
    return found


def test_no_converge_step_waits_for_enter():
    found = _interactive_pauses()
    assert len(found) >= 5, f"the scan lost the tree: only {sorted(found)}"
    stray = sorted(found - ALLOWED.keys())
    assert not stray, (
        "these tasks stop the converge for ENTER; report a warning instead, "
        f"or name the opt-in confirmation here with its reason: {stray}")
    stale = sorted(ALLOWED.keys() - found)
    assert not stale, f"allowed but no longer a prompt — drop from ALLOWED: {stale}"
