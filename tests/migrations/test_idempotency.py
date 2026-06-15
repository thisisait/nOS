"""Gate: every executable migration record honours the idempotency contract.

`nos_migrate` re-runs on EVERY playbook invocation; a non-idempotent record
re-fires its actions on an already-migrated host (data loss, double-rename,
revert). The README authoring checklist (files/anatomy/migrations/README.md §3)
makes this structural:

  * applies_if is the idempotency hinge — present + non-empty, so the engine can
    gate the migration OUT once it has run.
  * every step carries a detect predicate (so the step is a no-op if already
    applied) — OR is an inherently-idempotent action (state.set / fs.ensure_dir /
    noop), which is safe to re-run unconditionally.
  * every step is reversible — a rollback action, OR an on_failure of
    continue/abort that documents the irreversibility (a destructive step with
    rollback rollback + no detect would re-fire AND have nothing to undo).

Runs in the `tools/migration-pr.sh` validate phase, so the migration-author
cannot open an MR for a record that would re-fire on the next run.
"""

from __future__ import absolute_import, division, print_function

import pytest

from .conftest import load_yaml, migration_files

# Actions safe to re-run unconditionally — a detect predicate is then optional.
_IDEMPOTENT_ACTIONS = {
    "state.set",
    "state.bump_schema_version",
    "fs.ensure_dir",
    "noop",
}


def test_at_least_the_template_and_schema_exist():
    """Sanity: the gate set is wired even before the first real record lands.

    A bare repo (no executable migration yet) still proves the schema + the
    authoring template are present, so migration-pr.sh has something to validate
    against. This keeps the gate green on an empty migrations/ dir (B4a ships the
    plumbing; the first real record is authored by the agent / pg16->17 run)."""
    from .conftest import MIGRATIONS_DIR, SCHEMA_PATH
    import os
    assert os.path.isfile(SCHEMA_PATH), "migration schema missing"
    assert os.path.isfile(os.path.join(MIGRATIONS_DIR, "_template.yml")), (
        "authoring template missing — migration-author models records on it"
    )


@pytest.mark.parametrize("path", migration_files())
def test_applies_if_present_and_non_empty(path):
    """applies_if is the idempotency hinge — it must be there and say something."""
    doc = load_yaml(path)
    applies = doc.get("applies_if")
    assert applies, (
        "migration %s has no applies_if — without the gate the engine cannot "
        "skip an already-migrated host (README §3: applies_if must be FALSE "
        "once applied)" % path
    )
    assert isinstance(applies, dict) and applies, (
        "migration %s applies_if is empty — define the gate predicate" % path
    )


@pytest.mark.parametrize("path", migration_files())
def test_every_step_is_idempotent_or_detected(path):
    """Each step either has a detect predicate (skips when already applied) or
    is an inherently-idempotent action."""
    doc = load_yaml(path)
    failures = []
    for step in doc.get("steps") or []:
        sid = step.get("id", "?")
        action_type = (step.get("action") or {}).get("type", "")
        has_detect = bool(step.get("detect"))
        if not has_detect and action_type not in _IDEMPOTENT_ACTIONS:
            failures.append(
                "%s: action %r has no detect predicate and is not "
                "inherently idempotent (%s)" % (sid, action_type,
                                                sorted(_IDEMPOTENT_ACTIONS))
            )
    assert not failures, (
        "migration %s has non-idempotent step(s):\n  - %s"
        % (path, "\n  - ".join(failures))
    )


@pytest.mark.parametrize("path", migration_files())
def test_every_step_is_reversible_or_documented(path):
    """Each step declares a rollback action, OR an on_failure of continue/abort
    that documents it doesn't auto-revert. A bare step (default on_failure
    rollback, no rollback block) would try to roll back nothing."""
    doc = load_yaml(path)
    failures = []
    for step in doc.get("steps") or []:
        sid = step.get("id", "?")
        has_rollback = bool(step.get("rollback"))
        on_failure = step.get("on_failure", "rollback")
        if not has_rollback and on_failure == "rollback":
            failures.append(
                "%s: default on_failure=rollback but no rollback action — "
                "either add a rollback: block, a noop rollback with a reason, "
                "or set on_failure: continue|abort" % sid
            )
    assert not failures, (
        "migration %s has irreversible step(s) with no rollback contract:\n  - %s"
        % (path, "\n  - ".join(failures))
    )
