"""Dry-run now VALIDATES — it is no longer a blanket false-positive.

Before 2026-06-08, ``nos_migrate._apply_upgrade`` short-circuited every
dry-run to ``success`` BEFORE any handler ran, so a broken recipe (missing
override, ungated ``exec.shell``, unrenderable token) "passed" dry-run and
only blew up on the real apply. That short-circuit is gone; dry-run now
threads ``dry_run`` into each handler, which validates its inputs and THEN
skips the mutation.

These tests pin that property at the handler level (the mechanism the engine
fix relies on): a dry-run with BAD inputs must FAIL, and a dry-run with GOOD
inputs must succeed WITHOUT mutating anything.
"""

from __future__ import absolute_import, division, print_function

import os

from module_utils.nos_upgrade_actions import compose_ops
from module_utils.nos_migrate_actions import exec_shell as strict_exec


def _ctx(tmp_path, **extra):
    ctx = {"dry_run": True, "stacks_dir": str(tmp_path / "stacks"), "vars": {}}
    ctx.update(extra)
    return ctx


def test_dry_run_fails_on_missing_override(tmp_path):
    # compose.set_image_tag must FAIL (not silently pass) when the override
    # file doesn't exist — even on a dry-run. This is the exact false-positive
    # the old short-circuit masked.
    res = compose_ops.handle_set_image_tag(
        {"id": "bump", "type": "compose.set_image_tag",
         "stack": "infra", "service": "ghost", "tag": "v2"},
        _ctx(tmp_path))
    assert res["success"] is False
    assert "not found" in res["error"]


def test_dry_run_no_mutation_on_valid_override(tmp_path):
    # A present override with a different tag: dry-run reports it WOULD change
    # but writes nothing (and runs no docker command).
    ov_dir = tmp_path / "stacks" / "infra" / "overrides"
    os.makedirs(str(ov_dir))
    ov = ov_dir / "redis.yml"
    original = "services:\n  redis:\n    image: redis:7.2\n"
    ov.write_text(original)
    res = compose_ops.handle_set_image_tag(
        {"id": "bump", "type": "compose.set_image_tag",
         "stack": "infra", "service": "redis", "tag": "7.4"},
        _ctx(tmp_path))
    assert res["success"] is True
    assert ov.read_text() == original   # untouched — dry-run mutated nothing


def test_dry_run_exec_shell_still_enforces_gates(tmp_path):
    # exec.shell with a string cmd but NO allow_shell gates must fail on a
    # dry-run too — the default-reject gate runs BEFORE the would_exec return.
    res = strict_exec.handle_exec_shell(
        {"id": "x", "type": "exec.shell", "cmd": "echo hi", "shell": True},
        _ctx(tmp_path, migration_allows_shell=False))
    assert res["success"] is False
    assert "allow_shell" in res["error"]


def test_dry_run_exec_shell_would_exec_when_gated(tmp_path):
    # Properly gated exec.shell on a dry-run: reports would_exec, runs nothing.
    res = strict_exec.handle_exec_shell(
        {"id": "x", "type": "exec.shell", "cmd": "echo hi", "shell": True,
         "allow_shell": True},
        _ctx(tmp_path, migration_allows_shell=True))
    assert res["success"] is True
    assert res["result"].get("would_exec") is True
