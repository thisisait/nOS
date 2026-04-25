"""Every recipe file under upgrades/ must validate against the JSON Schema,
including the template and the example in the spec."""

from __future__ import absolute_import, division, print_function

import json
import os
import re

import pytest

from .conftest import ROOT, UPGRADES_DIR, SCHEMA_PATH


def _load_yaml(path):
    try:
        import yaml
    except ImportError:
        pytest.skip("PyYAML not installed")
    with open(path, "r") as fh:
        return yaml.safe_load(fh)


def _load_schema():
    with open(SCHEMA_PATH, "r") as fh:
        return json.load(fh)


def _recipe_files():
    out = []
    for name in sorted(os.listdir(UPGRADES_DIR)):
        if not (name.endswith(".yml") or name.endswith(".yaml")):
            continue
        path = os.path.join(UPGRADES_DIR, name)
        out.append(path)
    return out


def test_schema_is_valid_json():
    schema = _load_schema()
    assert schema["$schema"].startswith("http://json-schema.org/")
    assert schema["title"].startswith("nOS Upgrade")


def test_at_least_six_service_recipe_files():
    names = {os.path.basename(p) for p in _recipe_files()}
    # README not .yml so it's not in the list.
    required = {"_template.yml", "grafana.yml", "postgresql.yml",
                "mariadb.yml", "authentik.yml", "redis.yml", "infisical.yml"}
    missing = required - names
    assert not missing, "missing recipe files: %r" % missing


@pytest.mark.parametrize("path", _recipe_files())
def test_recipe_file_validates(path):
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")
    doc = _load_yaml(path)
    schema = _load_schema()
    jsonschema.validate(instance=doc, schema=schema)


@pytest.mark.parametrize("path", _recipe_files())
def test_recipe_file_basename_matches_service(path):
    base = os.path.splitext(os.path.basename(path))[0]
    if base == "_template":
        return
    doc = _load_yaml(path)
    assert doc["service"] == base, (
        "file %s declares service=%r (expected %r)" % (path, doc["service"], base)
    )


@pytest.mark.parametrize("path", _recipe_files())
def test_recipe_ids_unique_within_file(path):
    doc = _load_yaml(path)
    ids = [r["id"] for r in doc.get("recipes", [])]
    assert len(ids) == len(set(ids)), (
        "duplicate recipe ids in %s: %r" % (path, ids)
    )


def test_recipe_ids_unique_across_all_files():
    seen = {}
    for path in _recipe_files():
        if os.path.basename(path) == "_template.yml":
            continue
        doc = _load_yaml(path)
        for rec in doc.get("recipes", []):
            rid = rec["id"]
            assert rid not in seen, (
                "duplicate recipe id %r in %s (already in %s)"
                % (rid, path, seen[rid])
            )
            seen[rid] = path


@pytest.mark.parametrize("path", _recipe_files())
def test_recipe_from_regex_compiles(path):
    doc = _load_yaml(path)
    for rec in doc.get("recipes", []):
        try:
            re.compile(rec["from_regex"])
        except re.error as exc:
            raise AssertionError(
                "recipe %s in %s has invalid from_regex %r: %s"
                % (rec["id"], path, rec["from_regex"], exc)
            )


# ---------------------------------------------------------------------------
# Catalog smoke test — every step's `type:` in every recipe must resolve to
# a handler in merged_handlers() at runtime.  The JSON schema already guards
# the enum, but schema enum drift from the dispatcher has bitten us before;
# this is the runtime equivalent check that fails loudly in CI.

from module_utils.nos_upgrade_actions import merged_handlers  # noqa: E402


_HANDLER_KEYS = set(merged_handlers().keys())


def _steps(recipe):
    for phase in ("pre", "apply", "post", "rollback"):
        for step in recipe.get(phase) or []:
            yield phase, step


@pytest.mark.parametrize("path", _recipe_files())
def test_recipe_step_types_have_handlers(path):
    doc = _load_yaml(path)
    for rec in doc.get("recipes", []):
        for phase, step in _steps(rec):
            t = step.get("type")
            assert t in _HANDLER_KEYS, (
                "recipe %s step %s (%s.%s) uses type %r with no handler. "
                "Known handlers: %r"
                % (rec["id"], step.get("id", "?"), os.path.basename(path),
                   phase, t, sorted(_HANDLER_KEYS))
            )
