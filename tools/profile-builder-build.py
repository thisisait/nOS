#!/usr/bin/env python3
"""nOS profile builder — a static page, rendered at release, that writes a
config.yml before the first `nos` run.

    tools/profile-builder-build.py --out _site/profile-builder   # pages.yml
    tools/profile-builder-build.py --out /tmp/pb && open /tmp/pb/index.html

Everything the page knows comes from the artifacts, at build time:
  default.config.yml   every install_* flag, its default, its inline label and
                       the section it sits in; the step-1 parameters
  profiles/*.yml       the `axis:` header (use-case | policy | service-set |
                       environment | constraint), its install_* flags and its
                       other knobs
The page itself (tools/profile-builder/index.html.tpl) is plain HTML + JS with
no dependencies; the build only substitutes __DATA__. Three steps: parameters,
axes (one profile per axis, or none), the flag list prefilled from the chosen
profiles and editable, then the config.yml to download.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "default.config.yml"
PROFILES = REPO / "profiles"
TPL = REPO / "tools/profile-builder/index.html.tpl"

FLAG = re.compile(r"^(install_[a-z0-9_]+):\s*(.+?)\s*(?:#\s*(.*))?$")
SECTION = re.compile(r"^# ─+ ?(.+?) ?─*$")
AXES = ["service-set", "use-case", "policy", "environment", "constraint"]

# Step 1 — what a fresh operator must decide before anything is installed.
PARAMS = [
    {"key": "tenant_domain", "label": "Domain (TLD every service resolves under)",
     "hint": "dev.local for a laptop, a public domain you own for mail + real TLS"},
    {"key": "instance_name", "label": "Instance name", "hint": "lowercase, no spaces"},
    {"key": "instance_org", "label": "Organisation (GDPR Art-30 controller)", "hint": ""},
    {"key": "default_admin_email", "label": "Admin e-mail", "hint": "fallback admin for every service; ACME contact"},
    {"key": "external_storage_root", "label": "Data volume", "hint": "where service data lives (an external SSD works)"},
    {"key": "global_password_prefix", "label": "Password prefix", "hint": "every derived credential starts with it — choose once, keep secret",
     "secret": True},
]
MAIL = {"key": "mail", "label": "E-mail", "options": [
    {"id": "none", "label": "No mail server", "flags": {"install_mailpit": False, "install_smtp_stalwart": False}},
    {"id": "mailpit", "label": "Mailpit (dev capture, nothing leaves the box)", "flags": {"install_mailpit": True, "install_smtp_stalwart": False}},
    {"id": "stalwart", "label": "Stalwart (real SMTP/IMAP on your domain; needs public DNS + port 25)",
     "flags": {"install_mailpit": False, "install_smtp_stalwart": True}},
]}


def flags() -> list[dict]:
    out, section = [], "General"
    for ln in CONFIG.read_text().splitlines():
        m = SECTION.match(ln.strip())
        if m:
            section = m.group(1).strip()
            continue
        m = FLAG.match(ln)
        if not m:
            continue
        key, raw, label = m.groups()
        raw = raw.strip().strip('"')
        if "{{" in raw:
            default, auto = None, True
        else:
            default, auto = raw.lower() == "true", False
        out.append({"key": key, "default": default, "auto": auto,
                    "label": (label or "").strip(), "section": section})
    return out


def defaults() -> dict:
    raw = yaml.safe_load(CONFIG.read_text()) or {}
    return {p["key"]: raw.get(p["key"], "") for p in PARAMS}


def profiles() -> list[dict]:
    out = []
    for p in sorted(PROFILES.glob("*.yml")):
        text = p.read_text()
        m = re.search(r"^# axis: ([a-z-]+)", text, re.M)
        if not m:
            continue
        data = yaml.safe_load(text) or {}
        purpose = re.search(r"^# Purpose: (.+)$", text, re.M)
        out.append({"id": p.stem, "axis": m.group(1),
                    "purpose": (purpose.group(1) if purpose else "").strip(),
                    "flags": {k: bool(v) for k, v in data.items() if k.startswith("install_") and isinstance(v, bool)},
                    "knobs": {k: v for k, v in data.items() if not k.startswith("install_")}})
    return out


def build() -> dict:
    return {"axes": AXES, "params": PARAMS, "param_defaults": defaults(), "mail": MAIL,
            "flags": flags(), "profiles": profiles()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--json", action="store_true", help="print the data, build nothing")
    a = ap.parse_args()
    data = build()
    if a.json:
        print(json.dumps(data, indent=1, ensure_ascii=False))
        return 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    html = TPL.read_text().replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    (out / "index.html").write_text(html)
    print(f"{out / 'index.html'}: {len(data['flags'])} flags, {len(data['profiles'])} profiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
