"""Gate: every executable migration carries a floor-consistent reset block.

The migration twin of the recipe consistency gate
(tests/anatomy/test_upgrade_reset_floor.py::test_shipped_recipes_author_scope_at_or_above_floor).
Runs in the `tools/migration-pr.sh` validate phase (which executes this whole
package), so the migration-author agent can never open a forge MR for a record
whose authored `reset.scope` understates the blast radius its own step actions
imply. This is the deterministic, LLM-independent guarantee behind Phase-4 reset
propagation: the agent is instructed to carry the recipe's reset, and this gate
enforces it regardless of the agent's compliance.

No live migrations exist yet (only _template/_archived, which discovery skips),
so this is a forward guard — it activates the moment a real migration is authored.
"""

from __future__ import absolute_import, division, print_function

import os
import sys

import pytest

from .conftest import ROOT, load_yaml, migration_files

# module_utils lives under files/anatomy/ — same import shim the anatomy tests use.
_MODUTILS = os.path.join(ROOT, "files", "anatomy")
if _MODUTILS not in sys.path:
    sys.path.insert(0, _MODUTILS)

try:
    from module_utils.nos_upgrade_actions.reset_scope import (  # noqa: E402
        SCOPE_RANK,
        derive_floor,
    )
    _HAVE_RESET_SCOPE = True
except Exception:  # noqa: BLE001
    _HAVE_RESET_SCOPE = False


def test_shipped_migrations_reset_scope_at_or_above_floor():
    """A migration that AUTHORS reset must author scope >= its derived floor; a
    migration that OMITS reset must derive a floor <= 'container' (a session-risk
    migration must declare reset so the confirmation / detached path is offered)."""
    if not _HAVE_RESET_SCOPE:
        pytest.skip("reset_scope helper unavailable")
    offenders = []
    for path in migration_files():
        doc = load_yaml(path) or {}
        if not isinstance(doc, dict):
            continue
        name = os.path.basename(path)
        floor = derive_floor(doc)
        reset = doc.get("reset")
        if not isinstance(reset, dict):
            if SCOPE_RANK[floor] > SCOPE_RANK["container"]:
                offenders.append(
                    "%s omits reset but derives floor '%s' (> container) — a "
                    "session-risk migration must author an explicit reset block" % (name, floor)
                )
            continue
        authored = reset.get("scope")
        if authored not in SCOPE_RANK or SCOPE_RANK[authored] < SCOPE_RANK[floor]:
            offenders.append(
                "%s authored reset.scope '%s' < derived floor '%s'" % (name, authored, floor)
            )
    assert not offenders, (
        "migration reset.scope would understate the blast radius:\n  - "
        + "\n  - ".join(offenders)
    )
