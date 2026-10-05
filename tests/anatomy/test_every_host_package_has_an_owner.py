"""Anatomy gate — every host package list and desktop switch has an owner.

WHY: nOS was forked from a personal mac-dev-playbook. On 2026-10-05 its
committed defaults installed 69 Homebrew formulae, 36 casks, 21 global pip
packages, 10 global npm packages, Go and .NET toolchains and a set of macOS
defaults — and 12 of the 69 formulae had a caller anywhere in the repo. A
default converge on a client's Mac took responsibility for software nOS never
runs, and `brew upgrade` then stood between those apps and their vendors.

The line is drawn by OWNERSHIP, declared once in `software_owner`
(the default layers), one class per list or switch:
  self      nOS calls it, pins it, updates it   -> every entry has a caller
  symbiont  installed once when absent, then fed by its vendor's updates
  host      the machine owner's (the *personal* keys) -> off unless config.yml asks

A caller is read from code (tasks, roles, tools, organs, judge argv), never
from comments, docs, tests or the config layers that DECLARE the package.
Roadmap row: host-software-ownership.
"""

from __future__ import annotations

import functools
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

CLASSES = {"self", "symbiont", "host"}
# A host package list: Homebrew/pip/npm/go/gem/... — not authentik_oidc_apps.
LIST_NAME = re.compile(r"(_packages|_cask_apps|_installed_apps|_global_tools)$")
# Where the command a package provides differs from its install name.
COMMAND = {"sqlite": "sqlite3", "ansible": "ansible-playbook", "nss": "certutil", "ripgrep": "rg"}

CODE_ROOTS = ("tasks", "roles", "tools", "callback_plugins", "files/anatomy", "main.yml",
              "state/judge-sets.yml")
CODE_SUFFIXES = {".yml", ".yaml", ".j2", ".sh", ".py", ".php", ".ts", ".mjs", ".js", ""}
# Not host code: container builds, the knowledge corpus, the browser bundle.
NOT_HOST = re.compile(r"Dockerfile|compose[^/]*\.j2$|/cortex/knowledge/|/face/|/www/assets/|/node_modules/")
COMMENT = re.compile(r"^\s*(#|//|\*|--|\{#)")


def _defaults() -> dict:
    return ni.default_config()


def _owner() -> dict:
    owner = _defaults().get("software_owner")
    assert isinstance(owner, dict) and owner, "software_owner is missing from the default layers"
    return owner


def _name(entry) -> str:
    raw = entry.get("name", "") if isinstance(entry, dict) else str(entry)
    if "/" in raw and "@" in raw.split("/")[-1]:               # go: x/y/cmd@latest
        return raw.split("/")[-1].split("@")[0]
    return re.sub(r"(?<=.)@[^@/]*$", "", raw)                  # npm: name@1.2.3


@functools.lru_cache(maxsize=1)
def _code_lines() -> tuple[tuple[str, str], ...]:
    lines: list[tuple[str, str]] = []
    for root in CODE_ROOTS:
        base = REPO / root
        paths = [base] if base.is_file() else base.rglob("*")
        for p in paths:
            rel = p.relative_to(REPO).as_posix()
            if not p.is_file() or p.suffix not in CODE_SUFFIXES or NOT_HOST.search(rel):
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if not COMMENT.match(line):
                    lines.append((f"{rel}:{i}", line))
    return tuple(lines)


def _invokes(cmd: str):
    c = re.escape(cmd)
    return re.compile(
        rf"(?:^\s*|[|;&(`]\s*|\$\(\s*|\bexec\s+|/|[\"']|(?:cmd|shell|command)\s*:\s*[>|]?\s*)"
        rf"{c}(?=[\s\"',)\]]|$)"
        rf"|^\s*(?:import|from)\s+{c}\b")


def callers(package: str, lines=None) -> list[str]:
    cmd = COMMAND.get(package, package)
    rx = _invokes(cmd)
    return [where for where, line in (lines or _code_lines()) if cmd in line and rx.search(line)]


def test_every_host_package_list_is_classed():
    owner, cfg = _owner(), _defaults()
    lists = sorted(k for k, v in cfg.items() if isinstance(v, list) and LIST_NAME.search(k))
    assert len(lists) >= 8, f"positive control: the sweep found only {lists}"
    unclassed = [k for k in lists if k not in owner]
    assert not unclassed, f"host package lists with no owner in software_owner: {unclassed}"
    bad = {k: v for k, v in owner.items() if v not in CLASSES or k not in cfg}
    assert not bad, f"owner entries naming an unknown class or an undeclared variable: {bad}"


def test_a_package_has_one_owner():
    owner, cfg = _owner(), _defaults()
    seen: dict[str, str] = {}
    twice = []
    for var in owner:
        for entry in cfg[var] if isinstance(cfg[var], list) else []:
            n = _name(entry)
            if n in seen and seen[n] != var:
                twice.append(f"{n}: {seen[n]} and {var}")
            seen[n] = var
    assert not twice, "a package sits in two owner lists:\n  " + "\n  ".join(twice)


def test_every_self_package_has_a_caller():
    owner, cfg, lines = _owner(), _defaults(), _code_lines()
    assert callers("jq", lines), "positive control: jq is called by tasks/upgrade-engine.yml"
    assert not callers("htop", lines), "negative control: nothing in the repo runs htop"
    orphans = [f"{var}: {_name(e)}" for var, cls in owner.items() if cls == "self"
               and isinstance(cfg[var], list) for e in cfg[var] if not callers(_name(e), lines)]
    assert not orphans, (
        f"{len(orphans)} self package(s) with no caller in tasks/roles/tools/organs. "
        "nOS owns what it runs; move each to a symbiont or personal (host) list:\n  "
        + "\n  ".join(orphans))


def _gates(var: str) -> list[str]:
    """The `when:`/`loop:` text of every task looping over `var`, plus the
    main.yml entry that includes its file — read from the task files."""
    out = []
    main = yaml.safe_load((REPO / "main.yml").read_text())
    entries = [t for play in main for sect in ("pre_tasks", "roles", "tasks") for t in play.get(sect) or []
               if isinstance(t, dict)]
    for f in [*(REPO / "tasks").glob("*.yml"), *(REPO / "roles").glob("*/tasks/*.yml")]:
        text = f.read_text(encoding="utf-8")
        if var not in text:
            continue
        flat = []
        stack = list(yaml.safe_load(text) or [])
        while stack:
            t = stack.pop()
            if isinstance(t, dict):
                flat.append(t)
                stack += t.get("block") or []
        rel = f.relative_to(REPO).as_posix()
        role = rel.split("/")[1] if rel.startswith("roles/") else None
        parent = " ".join(str(e.get("when", "")) for e in entries
                          if rel in str(e.get("import_tasks", "")) + str(e.get("ansible.builtin.import_tasks", ""))
                          or (role and e.get("role") == role))
        for t in flat:
            if var in str(t.get("loop", "")):
                out.append(f"{t.get('loop')} {t.get('when', '')} {parent}")
    return out


def test_defaults_enable_no_host_item():
    owner, cfg = _owner(), _defaults()
    switches = {k for k, c in owner.items() if c == "host" and isinstance(cfg[k], bool)}
    on = sorted(k for k in switches if cfg[k])
    ungated = []
    for var, cls in owner.items():
        if cls != "host" or not isinstance(cfg[var], list) or not cfg[var]:
            continue
        sites = _gates(var)
        if not sites or not all(any(re.search(rf"\b{s}\b", g) and not cfg[s] for s in switches)
                                for g in sites):
            ungated.append(f"{var} ({len(sites)} install site(s))")
    assert not (on or ungated), (
        f"host-class switches that default ON: {on}\n"
        "host-class lists a default converge installs (every task looping over one must be "
        "gated by a host-class switch that defaults off):\n  " + "\n  ".join(ungated))
