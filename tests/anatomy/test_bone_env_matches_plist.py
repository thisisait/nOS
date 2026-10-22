"""Anatomy gate — the Linux Bone unit carries the environment the macOS plist carries.

THE SYMPTOM (2026-10-22, spark1). Once face could reach Bone on the docker bridge,
saving an Iris layout answered "user-state not configured (BONE_VFS_TOKEN unset)":
the systemd env dict in roles/pazny.bone/tasks/main.yml had never been given
BONE_VFS_TOKEN, NOS_DATA_ROOT, NOS_TENANT_SLUG, KEAP_AGENT_TOKEN_RO,
CORTEX_AGENT_TOKEN_RO or WING_AUDIT_CHAIN_ENABLED. One service, two service managers.

THE CHECK. The variable names the plist sets are the names the systemd env sets
(launchd-only names would be listed here with their reason; there are none today).

CEILING. Compares names, not values; the effect is the running Bone's environment.
"""

import re
from pathlib import Path

ROLE = Path(__file__).resolve().parents[2] / "roles" / "pazny.bone"
LAUNCHD_ONLY: set[str] = set()


def _plist() -> set[str]:
    text = (ROLE / "templates" / "bone.plist.j2").read_text(encoding="utf-8")
    return set(re.findall(r"<key>([A-Z][A-Z0-9_]+)</key>", text[text.index("EnvironmentVariables"):]))


def _systemd() -> set[str]:
    text = (ROLE / "tasks" / "main.yml").read_text(encoding="utf-8")
    block = text[text.index("_bone_systemd_env:"):text.index("Install systemd --user service")]
    return set(re.findall(r"'([A-Z][A-Z0-9_]+)':", block))


def test_the_systemd_unit_sets_every_name_the_plist_sets():
    missing = sorted(_plist() - LAUNCHD_ONLY - _systemd())
    assert not missing, f"the Linux Bone unit lacks {missing}: Bone on systemd runs without them"


def test_the_systemd_unit_sets_nothing_the_plist_does_not():
    extra = sorted(_systemd() - _plist())
    assert not extra, f"only the Linux Bone unit sets {extra}: add them to bone.plist.j2 too"
