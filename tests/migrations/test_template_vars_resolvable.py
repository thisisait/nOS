"""Gate: no un-rendered ``{{ jinja }}`` token survives in a migration record.

This is the migration counterpart of the upgrade-recipe
test_template_vars_resolvable, but with the OPPOSITE remedy — and that
difference is the whole point of the gate.

The UPGRADE engine (nos_migrate._apply_upgrade) renders recipe step strings
through Jinja2 with StrictUndefined + the controller's play-vars (tmpl_vars), so
``{{ postgresql_data_dir }}`` resolves at apply time. The MIGRATION engine
(module_utils/nos_migrate_engine.apply) does NOT: it dispatches each action's
literal fields (src/dst/path/command) to a handler and does ``~`` expansion only
— there is NO Jinja render pass. So a ``{{ token }}`` left in a migration record
ships verbatim into a filesystem path or a shell command (e.g. ``rm -rf {{
postgresql_data_dir }}/*`` would try to delete a literal ``{{`` directory).

Therefore the migration-author MUST resolve any service-specific path/port to a
concrete literal (or a ``~``-relative path the engine expands) when it promotes
a recipe into a migration record — it cannot copy the recipe's ``{{ }}`` tokens
verbatim. This gate fails the forge MR (run inside tools/migration-pr.sh) if a
token slips through.
"""

from __future__ import absolute_import, division, print_function

import re

import pytest

from .conftest import load_yaml, migration_files

_JINJA = re.compile(r"\{\{.*?\}\}", re.S)


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


@pytest.mark.parametrize("path", migration_files())
def test_no_unrendered_jinja_tokens(path):
    """The migration engine does not Jinja-render — a {{ token }} would ship
    literal into a path/command. Resolve it to a concrete value before merge."""
    doc = load_yaml(path)
    offenders = []
    for s in _strings(doc):
        for m in _JINJA.findall(s):
            offenders.append("%s  (in: %r)" % (m.strip(), s.strip()[:80]))
    assert not offenders, (
        "migration %s carries un-rendered Jinja token(s) — the migration "
        "engine does NOT render them (unlike upgrade recipes); resolve each to "
        "a concrete literal or a ~-relative path:\n  - %s"
        % (path, "\n  - ".join(offenders))
    )
