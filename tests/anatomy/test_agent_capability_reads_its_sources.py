"""The capability map is read from the tools and the backend register, not guessed.

WHY (2026-10-07, roadmap row `cell-level-words-and-capability-map`). Two facts in
tools/agent-capability.py were typed by hand and both were wrong:
  * TOOL_KAM gave `mcp-bone` the write scope `bone`, but the PHP tool asks only
    `bone.read` and refuses every verb but GET; `mcp-tables` had no row at all.
  * hosted-or-local came from a name list (LOCAL_MARKERS) that called `minimax`
    local. It is api.minimax.io, non-EU, so eight cells egressed with no
    `internet` scope, and WHERE came from the `-cloud` name suffix.
This gate compares TOOL_KAM with each PHP tool's own requiredScopes() by
polarity (read vs write; the two namespaces differ, `mcp.tool_use` is ignored),
and each cell's WHERE/`internet` with its serving row in state/llm-backends.yml.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOLS_PHP = REPO / "files/anatomy/wing/app/AgentKit/Tools"
sys.path.insert(0, str(REPO / "tools"))


def _load(mod: str):
    spec = importlib.util.spec_from_file_location(mod, REPO / "tools" / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


cap = _load("agent-capability")
uri = _load("nos_work_uri")


def _php_tools() -> dict[str, list[str]]:
    """tool id → its requiredScopes(), read from each PHP tool's source."""
    out = {}
    for f in sorted(TOOLS_PHP.glob("*Tool.php")):
        src = f.read_text(encoding="utf-8")
        tid = re.search(r"function id\(\): string\s*\{\s*return '([^']+)';", src)
        scopes = re.search(r"function requiredScopes\(\): array\s*\{\s*return \[([^\]]*)\];", src)
        if tid and scopes:
            out[tid.group(1)] = re.findall(r"'([^']+)'", scopes.group(1))
    return out


def _read_only(scopes: list[str]) -> bool:
    return all(s.endswith(".read") for s in scopes if s != "mcp.tool_use")


def test_the_php_tools_are_found():
    tools = _php_tools()
    assert {"mcp-bone", "mcp-tables", "mcp-keap", "bash-read-only"} <= set(tools), sorted(tools)


def test_every_php_tool_has_a_kam_row_or_a_reason():
    php = set(_php_tools())
    mapped = set(cap.TOOL_KAM) | set(cap.NO_KAM)
    assert php - mapped == set(), f"PHP tools with no TOOL_KAM row: {sorted(php - mapped)}"
    assert mapped - php == set(), f"TOOL_KAM rows with no PHP tool: {sorted(mapped - php)}"
    assert not set(cap.TOOL_KAM) & set(cap.NO_KAM)


def test_kam_polarity_matches_the_php_scopes():
    php = _php_tools()
    bad = [f"{t}: PHP {php[t]} vs KAM {k}" for t, k in cap.TOOL_KAM.items()
           if _read_only(php[t]) != _read_only(k)]
    assert not bad, "read/write polarity differs:\n  " + "\n  ".join(bad)


def test_where_and_internet_come_from_the_serving_backend():
    reg = yaml.safe_load((REPO / "state/llm-backends.yml").read_text(encoding="utf-8"))["backends"]
    default = next(n for n, r in reg.items() if r.get("default"))
    bad = []
    for d in cap._agents():
        row = reg[(d.get("model") or {}).get("backend") or default]
        local = row.get("local") is True
        where = "local" if local else "eu-cloud" if row["residency"]["eu"] else "ext-cloud"
        addr = cap.capability(d)
        if addr is None:
            if not local:
                bad.append(f"{d['name']}: served off-host but holds no address (no `internet`)")
            continue
        p = uri.parse(addr)
        if p.where != {where}:
            bad.append(f"{d['name']}: WHERE {sorted(p.where)} but its backend says {where}")
        if ("internet" in p.kam) == local:
            bad.append(f"{d['name']}: `internet` {'held' if local else 'missing'} on a "
                       f"{'local' if local else 'hosted'} backend")
    assert not bad, "\n  ".join(["capability vs state/llm-backends.yml:", *bad])
