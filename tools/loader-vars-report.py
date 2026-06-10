#!/usr/bin/env python3
"""D1 scoping tool (2026-06-11) — the plugin-loader variable contract.

The 6 `template_vars: "{{ vars }}"` / `role_vars: "{{ vars }}"` call sites
(core-up ×3, stack-up, blank-reset, pre-migrate) hard-break when ansible-core
2.24 removes the `vars` magic variable. The replacement is an EXPLICIT
namespace: a generated set_fact map containing exactly the vars plugins
reference.

Empirics that shaped the design (2026-06-11, see roadmap O25):
  - `hostvars[inventory_hostname]` is NOT a drop-in: it carries 126 keys vs
    `vars`' 891 — play vars_files (the whole default.config.yml namespace)
    are absent. Disproven live; do not retry it.
  - The actual contract is ~190 distinct vars across 114 plugin files.

This tool prints the referenced-var set so the future generator (and its
drift gate) has a single source of truth. Run:

    python3 tools/loader-vars-report.py            # human summary
    python3 tools/loader-vars-report.py --names    # one var per line
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "files/anatomy/plugins"

# Jinja builtins + template-local loop/scratch names — not play vars.
NOT_PLAY_VARS = {
    "loop", "item", "range", "true", "false", "none", "lookup", "dict",
    "list", "self", "varnames", "default", "c", "e", "entries", "cards",
    "namespace", "undefined",
}


def referenced_vars() -> tuple[set[str], int]:
    refs: set[str] = set()
    files = (
        list(PLUGINS.glob("*/plugin.yml"))
        + list(PLUGINS.glob("*/templates/*.j2"))
        + list(PLUGINS.glob("*/provisioning/**/*.j2"))
    )
    for f in files:
        try:
            src = f.read_text()
        except OSError:
            continue
        for m in re.finditer(r"\{\{-?\s*([a-z_][a-z0-9_]*)", src):
            refs.add(m.group(1))
        for m in re.finditer(
            r"\{%-?\s*(?:if|elif|for \w+ in|set \w+ =)\s+(?:not\s+)?([a-z_][a-z0-9_]*)",
            src,
        ):
            refs.add(m.group(1))
    return refs - NOT_PLAY_VARS, len(files)


def main() -> int:
    refs, nfiles = referenced_vars()
    if "--names" in sys.argv:
        print("\n".join(sorted(refs)))
        return 0
    print(f"plugin files scanned : {nfiles}")
    print(f"distinct var refs    : {len(refs)}")
    print("This set IS the template_vars contract — the future explicit-")
    print("namespace generator must cover every name here (drift-gated).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
