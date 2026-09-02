"""Anatomy CI gate — the tool enum and the registered implementations match.

Both directions, because both failures happened (agentkit.md §6, ruling 5,
2026-09-02): `ask-operator` was implemented but not in the enum — undeclarable
for months; `bash-write` and `mcp-pulse` sat in the enum with no implementation
— declarable landmines. The schema is a CONTRACT, not a roadmap; intent lives
in the roadmap table.

Reads the artifacts: the schema's enum, and the `id()` returns of every
ToolInterface implementation.
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = REPO / "state" / "schema" / "agent.schema.yaml"
TOOLS = REPO / "files" / "anatomy" / "wing" / "app" / "AgentKit" / "Tools"


def _enum_ids() -> set[str]:
    doc = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    tools = doc["properties"]["tools"]
    items = tools.get("items", tools)
    return set(items["properties"]["id"]["enum"])


def _registered_ids() -> set[str]:
    out = set()
    for php in TOOLS.glob("*.php"):
        src = php.read_text(encoding="utf-8")
        if "implements ToolInterface" not in src and "extends McpWingTool" not in src:
            continue
        if re.search(r"^abstract class", src, re.M):
            continue  # a base class registers nothing itself
        m = re.search(r"function id\(\)[^{]*\{\s*return '([a-z0-9-]+)';", src)
        assert m, f"{php.name} is a concrete tool but its id() is not a literal"
        out.add(m.group(1))
    assert out, "no ToolInterface implementations found — the glob or layout moved"
    return out


def test_every_enum_member_has_an_implementation():
    dead = _enum_ids() - _registered_ids()
    assert not dead, (
        f"enum members with no implementation: {sorted(dead)}. A declarable "
        "tool that cannot exist is a landmine (bash-write, mcp-pulse were "
        "this); intent belongs in the roadmap, not the contract")


def test_every_implementation_is_declarable():
    hidden = _registered_ids() - _enum_ids()
    assert not hidden, (
        f"implemented tools missing from the enum: {sorted(hidden)}. "
        "ask-operator sat here for months — built, and no manifest could "
        "grant it")
