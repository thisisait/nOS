"""Anatomy CI gate — face config DataTable definitions.

The shell's chrome (layouts / wallpapers / control-panel entries) is DataTable-
driven: repo defaults (SoC) + KEAP rows + per-user state. The three config table
defs in state/keap-tables/ must mirror the apps/systems DataTable shape and each
must be paired with a seeder so a def can't ship without landing in KEAP.
Doctrine: docs/doctrine/face.md, docs/plans/nos-face-shell-v2.md.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TABLES = REPO / "state" / "keap-tables"
CONFIG_TABLES = ["layouts", "wallpapers", "controls"]


def _load(name: str) -> dict:
    raw = (TABLES / f"{name}.table.yml").read_text(encoding="utf-8")
    return yaml.safe_load(re.sub(r"\{\{[^}]+\}\}", "TEMPLATE", raw)) or {}


@pytest.mark.parametrize("name", CONFIG_TABLES)
def test_config_table_def_exists_and_parses(name):
    f = TABLES / f"{name}.table.yml"
    assert f.is_file(), f"missing config DataTable def {f.relative_to(REPO)}"
    d = _load(name)
    assert isinstance(d, dict) and d, f"{name}.table.yml did not parse to a mapping"


@pytest.mark.parametrize("name", CONFIG_TABLES)
def test_config_table_mirrors_catalog_shape(name):
    """Same spine as apps.table.yml / systems.table.yml."""
    d = _load(name)
    for key in ("title", "description", "driver", "visibility", "schema"):
        assert key in d, f"{name}.table.yml missing top-level '{key}'"
    assert d["driver"] == "libsql", f"{name}.table.yml driver must be libsql"
    cols = (d.get("schema") or {}).get("columns")
    assert cols, f"{name}.table.yml has no schema.columns"
    for col in cols:
        assert "key" in col and "kind" in col, f"{name} column missing key/kind: {col}"
    keys = {c["key"] for c in cols}
    assert "slug" in keys, f"{name}.table.yml must have a 'slug' column (row identity)"


def test_config_tables_have_a_seeder():
    seeders = list((REPO / "roles" / "pazny.keap" / "tasks").glob("seed-face-table*.yml"))
    assert seeders, "no KEAP seeder for the face config DataTables"
    blob = "".join(p.read_text(encoding="utf-8") for p in seeders)
    for name in CONFIG_TABLES:
        assert name in blob, f"seeder does not reference the {name} table"
