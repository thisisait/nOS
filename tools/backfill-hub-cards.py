#!/usr/bin/env python3
"""One-shot: backfill ui-extension hub_card on user-facing web services.

Adds a Wing /hub deep-link card to the 6 native_oidc web apps that lacked one
(gitlab, homeassistant, n8n, nextcloud, open-webui, outline). Forward-ready for
the Wing hub-card harvest; matches the woodpecker-base/grafana-base shape.
Infra daemons (mariadb/postgres/redis/alloy/watchtower) are intentionally NOT
given a card — they have no user-facing UI.

Idempotent — skips any plugin that already declares a ui-extension block.
Textual append so inline comments survive. Run from repo root.
"""
from __future__ import annotations

import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
PLUGINS_ROOT = REPO / "files" / "anatomy" / "plugins"

# domain var, title, icon, tier, description — domain vars are defined by the
# playbook (same bare form woodpecker-base uses for woodpecker_domain).
CARDS = {
    "gitlab-base":        ("gitlab_domain",       "GitLab",         "git",            2, "DevOps platform — repos, CI/CD, registry"),
    "homeassistant-base": ("homeassistant_domain", "Home Assistant", "home-automation", 3, "Home automation hub"),
    "n8n-base":           ("n8n_domain",          "n8n",            "workflow",       2, "Workflow automation"),
    "nextcloud-base":     ("nextcloud_domain",    "Nextcloud",      "cloud",          3, "Self-hosted cloud — files, calendar, contacts"),
    "open-webui-base":    ("openwebui_domain",    "Open WebUI",     "ai-chat",        3, "Chat UI for local Ollama models"),
    "outline-base":       ("outline_domain",      "Outline",        "wiki",           3, "Team wiki / knowledge base"),
}

TEMPLATE = """
# ── Wing /hub card (ui-extension) ────────────────────────────────────────────
# Forward-ready deep-link card for the Wing hub (harvest pending). Matches the
# woodpecker-base/grafana-base shape. domain var is playbook-defined.
ui-extension:
  hub_card:
    title: {title}
    icon: {icon}
    url: "https://{{{{ {domain} }}}}"
    tier: {tier}
    description: {description}
    health_check: "https://{{{{ {domain} }}}}"
"""


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    done, skipped = [], []
    for name, (domain, title, icon, tier, desc) in CARDS.items():
        manifest = PLUGINS_ROOT / name / "plugin.yml"
        if not manifest.is_file():
            skipped.append(f"{name}(missing)")
            continue
        m = yaml.safe_load(manifest.read_text()) or {}
        if m.get("ui-extension"):
            skipped.append(f"{name}(has)")
            continue
        block = TEMPLATE.format(title=title, icon=icon, domain=domain,
                                tier=tier, description=desc)
        if not dry:
            text = manifest.read_text()
            if not text.endswith("\n"):
                text += "\n"
            manifest.write_text(text + block)
        done.append(name)
    print(f"added hub_card ({len(done)}): {', '.join(done)}")
    if skipped:
        print(f"skipped ({len(skipped)}): {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
