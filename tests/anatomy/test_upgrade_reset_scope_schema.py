"""Anatomy CI gate — the optional `reset` block on upgrade recipes (and the
mirror block on migration records) carries a valid blast-radius `scope`.

Phase 1 of docs/plans/upgrade-reset-scope-and-session-safety.md. The engine
DERIVES a floor from the step/action types and ESCALATES the authored scope to
it (authored may only raise the floor, never lower it). This gate pins the
static contract that the schema layer owns:

  * the JSON schema files themselves stay well-formed and load;
  * the `reset` definition is present in both schemas with the 5-level enum;
  * `reset` is OPTIONAL on every recipe / migration;
  * when a recipe / migration DOES author `reset`, its `scope` is one of the
    five valid enum values (none/container/stack/host_app/host_reboot).

The "authored never below the derived floor" assertion runs at engine-resolve
time (resolve_reset escalates) and is exercised by the engine-side gate; here we
pin the enum + optionality + schema validity, which is the schema layer's job.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

try:
    import jsonschema
    _JSONSCHEMA_AVAILABLE = True
except ImportError:
    _JSONSCHEMA_AVAILABLE = False


REPO_ROOT = Path(__file__).resolve().parents[2]
UPGRADE_SCHEMA_PATH = REPO_ROOT / "state" / "schema" / "upgrade.schema.json"
MIGRATION_SCHEMA_PATH = REPO_ROOT / "state" / "schema" / "migration.schema.json"
UPGRADES_DIR = REPO_ROOT / "upgrades"
MIGRATIONS_DIR = REPO_ROOT / "files" / "anatomy" / "migrations"

VALID_SCOPES = {"none", "container", "stack", "host_app", "host_reboot"}


def _load_json(path: Path) -> dict:
    with open(path) as fh:
        return json.load(fh)


def _recipe_files() -> list[Path]:
    if not UPGRADES_DIR.is_dir():
        return []
    return [
        p
        for p in sorted(UPGRADES_DIR.glob("*.yml"))
        if p.name not in ("_template.yml",)
    ]


def _migration_files() -> list[Path]:
    if not MIGRATIONS_DIR.is_dir():
        return []
    return [
        p
        for p in sorted(MIGRATIONS_DIR.glob("*.yml"))
        if not p.name.startswith("_") and p.name != "README.md"
    ]


# --------------------------------------------------------------------------- #
# Schema validity + the reset definition itself
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def upgrade_schema() -> dict:
    if not UPGRADE_SCHEMA_PATH.is_file():
        pytest.skip(f"schema not found at {UPGRADE_SCHEMA_PATH}")
    return _load_json(UPGRADE_SCHEMA_PATH)


@pytest.fixture(scope="module")
def migration_schema() -> dict:
    if not MIGRATION_SCHEMA_PATH.is_file():
        pytest.skip(f"schema not found at {MIGRATION_SCHEMA_PATH}")
    return _load_json(MIGRATION_SCHEMA_PATH)


def test_upgrade_schema_loads(upgrade_schema):
    """Static sanity: the upgrade schema is well-formed draft-07 JSON."""
    assert upgrade_schema.get("$schema") == "http://json-schema.org/draft-07/schema#"
    assert "definitions" in upgrade_schema


def test_migration_schema_loads(migration_schema):
    """Static sanity: the migration schema is well-formed draft-07 JSON."""
    assert migration_schema.get("$schema") == "http://json-schema.org/draft-07/schema#"


@pytest.mark.skipif(not _JSONSCHEMA_AVAILABLE, reason="jsonschema not installed")
def test_upgrade_schema_is_a_valid_jsonschema(upgrade_schema):
    """The schema file is itself a legal JSON Schema (meta-validates)."""
    jsonschema.Draft7Validator.check_schema(upgrade_schema)


@pytest.mark.skipif(not _JSONSCHEMA_AVAILABLE, reason="jsonschema not installed")
def test_migration_schema_is_a_valid_jsonschema(migration_schema):
    """The schema file is itself a legal JSON Schema (meta-validates)."""
    jsonschema.Draft7Validator.check_schema(migration_schema)


def test_upgrade_reset_definition_present(upgrade_schema):
    """The shared reset definition exists with the 5-level scope enum and is
    referenced from definitions.recipe.properties (recipe.additionalProperties
    is false, so the key MUST be declared or every authored reset is rejected)."""
    reset = upgrade_schema["definitions"].get("reset")
    assert reset, "upgrade schema lost definitions.reset"
    assert reset["required"] == ["scope"]
    assert reset["additionalProperties"] is False
    assert set(reset["properties"]["scope"]["enum"]) == VALID_SCOPES

    recipe_props = upgrade_schema["definitions"]["recipe"]["properties"]
    assert recipe_props.get("reset") == {"$ref": "#/definitions/reset"}, (
        "recipe must $ref the shared reset definition (recipe.additionalProperties"
        " is false — the key has to be declared)"
    )


def test_migration_reset_block_present(migration_schema):
    """The migration root carries its own reset block (root.additionalProperties
    is false) and keeps `downtime` as the legacy folded-in alias."""
    props = migration_schema["properties"]
    reset = props.get("reset")
    assert reset, "migration schema lost root.reset"
    assert reset["required"] == ["scope"]
    assert reset["additionalProperties"] is False
    assert set(reset["properties"]["scope"]["enum"]) == VALID_SCOPES

    # downtime MUST survive — the loader folds it into reset for back-compat.
    assert "downtime" in props, "migration `downtime` alias must not be removed"


# --------------------------------------------------------------------------- #
# reset is optional, and every authored scope is a valid enum value
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not _JSONSCHEMA_AVAILABLE, reason="jsonschema not installed")
def test_recipe_files_validate_against_schema(upgrade_schema):
    """Every shipped recipe file still validates — proves `reset` is optional
    (the files don't carry it yet) and the schema change is non-breaking."""
    failures = []
    for path in _recipe_files():
        with open(path) as fh:
            data = yaml.safe_load(fh)
        try:
            jsonschema.validate(data, upgrade_schema)
        except jsonschema.ValidationError as exc:
            failures.append(f"{path.name}: {exc.message} (at {list(exc.absolute_path)})")
    assert not failures, "recipe schema validation failures:\n  - " + "\n  - ".join(failures)


@pytest.mark.skipif(not _JSONSCHEMA_AVAILABLE, reason="jsonschema not installed")
def test_migration_files_validate_against_schema(migration_schema):
    """Every shipped migration record still validates against the schema."""
    failures = []
    for path in _migration_files():
        with open(path) as fh:
            data = yaml.safe_load(fh)
        try:
            jsonschema.validate(data, migration_schema)
        except jsonschema.ValidationError as exc:
            failures.append(f"{path.name}: {exc.message} (at {list(exc.absolute_path)})")
    assert not failures, "migration schema validation failures:\n  - " + "\n  - ".join(failures)


def test_authored_recipe_reset_scope_is_valid_enum():
    """When a recipe authors `reset`, its scope is one of the 5 valid values.
    Walks every recipe in every file (a file holds recipes[])."""
    offenders = []
    for path in _recipe_files():
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        for recipe in data.get("recipes") or []:
            if not isinstance(recipe, dict):
                continue
            reset = recipe.get("reset")
            if reset is None:
                continue  # optional — fine
            scope = reset.get("scope")
            if scope not in VALID_SCOPES:
                offenders.append(
                    f"{path.name}::{recipe.get('id', '?')}: reset.scope "
                    f"'{scope}' not in {sorted(VALID_SCOPES)}"
                )
    assert not offenders, "invalid reset.scope:\n  - " + "\n  - ".join(offenders)


def test_authored_migration_reset_scope_is_valid_enum():
    """When a migration authors `reset`, its scope is a valid enum value."""
    offenders = []
    for path in _migration_files():
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        reset = data.get("reset")
        if reset is None:
            continue  # optional — fine
        scope = reset.get("scope")
        if scope not in VALID_SCOPES:
            offenders.append(
                f"{path.name}: reset.scope '{scope}' not in {sorted(VALID_SCOPES)}"
            )
    assert not offenders, "invalid reset.scope:\n  - " + "\n  - ".join(offenders)


@pytest.mark.skipif(not _JSONSCHEMA_AVAILABLE, reason="jsonschema not installed")
def test_reset_is_optional_minimal_recipe_validates(upgrade_schema):
    """A recipe with NO reset block validates — `reset` is never required."""
    minimal = {
        "service": "demo",
        "recipes": [
            {
                "id": "demo-1-to-2",
                "from_regex": "^1\\.",
                "to": "2.0.0",
                "severity": "minor",
            }
        ],
    }
    jsonschema.validate(minimal, upgrade_schema)  # must not raise


@pytest.mark.skipif(not _JSONSCHEMA_AVAILABLE, reason="jsonschema not installed")
def test_authored_reset_below_floor_is_rejected_by_value_not_schema(upgrade_schema):
    """The schema accepts any valid-enum scope (escalation happens at runtime,
    not via schema rejection): a recipe whose authored scope is 'none' but whose
    apply step is a container-floor op still passes the SCHEMA — the engine's
    resolve_reset is what escalates it. This pins the doctrine boundary: the
    schema gate enforces the enum + optionality; the floor is a runtime concern."""
    recipe = {
        "service": "demo",
        "recipes": [
            {
                "id": "demo-1-to-2",
                "from_regex": "^1\\.",
                "to": "2.0.0",
                "severity": "minor",
                "reset": {"scope": "none"},
                "apply": [
                    {"id": "bump", "type": "compose.set_image_tag",
                     "service": "demo", "tag": "2.0.0"}
                ],
            }
        ],
    }
    jsonschema.validate(recipe, upgrade_schema)  # schema-valid; runtime escalates
