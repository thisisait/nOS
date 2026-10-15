"""nOS's own organs (manifest software_owner: self) are the core tier, never a bonus lane.

Ruling 2026-10-15: a bonus lane runs only when its paths change or once a week, so an
organ placed there (apex, nos_forum sat in iiab) goes untested on most pushes. The tier
is derived from software_owner in tools/test-tiers.py, no new manifest stack value.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def _tiers():
    spec = importlib.util.spec_from_file_location("_nos_test_tiers", REPO / "tools" / "test-tiers.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.derive()


def _own() -> list[dict]:
    rows = yaml.safe_load((REPO / "state" / "manifest.yml").read_text(encoding="utf-8"))["services"]
    own = [r for r in rows if r.get("software_owner") == "self"]
    assert own, "no manifest row has software_owner: self"
    return own


def test_no_lane_carries_an_own_organs_flag_or_role() -> None:
    lanes = _tiers()["lanes"]
    hits = [(name, r["id"]) for r in _own() for name, lane in lanes.items()
            if r["install_flag"] in lane["flags"] or f"roles/pazny.{r['id']}/" in lane["paths"]]
    assert not hits, f"own organs in a bonus lane (lane, id): {hits}"


def test_no_lane_carries_an_own_organs_plugin() -> None:
    own_flags = {r["install_flag"] for r in _own()}
    plugins = {f"files/anatomy/plugins/{p.parent.name}/" for p in (REPO / "files/anatomy/plugins").glob("*/plugin.yml")
               if ((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("requires") or {}).get("feature_flag")
               in own_flags}
    hits = sorted((name, p) for name, lane in _tiers()["lanes"].items() for p in lane["paths"] if p in plugins)
    assert not hits, f"an own organ's plugin is in a bonus lane: {hits}"


def test_no_lane_owned_test_names_an_own_organ() -> None:
    d = _tiers()
    token = re.compile(r"(?<![\w.-])(" + "|".join(
        t for r in _own() for t in (re.escape(r["install_flag"]), re.escape(f"pazny.{r['id']}"))) + r")(?![\w-])")
    hits = {f: (tier, sorted(set(token.findall((REPO / "tests" / "anatomy" / f).read_text(encoding="utf-8")))))
            for f, tier in d["tests"].items() if tier in d["lanes"]}
    hits = {f: v for f, v in hits.items() if v[1]}
    assert not hits, f"a test naming an own organ is owned by a bonus lane: {hits}"
