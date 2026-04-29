#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import-coolify-template.py — fetch a Coolify service template and emit a
Tier-2 nOS manifest draft at apps/<name>.yml.draft.

WHY HYBRID: Coolify (Apache-2.0) maintains ~280 compose templates at
github.com/coollabsio/coolify/tree/main/templates/compose. We borrow the
catalog without forking it; this importer rewrites their token syntax
(``${SERVICE_*}``) into ours (``$SERVICE_*_X``), parses their header
comments into a meta block, and stubs an EMPTY ``gdpr:`` block which the
operator MUST fill in before the parser will accept the file (rename
``.draft`` → ``.yml`` only after editing).

Coolify token mapping (left = upstream, right = nOS / module_utils.
nos_app_parser):

    ${SERVICE_URL_<NAME>_<PORT>}    →  https://$SERVICE_FQDN_<APP>
    ${SERVICE_URL_<NAME>}           →  https://$SERVICE_FQDN_<APP>
    ${SERVICE_FQDN_<NAME>}          →  $SERVICE_FQDN_<APP>
    ${SERVICE_USER_<KEY>}           →  $SERVICE_USER_<KEY>
    ${SERVICE_PASSWORD_<KEY>}       →  $SERVICE_PASSWORD_<KEY>
    ${SERVICE_BASE64_<KEY>}         →  $SERVICE_BASE64_64_<KEY>     (default 64-byte)
    ${SERVICE_BASE64_64_<KEY>}      →  $SERVICE_BASE64_64_<KEY>
    ${SERVICE_BASE64_32_<KEY>}      →  $SERVICE_BASE64_32_<KEY>
    ${VAR:-default}                 →  $VAR  (default value goes to TODO list)
    ${VAR}                          →  $VAR  (added to TODO list — operator must set)

Usage:
    python3 tools/import-coolify-template.py --url <raw-url> [--name <slug>]
    python3 tools/import-coolify-template.py --file <path>   [--name <slug>]
    python3 tools/import-coolify-template.py --url <raw-url> --name myapp --out apps/

Requirements:
    Standard library only. No requests / yaml deps — we hand-parse the
    Coolify header comments and emit YAML ourselves to keep the comment
    structure (PyYAML's dump strips comments, which would lose the GDPR
    TODO scaffolding the operator needs to see).

Exit codes:
    0 — draft written, parser-pending
    1 — bad arguments / source not reachable
    2 — header parse failure (manifest doesn't match Coolify conventions)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import sys
import urllib.request
from pathlib import Path


COOLIFY_HEADER_KEYS = (
    "documentation",
    "slogan",
    "category",
    "tags",
    "logo",
    "port",
    "minversion",
)

# Tokens we want to rewrite in-place. Order matters: the more specific
# patterns must run before the generic ${VAR} fallback or they'd be
# blanket-stripped to plain $VAR (losing semantics).
TOKEN_REWRITES = [
    # ${SERVICE_URL_<NAME>_<PORT>} → https://$SERVICE_FQDN_<APP>
    # We collapse the host:port form down to host because nOS's Traefik
    # router already encodes the port via the loadbalancer label and the
    # operator's app sees its own listener port through env / compose ports.
    (re.compile(r"\$\{SERVICE_URL_[A-Z0-9_]+_\d+\}"),
     lambda m, app: "https://$SERVICE_FQDN_" + app),
    (re.compile(r"\$\{SERVICE_URL_[A-Z0-9_]+\}"),
     lambda m, app: "https://$SERVICE_FQDN_" + app),
    (re.compile(r"\$\{SERVICE_FQDN_[A-Z0-9_]+\}"),
     lambda m, app: "$SERVICE_FQDN_" + app),
    # SERVICE_BASE64 with explicit length passes through, default → _64_
    (re.compile(r"\$\{SERVICE_BASE64_(32|64)_([A-Z0-9_]+)\}"),
     lambda m, app: "$SERVICE_BASE64_" + m.group(1) + "_" + m.group(2)),
    (re.compile(r"\$\{SERVICE_BASE64_([A-Z0-9_]+)\}"),
     lambda m, app: "$SERVICE_BASE64_64_" + m.group(1)),
    (re.compile(r"\$\{SERVICE_USER_([A-Z0-9_]+)\}"),
     lambda m, app: "$SERVICE_USER_" + m.group(1)),
    (re.compile(r"\$\{SERVICE_PASSWORD_([A-Z0-9_]+)\}"),
     lambda m, app: "$SERVICE_PASSWORD_" + m.group(1)),
]

# Operator-required env vars to TRACK (not rewrite to a token). We collect
# them so the import preamble can list them as TODOs the operator must
# resolve before un-drafting the manifest.
DEFAULT_ENV_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::-([^}]*))?\}")
SERVICE_TOKEN_PREFIXES = ("SERVICE_FQDN_", "SERVICE_URL_", "SERVICE_USER_",
                          "SERVICE_PASSWORD_", "SERVICE_BASE64_")


# ---------------------------------------------------------------------------
# Header parsing

def parse_header(text: str) -> dict[str, str]:
    """Extract Coolify-style ``# key: value`` lines from the top of the file.

    Stops at the first non-comment, non-blank line. Returns a dict of the
    key/value pairs as raw strings (no type coercion — caller decides).
    """
    out: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if not s.startswith("#"):
            break
        body = s.lstrip("#").strip()
        if ":" not in body:
            continue
        key, _, value = body.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key in COOLIFY_HEADER_KEYS:
            out[key] = value
    return out


def strip_header(text: str) -> str:
    """Drop the ``# ...`` header block, return only the compose body."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s and not s.startswith("#"):
            break
        i += 1
    return "\n".join(lines[i:]).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Token rewriting

def rewrite_tokens(body: str, app_upper: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (rewritten body, list of (var, default) operator-TODO env vars).

    The TODO list captures every ``${VAR}`` and ``${VAR:-default}`` reference
    that did NOT match a SERVICE_ token. Those are operator-supplied values
    Coolify expects the user to type into a web form — in nOS we surface
    them as a comment block at the top of the draft so the operator can
    replace them with their actual values before un-drafting.
    """
    out = body
    for rx, fn in TOKEN_REWRITES:
        out = rx.sub(lambda m, _fn=fn: _fn(m, app_upper), out)

    # After the SERVICE_ rewrites, anything matching ${...} that's left is an
    # operator-supplied env (or upstream conditional default we haven't
    # special-cased yet). Drop the curlies to plain $VAR (compose env interpolation
    # accepts both forms) and record it.
    todos: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _strip_braces(m: re.Match) -> str:
        var = m.group(1)
        default = m.group(2) or ""
        if any(var.startswith(p) for p in SERVICE_TOKEN_PREFIXES):
            # Already-rewritten SERVICE_ token snuck through — pass through
            # bare $VAR. Shouldn't happen post-rewrite, defensive.
            return "$" + var
        if var not in seen:
            todos.append((var, default))
            seen.add(var)
        return "$" + var

    out = DEFAULT_ENV_RE.sub(_strip_braces, out)
    return out, todos


# ---------------------------------------------------------------------------
# Manifest emission

def render_manifest(
    *,
    name: str,
    header: dict[str, str],
    compose_body: str,
    todos: list[tuple[str, str]],
    source_url: str,
) -> str:
    """Render the apps/<name>.yml.draft text. Comment-rich on purpose — the
    operator NEEDS the visual GDPR TODO scaffolding to know what to fill in.
    """
    today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    port = header.get("port", "8080")
    category = header.get("category", "productivity")
    summary = header.get("slogan", "(set a one-line description)")
    homepage = header.get("documentation", "")

    # tags: Coolify ships them as comma-separated; convert to YAML list.
    tags_raw = header.get("tags", "")
    tag_list = [t.strip() for t in tags_raw.split(",") if t.strip()]
    tags_yaml = "[" + ", ".join('"' + t + '"' for t in tag_list) + "]"

    # Header preamble: source attribution + license + numbered operator action
    # items. We compute step numbers dynamically so the list stays contiguous
    # whether or not there are operator-supplied env TODOs.
    steps: list[str] = [
        "Fill in the gdpr: block below — every key marked TODO is mandatory "
        "(the parser refuses manifests with a missing or null gdpr block).",
        "Review compose: image tags, mem_limit, healthchecks, volumes.",
    ]
    if todos:
        env_lines = []
        for var, default in todos:
            if default:
                env_lines.append("       - " + var + "  (upstream default: " + default + ")")
            else:
                env_lines.append("       - " + var + "  (no upstream default — REQUIRED)")
        steps.append(
            "Set the following operator-supplied env vars (see the compose "
            "env sections — they were ${VAR} placeholders in the upstream "
            "template):\n" + "\n".join("#" + line for line in env_lines)
        )
    steps.append("Rename apps/" + name + ".yml.draft → apps/" + name + ".yml")
    steps.append("Smoke-parse: python3 -m module_utils.nos_app_parser apps/" + name + ".yml")
    steps.append("Re-run the playbook (apps_runner brings it up automatically).")

    preamble_lines = [
        "# ============================================================================",
        "# Imported from Coolify on " + today + " by tools/import-coolify-template.py",
        "# Source: " + source_url,
        "# Upstream license: Apache-2.0 (coollabsio/coolify)",
        "#",
        "# OPERATOR ACTION REQUIRED before this manifest is deployable:",
    ]
    for idx, step in enumerate(steps, start=1):
        first, _, rest = step.partition("\n")
        preamble_lines.append("#   " + str(idx) + ". " + first)
        if rest:
            for cont_line in rest.splitlines():
                preamble_lines.append(cont_line)
    preamble_lines.append("# ============================================================================")
    preamble = "\n".join(preamble_lines)

    meta_block = "\n".join([
        "meta:",
        '  name: "' + name + '"',
        '  version: "1.0.0"',
        '  summary: ' + ('"' + summary.replace('"', "'") + '"' if summary else '""'),
        '  homepage: "' + homepage + '"',
        '  category: "' + category + '"',
        '  ports: [' + port + ']',
        '  tags: ' + tags_yaml,
    ])

    gdpr_block = """
# ── GDPR Article 30 register entry — MANDATORY ───────────────────────────────
# The parser REJECTS this manifest if any required key below is missing or
# null. These answers drive deploy gates (TLS, SSO, EU-residency) AND populate
# Wing's /gdpr/apps cards so DPO inquiries can be answered without
# re-investigating each app from scratch.
gdpr:
  # TODO Plain-language sentence describing why we process data.
  purpose: |
    REPLACE THIS WITH A REAL PURPOSE STATEMENT.

  # TODO Pick exactly one Article 6(1) lawful basis:
  #   consent | contract | legal_obligation | vital_interests
  #   public_task | legitimate_interests
  legal_basis: "TODO"

  # TODO Categories of personal data PROCESSED (be specific).
  data_categories:
    - "TODO"

  # TODO Whose data we process. Drives the TLS gate.
  #   end_users / patients / minors / employees → TLS termination required
  #   anonymous / partners                       → no TLS-from-data gate
  data_subjects:
    - "end_users"

  # TODO Auto-erasure horizon in days. -1 = forever (document why in purpose).
  retention_days: 365

  # TODO Third-party processors invoked. Empty list is OK if truly self-contained.
  processors: []

  # TODO Set true ONLY if data leaves the EU/EEA. Setting false (default)
  # forces the EU-residency deploy gate over compose images.
  transfers_outside_eu: false
""".lstrip("\n")

    nginx_hint = """
# ── Optional: Tier-2 nginx / Traefik routing hints ──────────────────────────
# Default behaviour: the runner derives subdomain=meta.name, upstream_port=
# meta.ports[0], auth=proxy (Authentik forward-auth gate). Override here if
# the upstream needs a non-default callback path or a different auth mode.
nginx:
  auth: "proxy"
""".lstrip("\n")

    # Coolify templates put `services:` / `volumes:` / `networks:` at top
    # level. nOS's schema expects them nested under `compose:`. Wrap by
    # indenting the body two spaces and prepending the key.
    indented_body = "\n".join(
        ("  " + line if line.strip() else line)
        for line in compose_body.splitlines()
    )
    compose_block = "# ── Compose fragment (transformed from Coolify) ─────────────────────────────\ncompose:\n" + indented_body

    return "\n".join([
        "---",
        preamble,
        "",
        meta_block,
        "",
        gdpr_block,
        compose_block,
        "",
        nginx_hint,
    ])


# ---------------------------------------------------------------------------
# I/O

def fetch(url: str, *, timeout: float = 15.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "nos-import-coolify/1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1].strip())
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="Raw URL to a Coolify .yaml template")
    src.add_argument("--file", help="Local path to a Coolify-style template")
    p.add_argument("--name", help="Slug for apps/<name>.yml.draft (default: derived from filename)")
    p.add_argument("--out", default="apps", help="Output directory (default: apps)")
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing apps/<name>.yml.draft (default: refuse)")
    args = p.parse_args()

    if args.url:
        try:
            text = fetch(args.url)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write("FAILED to fetch " + args.url + ": " + str(exc) + "\n")
            return 1
        source_url = args.url
        default_name = os.path.splitext(os.path.basename(args.url))[0]
    else:
        path = Path(args.file)
        if not path.is_file():
            sys.stderr.write("File not found: " + args.file + "\n")
            return 1
        text = path.read_text(encoding="utf-8")
        source_url = "file://" + str(path.resolve())
        default_name = path.stem

    name = (args.name or default_name).lower().replace(" ", "-")
    if not re.match(r"^[a-z][a-z0-9_-]{0,62}$", name):
        sys.stderr.write("Invalid slug '" + name + "' — must match ^[a-z][a-z0-9_-]{0,62}$\n")
        return 1

    header = parse_header(text)
    if not header:
        sys.stderr.write("WARNING: no Coolify header keys found — proceeding with empty meta defaults.\n")
    body_only = strip_header(text)

    rewritten, todos = rewrite_tokens(body_only, name.upper().replace("-", "_"))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (name + ".yml.draft")
    if out_path.exists() and not args.force:
        sys.stderr.write("Refusing to overwrite " + str(out_path) + " (use --force).\n")
        return 1

    manifest = render_manifest(
        name=name,
        header=header,
        compose_body=rewritten,
        todos=todos,
        source_url=source_url,
    )
    out_path.write_text(manifest, encoding="utf-8")

    print("Wrote " + str(out_path))
    print()
    print("Next steps:")
    print("  1. Edit the file and replace every TODO in the gdpr: block")
    print("     (purpose, legal_basis, data_categories, retention_days, transfers_outside_eu).")
    if todos:
        print("  2. Set the following env values somewhere reachable by docker compose")
        print("     (apps/" + name + ".yml env section, .env, or shell env):")
        for var, default in todos:
            note = "  default: " + default if default else "  (no default — operator-required)"
            print("       - " + var + note)
        print("  3. Smoke-parse:")
    else:
        print("  2. Smoke-parse:")
    print("     python3 -m module_utils.nos_app_parser " + str(out_path))
    print("     (a clean exit means the parser is satisfied)")
    print("  N. Rename apps/" + name + ".yml.draft → apps/" + name + ".yml")
    print("  N+1. Run the playbook — apps_runner picks the manifest up automatically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
