#!/usr/bin/env python3
"""Render IMPRINT.md — the first page a newborn model reads — from the body plan.

Roadmap row `imprint`. Every line is rendered from a source file (listed at the
bottom of the page); the only hand-written text is the short fixed preamble of
section 2 and the section headings. Hard cap 200 lines.

Regenerate-and-diff, as body-plan-gen.py: byte-stable, no clock, no network.
Gate: tests/anatomy/test_imprint_is_rendered.py.

    python3 tools/imprint-gen.py            # write IMPRINT.md
    python3 tools/imprint-gen.py --check    # exit 1 if IMPRINT.md is stale
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import textwrap
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
TARGET = REPO / "IMPRINT.md"
MAX_LINES = 200
# OpenHuman cuts each AGENTS.md layer at 20,000 chars (agent/prompts/types.rs
# BOOTSTRAP_MAX_CHARS); under 16k leaves a harness room for its own prompt.
MAX_CHARS = 16000
TOP = 5

SOURCES = {
    "charter": "CLAUDE.md",
    "readers": "tools/README.md",
    "tasks": "state/genome/task-types.yml",
    "skill": "files/anatomy/skills/nos-datatables/SKILL.md",
    "mcp": "tools/mcp-tables-server.py",
    "secrets": "templates/secrets.yml.j2",
    "backends": "state/habitat/llm-backends.yml",
    "manifest": "state/manifest.yml",
    "ruling": "files/anatomy/apex/ruling.yml",
    "glossary": "docs/glossary.md",
}
OTHER_SOURCES = [
    "state/body-plan.json (via tools/body.py)",
    "state/anatomy-graph.json (via files/anatomy/apex/projection.py)",
    "the default layers (tools/nos_identity.py default_config())",
]


def _module(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str((REPO / rel).parent))
    spec.loader.exec_module(mod)
    return mod


def _read(key: str) -> str:
    return (REPO / SOURCES[key]).read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """The body under a `## heading` line, up to the next `## `."""
    return text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def charter() -> list[str]:
    return _section(_read("charter"), "Working in nOS").strip("\n").splitlines()


def what_nos_is() -> list[str]:
    rows = yaml.safe_load(_read("manifest"))["services"]
    return [
        "- nOS is an Ansible playbook that turns one Mac (Apple Silicon) or Ubuntu 24.04 host into a self-hosted Agentic Home Lab.",
        "- This repo is the SOURCE. The running estate lives elsewhere on the host and changes only when the operator runs a converge.",
        f"- Each service is an organ: one role, one compose override, one row in state/manifest.yml ({len(rows)} rows).",
        "- All data stays on the machine. Sign-in goes through Authentik; work is tracked in KEAP tables, not in prose files.",
        "- When this page and a reader disagree, the reader is right. Ask it (section 4).",
    ]


def body_plan() -> list[str]:
    body = _module("tools/body.py", "body")
    graph = json.loads(body.GRAPH.read_text(encoding="utf-8"))
    deg = body._degree(graph)
    out = ["Levels run smallest to largest, then the systems that cut across every level.",
           "Each line: level (count) — what it means (the lexicon's words), then the most "
           "connected nodes (edge count).", ""]
    for lv in body.LEVELS:
        what = body.gloss(lv)
        members = body._members(graph, deg, lv)
        top = ", ".join(f"{n} ({deg[n]})" for n in members[:TOP])
        top = top or f"none — {body.EMPTY.get(lv, 'no kind is placed here')}"
        out.append(f"- **{lv}** ({len(members)}) — {what} Most connected: {top}")
    out += ["", f"Hidden plumbing: {graph['counts'].get('internal', 0)} internal nodes. "
            "Look closer: `tools/body.py <level>` or `tools/body.py <node>`."]
    return out


def readers() -> list[tuple[str, str]]:
    """§Readers rows: `*-status.py` (the set Apgar asks about) + the readers CLAUDE.md names."""
    rows = dict(re.findall(r"^- `([^`]+)` — (.+)$", _section(_read("readers"), "Readers — what is true right now"), re.M))
    named = re.findall(r"^tools/(\S+\.py)", _read("charter"), re.M)
    order = [n for n in named if n in rows] + [n for n in rows if n.endswith("-status.py")]
    out = []
    for name in dict.fromkeys(order):
        desc = re.sub(rf"^(READER: |{re.escape(Path(name).stem)}\s+—\s+)", "", rows[name]).strip()
        out.append((name, desc))
    return out


def senses() -> list[str]:
    out = ["A reader only reads, exits 0, and reports what it cannot read as UNKNOWN, never green.",
           "Start with the first one.", ""]
    return out + [f"- `tools/{n}` — {d}" for n, d in readers()]


def _skill_table(skill: str) -> list[str]:
    rows = re.findall(r"^\| `([\w-]+)` \| ([^|]+) \| ([^|]+) \|$", skill, re.M)
    return [f"- `{t}` — a row is {what.strip()}. Written by: {who.strip()}." for t, what, who in rows[:2]]


def _dtt_verbs(skill: str) -> list[str]:
    block = _section(skill, "Two doors, one contract").split("```", 2)[1]
    joined = re.sub(r"\\\n\s*", "", block)
    return [ln.strip() for ln in joined.splitlines() if ln.strip().startswith("nos dtt")]


def _never(skill: str) -> list[str]:
    bullets = re.split(r"\n- ", "\n" + _section(skill, "Never").strip())[1:]
    return ["- " + " ".join(b.split()).split(". ")[0].rstrip(".") + "." for b in bullets]


def act() -> list[str]:
    types = yaml.safe_load(_read("tasks"))["task_types"]
    skill = _read("skill")
    out = ["Every row on the board carries a `task_type`. Its contract says which tools, what it writes, who runs it, and what ends it.", ""]
    for name, c in types.items():
        who = "operator-run" if c["needs_operator"] else "agent-run"
        out.append(f"- `{name}` — {c['summary']} writes: {c['writes']} · {who} · "
                   f"tools: {', '.join(c['tools'])} · done: {' '.join(c['done'].split())}")
    out += ["", "The two tables (in KEAP):"] + _skill_table(skill)
    out += ["", "The `nos dtt` verbs:", "", "```"] + _dtt_verbs(skill) + ["```"]
    mcp = _module(SOURCES["mcp"], "mcp_tables_server")
    out += ["", "The MCP tool `nos_tables`, one verb per call: " +
            ", ".join(f"`{v}` ({p})" for v, p in mcp.VERBS.items()) + "."]
    op = [n for n, c in types.items() if c["needs_operator"]]
    rule = next(b for b in "\n".join(charter()).split("\n- ") if "config.yml" in b)
    out += ["", "What a model may never do:", "",
            f"- Run a task of type {', '.join(f'`{n}`' for n in op)}: only the operator runs it.",
            "- " + " ".join(rule.split())] + _never(skill)
    return out


def doors() -> list[str]:
    ident = _module("tools/nos_identity.py", "nos_identity")
    cfg = ident.default_config()
    assert re.search(r"^keap_agent_token_ro:", _read("secrets"), re.M), "RO token key moved"
    keap = f"http://127.0.0.1:{cfg['keap_port']}"
    ollama = yaml.safe_load(_read("backends"))["backends"]["ollama"]
    rows = yaml.safe_load(_read("manifest"))["services"]
    routed = [r["id"] for r in rows if r.get("domain_var")]
    out = [
        f"- KEAP agent API: `{keap}/agent/v1` (bearer token; the RO token reads, the RW token writes).",
        "- The tables over MCP (stdio). The read-only token is the key `keap_agent_token_ro` in `~/.nos/secrets.yml`:",
        "",
        "```",
        f"KEAP_API_URL={keap} KEAP_AGENT_TOKEN_RO=<keap_agent_token_ro> python3 <this repo>/{SOURCES['mcp']}",
        "```",
        "",
        f"- Local models (Ollama, OpenAI-compatible): `{ollama['base_url']}`, no token. "
        f"Models the register names: {', '.join(f'`{m}`' for m in ollama['sizes_b'].values())}.",
        f"- Web: Traefik owns ports 80/443. A service with a `domain_var` in state/manifest.yml ({len(routed)} of {len(rows)}) "
        f"answers at that variable, by default `<name>.{{{{ tenant_domain }}}}` with `tenant_domain: {cfg['tenant_domain']}`. "
        "This host's value: `tools/estate-status.py --config tenant_domain`.",
    ]
    out += textwrap.wrap("  Routed: " + ", ".join(routed) + ".", 118, subsequent_indent="  ")
    proj = _module("files/anatomy/apex/projection.py", "projection")
    art, ruling = proj.load_artifact(), proj.load_ruling()
    public = json.loads(proj.public_json(art, ruling))
    withheld = sum(1 for v in ruling["nodes"].values() if not isinstance(v, dict))
    out += ["", f"The public organ systems (the apex ruling publishes {public['counts']['organ_systems']}; "
            f"{withheld} of {len(ruling['nodes'])} ruled nodes are withheld):", ""]
    out += [f"- {o['title']} — {o['tells']} ({len(o['atoms'])} parts)" for o in public["organ_systems"]]
    return out


def level_words() -> list[str]:
    return [ln for ln in _section(_read("glossary"), "Levels").splitlines() if ln.startswith("- ")]


SECTIONS = [
    ("1. The charter — read this first (verbatim from CLAUDE.md, \"Working in nOS\")", charter),
    ("2. What nOS is", what_nos_is),
    ("3. The body plan", body_plan),
    ("4. How to ask — the senses", senses),
    ("5. How to act — task types and the two tables", act),
    ("6. Doors on this host", doors),
    ("7. The level words", level_words),
]


def render() -> str:
    out = ["<!-- GENERATED by tools/imprint-gen.py — do not edit. Gate: tests/anatomy/test_imprint_is_rendered.py -->",
           "# IMPRINT — the first page a new model reads in nOS"]
    for title, fn in SECTIONS:
        out += ["", f"## {title}", ""] + fn()
    out += ["", "## Sources", "", "Every line above is rendered from these files:", ""]
    out += [f"- {s}" for s in dict.fromkeys(SOURCES.values())] + [f"- {s}" for s in OTHER_SOURCES]
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="render IMPRINT.md")
    ap.add_argument("--check", action="store_true", help="exit 1 if IMPRINT.md is stale")
    args = ap.parse_args()
    text = render()
    n = text.count("\n")
    if n > MAX_LINES:
        print(f"imprint: render is {n} lines, over the {MAX_LINES}-line cap", file=sys.stderr)
        return 1
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != text:
            print("imprint: IMPRINT.md STALE — regenerate with tools/imprint-gen.py", file=sys.stderr)
            return 1
        print(f"imprint current ({n} lines)")
        return 0
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote IMPRINT.md ({n} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
