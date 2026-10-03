"""Anatomy gate — an enabled tileserver must serve at least one dataset and one style.

2026-10-03: `install_offline_maps` was on, the container healthy, `/index.json`
returned `[]`. The Zurich fixture URL 404'd under `failed_when: false`, the
config block was `"styles": {}` and the health probe accepted 4xx. Nothing in
the estate was red. This gate reads the rendered tileserver config, the
vendored style, the plugin probes and the role's error handling:

  1. config.json.j2 rendered with defaults has >=1 `data` entry and >=1 style,
     every style file is vendored and every `pmtiles://{id}` source it uses is
     a declared data id;
  2. the role never hides a download/build failure (`failed_when: false`);
  3. the plugin's e2e probes read the style and the dataset back (200 only)
     and the health wait is strict;
  4. post_blank removes `maps_data_dir`, not a hard-coded `~/maps`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
ROLE = REPO / "roles/pazny.offline_maps"
PLUGIN = REPO / "files/anatomy/plugins/offline-maps-base/plugin.yml"

DEFAULTS = {
    "maps_region": "czech-republic",
    "_maps_extra_files": [],
}


def _rendered_config() -> dict:
    tpl = ROLE / "templates/config.json.j2"
    assert tpl.exists(), "tileserver config must be a template the gate can render"
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, trim_blocks=True, lstrip_blocks=True)
    return json.loads(env.from_string(tpl.read_text()).render(**DEFAULTS))


def test_rendered_config_declares_a_dataset_and_a_style():
    cfg = _rendered_config()
    assert cfg.get("data"), "an enabled tileserver with zero datasets is red"
    assert cfg.get("styles"), "an enabled tileserver with zero styles is red"
    for sid, style in cfg["styles"].items():
        path = ROLE / "files/styles" / style["style"]
        assert path.exists(), f"style {sid} points at {style['style']} which is not vendored"
        for src in json.loads(path.read_text())["sources"].values():
            m = re.fullmatch(r"pmtiles://\{(.+)\}", src.get("url", ""))
            assert m and m.group(1) in cfg["data"], (
                f"style {sid} source {src.get('url')!r} is not a declared data id {list(cfg['data'])}")


def test_role_does_not_hide_failures():
    text = (ROLE / "tasks/main.yml").read_text()
    assert "failed_when: false" not in text, "a map that fails to arrive must fail the play"


def test_plugin_reads_the_served_map_back():
    plugin = yaml.safe_load(PLUGIN.read_text())
    probes = {p["name"]: p for p in plugin["e2e"]["probes"]}
    urls = " ".join(p["url"] for p in probes.values())
    assert "/styles/" in urls and "/style.json" in urls, "no probe reads a style back"
    assert "/data/" in urls and ".json" in urls, "no probe reads the dataset TileJSON back"
    for p in probes.values():
        assert p.get("expect", {}).get("status", [200]) == [200], f"{p['name']} accepts a non-200"
    waits = [a["wait_health"] for a in plugin["lifecycle"]["post_compose"] if "wait_health" in a]
    assert waits and not any(isinstance(w, dict) and w.get("accept_any_2xx_3xx_4xx") for w in waits), (
        "health wait must not accept 4xx — a 404 index was 'healthy' for months")
    blanks = [a["remove_dir"] for a in plugin["lifecycle"]["post_blank"] if "remove_dir" in a]
    assert any("maps_data_dir" in b for b in blanks), "post_blank must remove maps_data_dir"
