"""Gate: every executable migration record validates against the JSON Schema.

The migration twin of tests/upgrades/test_schema_validation.py. Runs as part of
the `tools/migration-pr.sh` validate phase, so the migration-author can never
open a forge MR for a record the engine would reject at load time.

Validates the records the engine actually executes (underscore-prefixed
_template.yml / _archived-*.yml are skipped — the discovery glob excludes them).
"""

from __future__ import absolute_import, division, print_function

import json
import os

import pytest

from .conftest import SCHEMA_PATH, load_yaml, migration_files


def _load_schema():
    with open(SCHEMA_PATH, "r") as fh:
        return json.load(fh)


def test_schema_is_valid_json():
    schema = _load_schema()
    assert schema["$schema"].startswith("http://json-schema.org/")
    assert schema["title"].startswith("nOS Migration")


@pytest.mark.parametrize("path", migration_files())
def test_migration_file_validates(path):
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    doc = load_yaml(path)
    schema = _load_schema()
    jsonschema.validate(instance=doc, schema=schema)


@pytest.mark.parametrize("path", migration_files())
def test_migration_id_matches_filename(path):
    """The engine rejects a record whose id != filename (nos_migrate list)."""
    base = os.path.splitext(os.path.basename(path))[0]
    doc = load_yaml(path)
    assert doc.get("id") == base, (
        "migration %s declares id=%r (expected %r — id MUST match the filename)"
        % (path, doc.get("id"), base)
    )


def test_migration_ids_unique_across_all_files():
    seen = {}
    for path in migration_files():
        doc = load_yaml(path)
        mid = doc.get("id")
        assert mid not in seen, (
            "duplicate migration id %r in %s (already in %s)"
            % (mid, path, seen.get(mid))
        )
        seen[mid] = path
