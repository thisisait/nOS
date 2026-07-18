#!/usr/bin/env python3
"""nOS-face wiring report — the hard-doctrine linter for the web-desktop shell.

The face shell (vendored at files/anatomy/face/) composes Authentik identity, the
Wing catalog, the Bone VFS/user-state, and KEAP config DataTables. That wiring is
doctrine (docs/doctrine/face.md) and easy to break silently — a client that reads
`uid` from the browser, a `{@html}` XSS hole, a config DataTable with a def but no
seeder, a compose env missing the edge token. This tool makes those legible and
enforces them. Paired gate: tests/anatomy/test_face_wiring_contract.py +
test_face_security_gates.py.

Checks:
  1. Vendored source present (package.json, VERSION, Dockerfile, svelte.config.js).
  2. face-base plugin wiring: forward_auth SSO, hub_card, gdpr, gated on install_face.
  3. Compose env carries the trust + upstream tokens (FACE_EDGE_TOKEN,
     NOS_VFS_API_TOKEN, NOS_HUB_API_URL, NOS_KEAP_TABLES_URL).
  4. The 3 config DataTables (layouts/wallpapers/controls) have a def AND a seeder.
  5. XSS: no `{@html}` anywhere in the shell source.
  6. uid discipline: BFF endpoints never read uid from the client (query/body) —
     it is pinned from locals.identity only.
  7. Edge-trust: hooks.server.ts enforces FACE_EDGE_TOKEN (403 on mismatch).
  8. Token isolation: `$env/dynamic/private` is imported only server-side.

Usage:
  python3 tools/face-wiring-report.py            # print report, exit 0
  python3 tools/face-wiring-report.py --strict   # exit 1 on any violation
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
FACE = REPO / "files" / "anatomy" / "face"
SRC = FACE / "src"
PLUGIN = REPO / "files" / "anatomy" / "plugins" / "face-base" / "plugin.yml"
COMPOSE = REPO / "roles" / "pazny.face" / "templates" / "compose.yml.j2"
KEAP_TABLES = REPO / "state" / "keap-tables"
CONFIG_TABLES = ("layouts", "wallpapers", "controls")
REQUIRED_ENV = ("FACE_EDGE_TOKEN", "NOS_VFS_API_TOKEN", "NOS_HUB_API_URL", "NOS_KEAP_TABLES_URL")


def _iter_src(*suffixes: str):
    for p in SRC.rglob("*"):
        if p.is_file() and p.suffix in suffixes:
            yield p


def check_vendored() -> list[str]:
    fails = []
    for f in ("package.json", "VERSION", "Dockerfile", "svelte.config.js"):
        if not (FACE / f).is_file():
            fails.append(f"vendored source missing {f}")
    if not (SRC / "hooks.server.ts").is_file():
        fails.append("BFF missing src/hooks.server.ts")
    return fails


def check_plugin() -> list[str]:
    fails = []
    if not PLUGIN.is_file():
        return ["face-base plugin.yml missing"]
    raw = re.sub(r"\{\{[^}]+\}\}", "TEMPLATE", PLUGIN.read_text(encoding="utf-8"))
    m = yaml.safe_load(raw) or {}
    if (m.get("authentik") or {}).get("mode") != "forward_auth":
        fails.append("face-base: authentik.mode must be forward_auth")
    if not (m.get("ui-extension") or {}).get("hub_card"):
        fails.append("face-base: ui-extension.hub_card missing")
    if not m.get("gdpr"):
        fails.append("face-base: gdpr Article-30 block missing")
    if (m.get("requires") or {}).get("feature_flag") != "install_face":
        fails.append("face-base: requires.feature_flag must be install_face")
    return fails


def check_compose_env() -> list[str]:
    if not COMPOSE.is_file():
        return ["roles/pazny.face compose template missing"]
    text = COMPOSE.read_text(encoding="utf-8")
    return [f"compose env missing {e}" for e in REQUIRED_ENV if e not in text]


def check_datatables() -> list[str]:
    fails = []
    seeder_text = ""
    for cand in (REPO / "roles" / "pazny.keap" / "tasks").glob("seed-face-table*.yml"):
        seeder_text += cand.read_text(encoding="utf-8")
    if not seeder_text:
        fails.append("no KEAP seeder for the config DataTables (roles/pazny.keap/tasks/seed-face-table*.yml)")
    for name in CONFIG_TABLES:
        f = KEAP_TABLES / f"{name}.table.yml"
        if not f.is_file():
            fails.append(f"config DataTable def missing: {f.relative_to(REPO)}")
            continue
        d = yaml.safe_load(re.sub(r"\{\{[^}]+\}\}", "TEMPLATE", f.read_text(encoding="utf-8"))) or {}
        for key in ("title", "driver", "visibility"):
            if key not in d:
                fails.append(f"{name}.table.yml missing '{key}'")
        if not (d.get("schema") or {}).get("columns"):
            fails.append(f"{name}.table.yml missing schema.columns")
    return fails


def _strip_comments(text: str) -> str:
    """Drop /* */, // and <!-- --> comments so a doctrine mention of the rule in a
    comment isn't mistaken for a real usage."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"(?m)//.*$", "", text)
    return text


def check_no_html() -> list[str]:
    hits = []
    for p in _iter_src(".svelte", ".ts"):
        code = _strip_comments(p.read_text(encoding="utf-8"))
        # A real usage is `{@html <expr>}` — a mention like `{@html}` (immediately
        # closed) in prose has no expression and is not the tag.
        if re.search(r"\{@html\s+[^}\s]", code):
            hits.append(f"{{@html}} XSS risk in {p.relative_to(REPO)}")
    return hits


def check_uid_discipline() -> list[str]:
    """BFF endpoints must pin uid from locals.identity, never read it from the client."""
    fails = []
    bff = SRC / "routes" / "bff"
    if not bff.is_dir():
        return ["BFF routes dir missing"]
    for p in bff.rglob("+server.ts"):
        text = p.read_text(encoding="utf-8")
        # Hard rule: an endpoint must NEVER read uid from the client (query/body).
        if re.search(r"""searchParams\.get\(\s*['"]uid['"]""", text) or re.search(
            r"""\bbody\s*\.\s*uid\b|['"]uid['"]\s*:\s*(?:body|url)\b""", text
        ):
            fails.append(f"BFF reads uid from the client in {p.relative_to(REPO)}")
        # An endpoint that USES uid must source it from the edge-trusted identity.
        if "uid" in text and "locals.identity" not in text:
            fails.append(f"BFF uses uid but not from locals.identity in {p.relative_to(REPO)}")
    return fails


def check_edge_trust() -> list[str]:
    hooks = SRC / "hooks.server.ts"
    if not hooks.is_file():
        return ["src/hooks.server.ts missing"]
    text = hooks.read_text(encoding="utf-8")
    fails = []
    if "FACE_EDGE_TOKEN" not in text:
        fails.append("hooks.server.ts does not reference FACE_EDGE_TOKEN")
    if "403" not in text:
        fails.append("hooks.server.ts does not refuse (403) on failed edge trust")
    return fails


def check_token_isolation() -> list[str]:
    """`$env/dynamic/private` (tokens) must be imported only server-side."""
    fails = []
    for p in _iter_src(".ts", ".svelte"):
        rel = p.relative_to(SRC).as_posix()
        if "$env/dynamic/private" not in p.read_text(encoding="utf-8"):
            continue
        server_ok = rel == "hooks.server.ts" or rel.startswith("lib/server/") or rel.endswith("+server.ts")
        if not server_ok:
            fails.append(f"$env/dynamic/private imported in client file {p.relative_to(REPO)}")
    return fails


CHECKS = [
    ("vendored source", check_vendored),
    ("face-base plugin", check_plugin),
    ("compose env", check_compose_env),
    ("config DataTables", check_datatables),
    ("no {@html} (XSS)", check_no_html),
    ("uid discipline", check_uid_discipline),
    ("edge-trust", check_edge_trust),
    ("token isolation", check_token_isolation),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="nOS-face wiring report")
    ap.add_argument("--strict", action="store_true", help="exit 1 on any violation")
    args = ap.parse_args()

    all_fails: list[str] = []
    print("nOS-face wiring report")
    print("=" * 60)
    for label, fn in CHECKS:
        fails = fn()
        mark = "ok  " if not fails else "FAIL"
        print(f"[{mark}] {label}")
        for f in fails:
            print(f"        - {f}")
        all_fails.extend(fails)
    print("=" * 60)
    print(f"{len(all_fails)} violation(s)")
    if args.strict and all_fails:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
