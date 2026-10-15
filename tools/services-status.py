#!/usr/bin/env python3
"""What nOS offers: each manifest service, whether its install flag is on, and what it is.

READER. Joins state/manifest.yml (id, category, install_flag), the install_*
flag resolved over every config layer (nos_identity.install_flags, no
credentials) and the plugin hub_card description (joined by feature_flag, as
the dir name is not the id). A Jinja or undeclared flag is enabled: null.
Exits 0 always; a source it could not read is named in `unknown`.
Gate: tests/anatomy/test_services_status_reader.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nos_identity  # noqa: E402

DESC_MAX = 120


def _cards(unknown: list[str]) -> dict[str, str]:
    """install flag -> hub_card description."""
    root = nos_identity.REPO
    out: dict[str, str] = {}
    for p in sorted((root / "files/anatomy/plugins").glob("*/plugin.yml")):
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            card = d.get("hub_card") or (d.get("ui-extension") or {}).get("hub_card") or {}
            flag = (d.get("requires") or {}).get("feature_flag")
        except Exception:  # noqa: BLE001 — a reader names it, never dies on it
            unknown.append(str(p.relative_to(root)))
            continue
        if flag and card.get("description"):
            out.setdefault(flag, str(card["description"])[:DESC_MAX])
    return out


def collect() -> dict:
    unknown: list[str] = []
    try:
        rows = nos_identity.services()
    except Exception:  # noqa: BLE001
        return {"items": [], "unknown": ["state/manifest.yml"]}
    flags: dict = {}
    try:
        flags = nos_identity.install_flags()
    except Exception:  # noqa: BLE001
        unknown.append("config layers")
    cards = _cards(unknown)
    on = {r.get("id") for r in nos_identity.installed(flags, rows)}
    items = [{"id": r.get("id"), "category": r.get("category"),
              "install_flag": r.get("install_flag"),
              "enabled": (r.get("id") in on) if r.get("install_flag") in flags else None,
              "description": cards.get(r.get("install_flag"))} for r in rows]
    return {"items": items, "unknown": unknown}


def main() -> int:
    try:
        out = collect()
    except Exception as e:  # noqa: BLE001
        out = {"items": [], "unknown": [f"services-status: {type(e).__name__}"]}
    if "--json" in sys.argv[1:]:
        print(json.dumps(out))
        return 0
    for i in out["items"]:
        state = {True: "on", False: "off", None: "UNKNOWN"}[i["enabled"]]
        print(f"{i['id']:<24} {state:<8} {i['category'] or '':<14} {i['description'] or ''}")
    for u in out["unknown"]:
        print(f"UNKNOWN: {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
