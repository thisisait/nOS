"""Anatomy CI gate — every plugin template is one its plugin.yml renders.

MEASURED 2026-10-04: grafana-base/provisioning/datasources/all.yml.j2 still
defined Wing SQLite (and InfluxDB) years after the per-plugin datasource files
replaced it; nothing rendered it, so a reader trusted a copy the estate never saw.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2] / "files/anatomy/plugins"


def test_no_plugin_template_is_dead():
    dead = []
    for tpl in sorted(ROOT.rglob("*.j2")):
        plugin = ROOT / tpl.relative_to(ROOT).parts[0]
        rel = str(tpl.relative_to(plugin))
        manifest = (plugin / "plugin.yml").read_text(encoding="utf-8") if (plugin / "plugin.yml").is_file() else ""
        dirs = [d.strip().strip("'\"").rstrip("/") + "/" for d in re.findall(r"source_dir:\s*(\S+)", manifest)]
        if rel not in manifest and not any(rel.startswith(d) for d in dirs):
            dead.append(f"{plugin.name}/{rel}")
    assert not dead, f"templates no plugin.yml renders (delete or wire them): {dead}"
