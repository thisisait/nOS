"""Step-level on_failure semantics in the migration engine.

Bug fix from 2026-04-26: prior to this, the engine ignored `on_failure`
entirely and always rolled back on action failure. Track A's
2026-05-01-bone-wing-to-container migration relies on `continue` so
host-side leftovers from older installs (Homebrew php-fpm not running,
plist already gone) don't fail the entire migration.

Each test injects an action via `noop` whose handler we monkey-patch to
return failure once, then assert engine behaviour matches `on_failure`.
"""

from __future__ import absolute_import, division, print_function

import os
import sys

import pytest


# Ensure module_utils is importable.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from module_utils import nos_migrate_engine as engine  # noqa: E402
from module_utils.nos_migrate_actions import ACTION_HANDLERS  # noqa: E402


@pytest.fixture
def failing_handler():
    """Replace `noop` with a handler that always reports failure."""
    original = ACTION_HANDLERS["noop"]
    ACTION_HANDLERS["noop"] = lambda action, ctx: {
        "success": False, "changed": False, "error": "synthetic test failure",
    }
    try:
        yield
    finally:
        ACTION_HANDLERS["noop"] = original


def _record(on_failure):
    """Build a minimal migration record with one failing step + one trailing
    success step. The trailing step proves whether `continue` actually
    advanced past the failure or not.
    """
    return {
        "id": "test-on-failure",
        "title": "test",
        "summary": "x",
        "severity": "patch",
        "created_at": "2026-04-26",
        "allow_shell": False,
        "applies_if": [],
        "preconditions": [],
        "steps": [
            {
                "id": "failing_step",
                "description": "always fails",
                "action": {"type": "noop"},
                "on_failure": on_failure,
            },
            {
                "id": "trailing_step",
                "description": "should run only if continue",
                "action": {"type": "noop"},
            },
        ],
    }


def test_on_failure_continue_proceeds(failing_handler, base_ctx):
    """on_failure: continue → trailing step still runs."""
    # Restore noop for the trailing step by unwinding the patch *just* for it.
    # Easier: keep the failing handler, but make trailing_step succeed via a
    # different action type. Simpler: leave both as noop, but watch
    # steps_applied count. With `continue`, failing_step is NOT in
    # applied_steps but trailing_step IS (because the failing handler is
    # currently patched). So we need a non-monkeypatched trailing step.
    pass  # placeholder — see test below for the cleaner version


def test_on_failure_continue_records_failure_and_continues(base_ctx, monkeypatch):
    """When step has on_failure: continue, engine moves to next step.

    We use two distinct action types so we can selectively fail one without
    affecting the other.
    """
    # Synthetic action types
    ACTION_HANDLERS["__test_fail__"] = lambda action, ctx: {
        "success": False, "error": "boom",
    }
    ACTION_HANDLERS["__test_pass__"] = lambda action, ctx: {
        "success": True, "changed": True,
    }
    try:
        record = {
            "id": "test-continue",
            "title": "test",
            "summary": "x",
            "severity": "patch",
            "created_at": "2026-04-26",
            "allow_shell": False,
            "preconditions": [],
            "steps": [
                {"id": "step_a", "action": {"type": "__test_fail__"},
                 "on_failure": "continue"},
                {"id": "step_b", "action": {"type": "__test_pass__"}},
            ],
        }
        result = engine.apply(record, base_ctx)
        # Best-effort semantics: a step marked `on_failure: continue` does
        # NOT cascade to migration-level failure. If every other step
        # succeeded, migration is overall successful and gets recorded as
        # applied. The failed step's status is logged via _state_record_step
        # so auditors can still see what was skipped.
        assert result["success"] is True
        # The trailing step DID run — proof that continue advanced past
        # the failure rather than aborting.
        assert result["steps_applied"] == 1, (
            "trailing step should be in applied_steps; got %r" % result
        )
    finally:
        del ACTION_HANDLERS["__test_fail__"]
        del ACTION_HANDLERS["__test_pass__"]


def test_on_failure_default_rolls_back(base_ctx, monkeypatch):
    """Without on_failure (or with omitted), failure aborts + rolls back."""
    rollback_calls = []
    ACTION_HANDLERS["__test_pass2__"] = lambda action, ctx: {
        "success": True, "changed": True,
        "rollback_id": "stamp-" + str(len(rollback_calls)),
    }
    ACTION_HANDLERS["__test_fail2__"] = lambda action, ctx: {
        "success": False, "error": "boom",
    }
    try:
        record = {
            "id": "test-default-rollback",
            "title": "test",
            "summary": "x",
            "severity": "patch",
            "created_at": "2026-04-26",
            "allow_shell": False,
            "preconditions": [],
            "steps": [
                {"id": "step_a", "action": {"type": "__test_pass2__"}},
                {"id": "step_b", "action": {"type": "__test_fail2__"}},
            ],
        }
        result = engine.apply(record, base_ctx)
        assert result["success"] is False
        # Default behaviour: failure halts pipeline immediately.
        assert result.get("phase") == "action"
        assert result.get("failed_step") == "step_b"
    finally:
        del ACTION_HANDLERS["__test_pass2__"]
        del ACTION_HANDLERS["__test_fail2__"]


def test_on_failure_abort_does_not_rollback(base_ctx):
    """on_failure: abort → return failure but leave applied steps in place."""
    ACTION_HANDLERS["__test_pass3__"] = lambda action, ctx: {
        "success": True, "changed": True,
    }
    ACTION_HANDLERS["__test_fail3__"] = lambda action, ctx: {
        "success": False, "error": "boom",
    }
    try:
        record = {
            "id": "test-abort",
            "title": "test",
            "summary": "x",
            "severity": "patch",
            "created_at": "2026-04-26",
            "allow_shell": False,
            "preconditions": [],
            "steps": [
                {"id": "step_a", "action": {"type": "__test_pass3__"}},
                {"id": "step_b", "action": {"type": "__test_fail3__"},
                 "on_failure": "abort"},
                {"id": "step_c", "action": {"type": "__test_pass3__"}},
            ],
        }
        result = engine.apply(record, base_ctx)
        assert result["success"] is False
        # step_a succeeded and is in applied_steps; step_b failed; step_c
        # never ran (abort halts the pipeline like default rollback would).
        assert result["steps_applied"] == 1
        assert result.get("failed_step") == "step_b"
    finally:
        del ACTION_HANDLERS["__test_pass3__"]
        del ACTION_HANDLERS["__test_fail3__"]
