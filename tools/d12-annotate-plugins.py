#!/usr/bin/env python3
"""D1.2.b — add `name` + `enabled` to each plugin's authentik block.

Idempotent: skips plugins whose authentik block already declares both
fields. Uses line-surgery (add lines just after `slug:` inside the
`authentik:` block) to preserve YAML comments.

Source of truth for the slug → (display name, install_flag) map is
authentik_oidc_apps in default.config.yml as of 2026-05-05; mappings
that aren't in the central list (qdrant, woodpecker) get a fallback.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PLUGINS = REPO / "files/anatomy/plugins"

# slug → (display name, install_flag). Sourced from default.config.yml's
# authentik_oidc_apps, plus net-coverage entries that the central list
# never carried.
META: dict[str, tuple[str, str]] = {
    "grafana":       ("Grafana",         "install_observability"),
    "gitea":         ("Gitea",           "install_gitea"),
    "portainer":     ("Portainer",       "install_portainer"),
    "outline":       ("Outline",         "install_outline"),
    "open-webui":    ("Open WebUI",      "install_openwebui"),
    "nextcloud":     ("Nextcloud",       "install_nextcloud"),
    "n8n":           ("n8n",             "install_n8n"),
    "metabase":      ("Metabase",        "install_metabase"),
    "gitlab":        ("GitLab",          "install_gitlab"),
    "uptime-kuma":   ("Uptime Kuma",     "install_uptime_kuma"),
    "calibre-web":   ("Calibre-Web",     "install_calibreweb"),
    "homeassistant": ("Home Assistant",  "install_homeassistant"),
    "jellyfin":      ("Jellyfin",        "install_jellyfin"),
    "kiwix":         ("Kiwix",           "install_kiwix"),
    "wordpress":     ("WordPress",       "install_wordpress"),
    "erpnext":       ("ERPNext",         "install_erpnext"),
    "freescout":     ("FreeScout",       "install_freescout"),
    "infisical":     ("Infisical",       "install_infisical"),
    "vaultwarden":   ("Vaultwarden",     "install_vaultwarden"),
    "spacetimedb":   ("SpacetimeDB",     "install_spacetimedb"),
    "paperclip":     ("Paperclip",       "install_paperclip"),
    "superset":      ("Superset",        "install_superset"),
    "puter":         ("Puter",           "install_puter"),
    "wing":          ("Wing",            "install_wing"),
    "miniflux":      ("Miniflux",        "install_miniflux"),
    "hedgedoc":      ("HedgeDoc",        "install_hedgedoc"),
    "bookstack":     ("BookStack",       "install_bookstack"),
    "code-server":   ("code-server",     "install_code_server"),
    "ntfy":          ("ntfy",            "install_ntfy"),
    "nodered":       ("Node-RED",        "install_nodered"),
    "firefly":       ("Firefly III",     "install_firefly"),
    "influxdb":      ("InfluxDB",        "install_influxdb"),
    "onlyoffice":    ("ONLYOFFICE",      "install_onlyoffice"),
    "mailpit":       ("Mailpit",         "install_mailpit"),
    # net coverage (no central entry):
    "qdrant":        ("Qdrant",          "install_qdrant"),
    "woodpecker":    ("Woodpecker CI",   "install_woodpecker"),
}


def annotate(text: str, slug: str, display: str, flag: str) -> tuple[str, bool]:
    """Insert `name:` and `enabled:` lines after the slug: line in the
    authentik: block. Returns (new_text, changed)."""
    # Locate the authentik block. Tolerate any indentation (top-level only).
    # We look for the slug: line within that block.
    has_name = re.search(r"^\s+name:\s+", text, re.M) is not None
    # More precise: check inside authentik block specifically.
    # Easier: detect presence of `enabled:` immediately following slug:
    pat_slug = re.compile(rf"^(?P<indent>\s+)slug:\s*['\"]?{re.escape(slug)}['\"]?\s*$",
                          re.M)
    m = pat_slug.search(text)
    if not m:
        return text, False
    indent = m.group("indent")
    after = text[m.end():]
    # Skip if `enabled:` already appears within next 6 lines.
    next_block = "\n".join(after.splitlines()[:6])
    has_enabled = re.search(r"^\s+enabled:\s+", next_block, re.M) is not None
    has_block_name = re.search(r"^\s+name:\s+", next_block, re.M) is not None
    insert_lines = []
    if not has_block_name:
        insert_lines.append(f"{indent}name: {display!r}")
    if not has_enabled:
        insert_lines.append(f"{indent}enabled: \"{{{{ {flag} | default(false) }}}}\"")
    if not insert_lines:
        return text, False
    # Insert immediately after the slug: line (preserve trailing newline).
    insertion = "\n" + "\n".join(insert_lines)
    new_text = text[:m.end()] + insertion + text[m.end():]
    return new_text, True


def main() -> int:
    changed_count = 0
    for slug, (display, flag) in META.items():
        plugin_yml = PLUGINS / f"{slug}-base" / "plugin.yml"
        if not plugin_yml.is_file():
            print(f"SKIP {slug}: no plugin.yml", file=sys.stderr)
            continue
        text = plugin_yml.read_text()
        new_text, changed = annotate(text, slug, display, flag)
        if changed:
            plugin_yml.write_text(new_text)
            changed_count += 1
            print(f"  + {slug}: name + enabled inserted")
        else:
            print(f"  · {slug}: already annotated (or slug not found)")
    print(f"\n{changed_count}/{len(META)} plugins annotated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
