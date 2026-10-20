# nOS — `flags | nos_installed(rows)`: the manifest rows this host runs.
# Ansible's face of tools/nos_identity.installed, so a template and the readers
# share one derivation. Gate: tests/anatomy/test_service_registry_is_the_installed_set.py.
# `playbook_dir | nos_hub_cards`: each plugin's hub_card display fields keyed by
# registry id, joined into service-registry.json. Gate: test_one_service_directory.py.

import sys
from pathlib import Path


def nos_installed(flags, rows=None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from nos_identity import installed  # noqa: PLC0415

    return installed(dict(flags), list(rows) if rows is not None else None)


def nos_hub_cards(playbook_dir):
    """{id: {name, icon, description, rbac_tier, backend}} from plugin.yml hub_card
    (literal fields only — a templated value stays with the loader's render)."""
    import yaml  # noqa: PLC0415

    out = {}
    for p in sorted(Path(playbook_dir, "files/anatomy/plugins").glob("*-base/plugin.yml")):
        m = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        card = (m.get("ui-extension") or {}).get("hub_card") or {}
        row = {k: card[src] for k, src in (("name", "title"), ("icon", "icon"), ("description", "description"),
                                           ("rbac_tier", "tier"))
               if src in card and "{{" not in str(card[src])}
        if m.get("kind") == "backend":
            row["backend"] = True
        if row:
            out[p.parent.name.removesuffix("-base").replace("-", "_")] = row
    return out


class FilterModule:
    def filters(self):
        return {"nos_installed": nos_installed, "nos_hub_cards": nos_hub_cards}
