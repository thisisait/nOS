"""A provider the playbook forces on is declared once: its manifest row's forced_by.

MEASURED 2026-10-15: redis runs on a core host because Authentik forces
redis_docker on, but the rule lived twice (main.yml's Auto-enable when-lists
and tasks/removal-set.yml's copy), and installed() re-parsed main.yml's
when-shape, skipping any other shape in silence. Now main.yml, removal-set.yml
and nos_identity all read state/manifest.yml forced_by.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

ROWS = {r["id"]: r for r in ni.services()}
FORCED = {"mariadb": "install_mariadb", "postgresql": "install_postgresql", "redis": "redis_docker"}


def _set_facts(node):
    if isinstance(node, list):
        for n in node:
            yield from _set_facts(n)
    elif isinstance(node, dict):
        sf = node.get("ansible.builtin.set_fact") or node.get("set_fact")
        if isinstance(sf, dict):
            yield node.get("name", "?"), sf
        for v in node.values():
            yield from _set_facts(v)


def test_the_manifest_declares_each_forced_provider() -> None:
    for rid, flag in FORCED.items():
        row = ROWS[rid]
        assert row.get("install_flag") == flag and row.get("forced_by"), f"{rid}: no forced_by in state/manifest.yml"
    assert "install_authentik" in ROWS["redis"]["forced_by"], "Authentik forces redis (main.yml, since 2026-05)"


def test_no_task_hand_lists_a_forced_provider() -> None:
    """A set_fact may switch a forced flag on only through the manifest (templated key)."""
    bad = []
    for path in [REPO / "main.yml", *sorted((REPO / "tasks").rglob("*.yml"))]:
        for name, sf in _set_facts(yaml.safe_load(path.read_text(encoding="utf-8"))):
            bad += [f"{path.relative_to(REPO)}: {name} sets {k}" for k in sf if k in FORCED.values()]
    assert not bad, "a second hand list of forced providers:\n" + "\n".join(bad)


def test_installed_counts_a_forced_provider(tmp_path: Path) -> None:
    """Every forced_by entry switches its provider on in install_flags, and core runs redis."""
    defaults = [p for p in ni.layer_paths() if p != REPO / "config.yml"]
    for rid, flag in FORCED.items():
        for trigger in ROWS[rid]["forced_by"]:
            off = tmp_path / f"{rid}-{trigger}.yml"
            off.write_text("".join(f"{f}: false\n" for r in FORCED for f in ROWS[r]["forced_by"])
                           + f"{flag}: false\n{trigger}: true\n")
            assert ni.install_flags([*defaults, off]).get(flag) is True, f"{trigger} does not force {rid}"
    core = ni.install_flags(ni.profile_layers(REPO / "profiles" / "core.yml"))
    assert "redis" in {r["id"] for r in ni.installed(core)}
