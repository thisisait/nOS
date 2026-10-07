"""Gate: a plugin's feature_flag is the flag its role actually runs under.

2026-10-01: backup-base declared configure_backup (restic copy #2, default off)
while main.yml imports pazny.backup under install_backup — so the loader skipped
the plugin that routes the nightly backup's alarms, on every default estate.
"""
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _role_flags() -> dict:
    """role name -> the install_*/configure_* flags in the `when` that runs it."""
    out: dict = {}

    def walk(node):
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            for key in ("ansible.builtin.import_role", "ansible.builtin.include_role", "import_role", "include_role"):
                role = (node.get(key) or {}).get("name") if isinstance(node.get(key), dict) else None
                if role:
                    out.setdefault(role, set()).update(re.findall(r"\b((?:install|configure)_\w+)", str(node.get("when", ""))))
            for v in node.values():
                if isinstance(v, (list, dict)):
                    walk(v)
    for f in [REPO / "main.yml", *(REPO / "tasks/stacks").glob("*.yml")]:
        walk(yaml.safe_load(f.read_text(encoding="utf-8")))
    return out


def test_feature_flag_matches_the_roles_gate():
    flags = _role_flags()
    bad = []
    for f in sorted((REPO / "files/anatomy/plugins").glob("*/plugin.yml")):
        req = (yaml.safe_load(f.read_text()) or {}).get("requires") or {}
        role, flag = req.get("role"), req.get("feature_flag")
        if role and flag and flags.get(role) and flag not in flags[role] and not req.get("role_flag_differs"):
            bad.append(f"{f.parent.name}: feature_flag {flag}, but {role} runs under {sorted(flags[role])}")
    assert not bad, "\n".join(bad)
    assert "install_backup" in flags.get("pazny.backup", set()), "the detector lost its positive case"
