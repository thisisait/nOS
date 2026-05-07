"""Anatomy CI gate — every files/anatomy/agents/<name>/agent.yml must validate
against state/schema/agent.schema.yaml (A14, 2026-05-07).

The PHP runtime (App\\AgentKit\\AgentLoader) re-validates at load time, but
this Python-side gate fires earlier in the lifecycle (every CI push, no
PHP needed) so a broken agent.yml never lands on master.

Also asserts:
  * agent.yml::name matches the directory name
  * system_prompt_path / outcomes.rubric_path point at files that exist
  * model URI scheme matches `^(anthropic|openclaw|openai|local)-[a-z0-9.-]+$`
  * capability_scopes is non-empty
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

try:
    import jsonschema
    _JSONSCHEMA_AVAILABLE = True
except ImportError:
    _JSONSCHEMA_AVAILABLE = False


REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / "files" / "anatomy" / "agents"
SCHEMA_PATH = REPO_ROOT / "state" / "schema" / "agent.schema.yaml"

_MODEL_URI_RE = re.compile(r"^(anthropic|openclaw|openai|local)-[a-z0-9.-]+$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,38}[a-z0-9]$")


def _all_agent_yml_paths() -> list[tuple[str, Path]]:
    """Returns (name, path) tuples — name is the directory."""
    if not AGENTS_DIR.is_dir():
        return []
    out = []
    for entry in sorted(AGENTS_DIR.iterdir()):
        agent_yml = entry / "agent.yml"
        if entry.is_dir() and agent_yml.is_file():
            out.append((entry.name, agent_yml))
    return out


@pytest.fixture(scope="module")
def schema():
    if not SCHEMA_PATH.is_file():
        pytest.skip(f"schema not found at {SCHEMA_PATH}")
    with open(SCHEMA_PATH) as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def agent_paths():
    paths = _all_agent_yml_paths()
    if not paths:
        pytest.skip(f"no agents under {AGENTS_DIR}")
    return paths


def test_schema_loads(schema):
    """Static sanity: schema is well-formed YAML with the expected top-level keys."""
    assert isinstance(schema, dict)
    assert schema.get("$schema") == "http://json-schema.org/draft-07/schema#"
    assert schema["title"] == "AIT Agent Definition"
    for required in ("name", "version", "description", "model", "audit"):
        assert required in schema["required"], f"schema lost required field: {required}"


@pytest.mark.skipif(not _JSONSCHEMA_AVAILABLE, reason="jsonschema not installed")
def test_each_agent_yml_validates_against_schema(agent_paths, schema):
    """Every agent.yml on disk passes the JSON Schema."""
    failures = []
    for name, path in agent_paths:
        with open(path) as fh:
            data = yaml.safe_load(fh)
        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as exc:
            failures.append(f"{name}: {exc.message} (at {list(exc.absolute_path)})")
    assert not failures, "schema validation failures:\n  - " + "\n  - ".join(failures)


def test_agent_yml_name_matches_directory(agent_paths):
    """A loader can't disambiguate when name and directory disagree."""
    for name, path in agent_paths:
        with open(path) as fh:
            data = yaml.safe_load(fh)
        assert data.get("name") == name, (
            f"agent.yml at {path}: name '{data.get('name')}' must match "
            f"directory '{name}'"
        )


def test_agent_yml_name_matches_pattern(agent_paths):
    """Names are lower+dashes only — keeps URLs, table joins, log greps simple."""
    for name, _ in agent_paths:
        assert _NAME_RE.match(name), (
            f"agent name '{name}' does not match {_NAME_RE.pattern}"
        )


def test_agent_yml_model_uri_pattern(agent_paths):
    """Both primary and (if set) fallback URI use the dash-separated provider scheme."""
    for name, path in agent_paths:
        with open(path) as fh:
            data = yaml.safe_load(fh)
        primary = data.get("model", {}).get("primary", "")
        assert _MODEL_URI_RE.match(primary), (
            f"agent {name} model.primary '{primary}' does not match "
            f"{_MODEL_URI_RE.pattern}"
        )
        fallback = data.get("model", {}).get("fallback")
        if fallback:
            assert _MODEL_URI_RE.match(fallback), (
                f"agent {name} model.fallback '{fallback}' does not match "
                f"{_MODEL_URI_RE.pattern}"
            )


def test_agent_yml_referenced_files_exist(agent_paths):
    """system_prompt_path + outcomes.rubric_path must resolve to files."""
    for name, path in agent_paths:
        agent_dir = path.parent
        with open(path) as fh:
            data = yaml.safe_load(fh)
        sp = data.get("system_prompt_path")
        if sp:
            assert (agent_dir / sp).is_file(), (
                f"agent {name}: system_prompt_path '{sp}' missing"
            )
        rp = (data.get("outcomes") or {}).get("rubric_path")
        if rp:
            assert (agent_dir / rp).is_file(), (
                f"agent {name}: outcomes.rubric_path '{rp}' missing"
            )


def test_agent_yml_has_non_empty_capability_scopes(agent_paths):
    """No silent 'all powerful' agents — capability_scopes is the audit trail
    of what the agent IS allowed to do. Empty means we'd reject it anyway."""
    for name, path in agent_paths:
        with open(path) as fh:
            data = yaml.safe_load(fh)
        scopes = (data.get("audit") or {}).get("capability_scopes") or []
        assert scopes, f"agent {name}: audit.capability_scopes must be non-empty"
