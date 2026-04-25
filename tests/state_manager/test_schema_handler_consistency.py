"""Schema ↔ handler consistency guard.

Two bugs that have bitten us before:

  1. A schema enum lists an action type with no registered handler.
     YAML files validate, but ``nos_migrate apply`` crashes with
     ``KeyError: Unknown migration action type``.
  2. A handler is registered but the schema doesn't list its type.
     The action can never be used in a well-formed record — dead code.

This test checks both directions for the migration schema + handlers,
and one direction for the upgrade schema (schema ⊆ handlers — extras in
``merged_handlers`` are migration-only and deliberately excluded from the
upgrade schema).
"""

from __future__ import absolute_import, division, print_function

import json
import os

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MIGRATION_SCHEMA = os.path.join(ROOT, "state", "schema", "migration.schema.json")
UPGRADE_SCHEMA = os.path.join(ROOT, "state", "schema", "upgrade.schema.json")


def _schema_enum(schema_path, *json_path):
    with open(schema_path) as fh:
        node = json.load(fh)
    for key in json_path:
        node = node[key]
    return set(node["enum"])


def _migration_schema_types():
    return _schema_enum(MIGRATION_SCHEMA,
                        "definitions", "action", "properties", "type")


def _upgrade_schema_types():
    return _schema_enum(UPGRADE_SCHEMA,
                        "definitions", "step", "properties", "type")


# ---------------------------------------------------------------------------
# Migration: strict parity — schema enum == registered handler keys.

def test_migration_schema_matches_handlers():
    from module_utils.nos_migrate_actions import ACTION_HANDLERS

    schema = _migration_schema_types()
    handlers = set(ACTION_HANDLERS.keys())

    in_schema_not_registered = schema - handlers
    registered_not_in_schema = handlers - schema

    msg_parts = []
    if in_schema_not_registered:
        msg_parts.append(
            "action types in migration.schema.json with NO handler "
            "(YAML would validate but runtime crashes): %r"
            % sorted(in_schema_not_registered)
        )
    if registered_not_in_schema:
        msg_parts.append(
            "handlers registered in ACTION_HANDLERS but missing from "
            "migration.schema.json enum (action unreachable from YAML): %r"
            % sorted(registered_not_in_schema)
        )
    assert not msg_parts, "\n".join(msg_parts)


# ---------------------------------------------------------------------------
# Upgrade: schema enum ⊆ merged handlers.  Extras in merged_handlers are
# migration-only types that upgrade recipes are not supposed to use, so we
# don't require full symmetry on this side.

def test_upgrade_schema_subset_of_merged_handlers():
    from module_utils.nos_upgrade_actions import merged_handlers

    schema = _upgrade_schema_types()
    handlers = set(merged_handlers().keys())

    missing = schema - handlers
    assert not missing, (
        "action types in upgrade.schema.json with NO handler in "
        "merged_handlers (recipe would validate but crash at apply): %r"
        % sorted(missing)
    )


# ---------------------------------------------------------------------------
# Guard: the upgrade-specific handler set must not silently shadow a
# migration handler of the same name — if a collision ever happens we want
# a deliberate choice, not a silent override.

def test_no_handler_name_collisions():
    from module_utils.nos_migrate_actions import ACTION_HANDLERS as MIG
    from module_utils.nos_upgrade_actions import UPGRADE_ACTION_HANDLERS as UPG

    overlap = set(MIG.keys()) & set(UPG.keys())
    assert not overlap, (
        "action type(s) registered in both migration and upgrade handler "
        "tables — merged_handlers() would silently prefer the upgrade one: %r"
        % sorted(overlap)
    )
