#!/usr/bin/env python3
"""Derive each agent's nos-work:// CAPABILITY address (dtt-routing-address).

Operator decision 2026-09-06: a capability is a DERIVED PROJECTION, not a
second store (docs/plans/routing-address.md §5). This reads files/anatomy/agents/*/agent.yml
and emits, for each, the address a planner matches assignments against:

    nos-work://<WHERE>/agent:<name>/<KAM>/<CO>/*

  WHERE  the process locus — ext-cloud for a `-cloud` agent, else local.
  WHO    agent:<name>.
  KAM    the tool/scope set derived from `tools:` (the tool-id → scope map
         below), plus `internet` when the EFFECTIVE model is hosted (a cloud
         model call is data egress). The effective model is `model.backend`
         when set (the estate stamps the effective, not the declared, model),
         else `model.primary`.
  CO     the authored `task_types:` list (state/task-types.yml) — the one
         segment nothing else declares; absent ⇒ `*`.
  KDY    `*` — a capability is held anytime; a deadline lives on an assignment.

The emitted address is the executable definition's input: every one must
`parse()` under tools/nos_work_uri.py. An agent whose KAM would be empty (no
tools, local model — the ops-* measurement subjects) holds no routing
capability and is reported separately, never emitted as a malformed address.

    tools/agent-capability.py            # human report, one line per agent
    tools/agent-capability.py --json     # {name: address} for consumers
    tools/agent-capability.py --check    # exit 1 if any emitted address is unparseable
"""

from __future__ import annotations

import argparse
import glob
import json
import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import nos_work_uri  # noqa: E402  (the reference parser is the definition)

AGENTS = REPO / "files/anatomy/agents"

#: tool id → KAM scope(s). The KAM namespace IS the tool/scope model
#: (docs/plans/routing-address.md §1), so wing/bone/loop are scopes beside repo/dtt/keap.
#: A read-only tool grants the `.read` scoped verb; a writer grants the bare
#: scope (which covers read, per nos_work_uri._covers).
TOOL_KAM: dict[str, list[str]] = {
    "bash-read-only": ["repo.read"],
    "exec": ["repo"],
    "contract-search": ["repo.read"],
    "migration-file-write": ["repo"],
    "mcp-bone": ["bone"],
    "mcp-wing-read": ["wing.read"],
    "mcp-wing-write": ["wing"],
    "mcp-keap": ["keap", "dtt"],
    "mcp-loop": ["loop"],
    # ask-operator is a human channel, not a machine scope — no KAM.
}

#: Effective-model prefixes that mean a HOSTED (cloud) call ⇒ `internet` egress.
#: Local backends (minimax, ollama, openclaw, openai-local-*) do not.
HOSTED_PREFIXES = ("anthropic", "claude-", "openai-")
LOCAL_MARKERS = ("local", "minimax", "ollama", "openclaw")


def _effective_model(model: dict) -> str:
    return str(model.get("backend") or model.get("primary") or "")


def _is_hosted(model: dict) -> bool:
    m = _effective_model(model)
    if any(k in m for k in LOCAL_MARKERS):
        return False
    return m.startswith(HOSTED_PREFIXES)


def _kam(doc: dict) -> list[str]:
    scopes: list[str] = []
    for t in doc.get("tools") or []:
        if isinstance(t, dict):
            scopes += TOOL_KAM.get(t.get("id"), [])
    if _is_hosted(doc.get("model") or {}):
        scopes.append("internet")
    # de-dupe, stable order
    seen: dict[str, None] = {}
    for s in scopes:
        seen.setdefault(s, None)
    # A bare scope covers its own `.read` verb (nos_work_uri._covers), so listing
    # both is noise — drop `X.read` when bare `X` is held (jeff: repo.read+repo).
    bare = {s for s in seen if "." not in s}
    return [s for s in seen if not (s.endswith(".read") and s.split(".")[0] in bare)]


def capability(doc: dict) -> str | None:
    """The agent's nos-work:// address, or None when it holds no scope."""
    name = doc["name"]
    where = "ext-cloud" if name.endswith("-cloud") else "local"
    kam = _kam(doc)
    if not kam:
        return None
    co = doc.get("task_types") or ["*"]
    return f"nos-work://{where}/agent:{name}/{'+'.join(kam)}/{'+'.join(co)}/*"


def _agents() -> list[dict]:
    return [yaml.safe_load(pathlib.Path(f).read_text())
            for f in sorted(glob.glob(str(AGENTS / "*/agent.yml")))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any emitted address is unparseable")
    args = ap.parse_args()

    caps: dict[str, str] = {}
    no_scope: list[str] = []
    for doc in _agents():
        addr = capability(doc)
        if addr is None:
            no_scope.append(doc["name"])
        else:
            caps[doc["name"]] = addr

    if args.check:
        bad = []
        for name, addr in caps.items():
            try:
                nos_work_uri.parse(addr)
            except Exception as e:  # noqa: BLE001
                bad.append(f"{name}: {addr} — {e}")
        if bad:
            print("unparseable capability addresses:\n  " + "\n  ".join(bad), file=sys.stderr)
            return 1
        print(f"agent-capability: {len(caps)} addresses parse; {len(no_scope)} hold no scope")
        return 0

    if args.json:
        print(json.dumps(caps, indent=2))
        return 0

    for name, addr in caps.items():
        print(addr)
    if no_scope:
        print(f"\n# no routing capability (no external scope): {', '.join(no_scope)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
