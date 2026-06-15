"""Test scaffolding for the migration-author gate set (B4a, 2026-06-16).

The migration twin of tests/upgrades/conftest.py. `tools/migration-pr.sh` runs
this whole package as the authoritative migration gate before opening a forge
MR, so the migration-author's write+MR path can only ship a record that:

  * validates against state/schema/migration.schema.json (test_schema_validation),
  * is idempotent — its applies_if + per-step detect/rollback hold the
    re-run-safety contract (test_idempotency),
  * carries no un-rendered {{ jinja }} token, because — UNLIKE upgrade recipes —
    the migration engine (module_utils/nos_migrate_engine.apply) does NOT
    Jinja-render step strings; it does literal field dispatch + ~ expansion. A
    stray {{ token }} would ship verbatim into a path/command at apply time
    (test_template_vars_resolvable).

Discovery skips underscore-prefixed files (the discovery glob the engine itself
uses: _template.yml + _archived-*.yml are not executable migrations).
"""

from __future__ import absolute_import, division, print_function

import glob
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MIGRATIONS_DIR = os.path.join(ROOT, "files", "anatomy", "migrations")
SCHEMA_PATH = os.path.join(ROOT, "state", "schema", "migration.schema.json")


def migration_files():
    """Executable migration records — the same set the engine discovers.

    Underscore-prefixed files (_template.yml, _archived-*.yml) are skipped:
    the engine's discovery glob excludes them, so they are not migrations.
    """
    out = []
    for path in sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.yml"))):
        if os.path.basename(path).startswith("_"):
            continue
        out.append(path)
    return out


def load_yaml(path):
    try:
        import yaml
    except ImportError:
        pytest.skip("PyYAML not installed")
    with open(path, "r") as fh:
        return yaml.safe_load(fh)
