"""A sanction cuts a symbiont at the edge, reversibly, and a converge keeps it.

Row immune-panic-mode, first effector (operator 2026-10-24: "základní sankce —
obrana proti bezpečnostním dírám v symbiontu"). Jellyfin 10.11.11 carried a
critical path traversal with no fix on its line; the only answers were "wait"
or "remove it". A sanction is the third: every manifest router carries
sanction-<router>@file first, open by default; tools/nos-sanction.py narrows
it to 127.0.0.1/32 (403 to every caller) and lifts it again; the record in
~/.nos/sanctions.yml makes the converge render the same cut.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
ROLE = REPO / "roles" / "pazny.traefik"
_spec = importlib.util.spec_from_file_location("origin", REPO / "tests/anatomy/test_origin_pull_is_a_second_door.py")
_origin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_origin)
_tool = importlib.util.spec_from_file_location("nos_sanction", REPO / "tools" / "nos-sanction.py")
sanction = importlib.util.module_from_spec(_tool)
_tool.loader.exec_module(sanction)


def _render(rel: str, held: dict | None = None) -> dict:
    return yaml.safe_load(_origin.render(rel, nos_sanctions=held or {}))


def test_every_router_and_lane_is_cut_first():
    routers = _render("roles/pazny.traefik/templates/dynamic/services.yml.j2")["http"]["routers"]
    defined = set(_render("roles/pazny.traefik/templates/dynamic/sanctions.yml.j2")["http"]["middlewares"])
    manifest_ids = {s["id"].replace("_", "-") for s in yaml.safe_load((REPO / "state/manifest.yml").read_text())["services"]}
    checked = 0
    for name, r in routers.items():
        mw = r.get("middlewares") or []
        cut = [m for m in mw if m.startswith("sanction-")]
        base = name.removesuffix("-origin")
        if not any(base == i or base.startswith(i + "-") for i in manifest_ids) or not cut:
            continue  # extra routers (dashboard, bare-ip) are not symbionts
        checked += 1
        assert mw[0] == cut[0], f"{name}: the sanction must run before auth: {mw}"
        assert cut[0].removesuffix("@file") in defined, f"{name} references an undefined {cut[0]}"
    assert checked > 20, f"only {checked} routers carry a sanction"
    jellyfin = routers["jellyfin"]["middlewares"]
    assert jellyfin[0] == "sanction-jellyfin@file", jellyfin


def test_the_render_is_open_unless_the_record_holds_the_id():
    mw = _render("roles/pazny.traefik/templates/dynamic/sanctions.yml.j2")["http"]["middlewares"]
    assert mw["sanction-jellyfin"]["ipAllowList"]["sourceRange"] == ["0.0.0.0/0", "::/0"]
    mw = _render("roles/pazny.traefik/templates/dynamic/sanctions.yml.j2",
                 {"jellyfin": {"level": "edge"}})["http"]["middlewares"]
    assert mw["sanction-jellyfin"]["ipAllowList"]["sourceRange"] == ["127.0.0.1/32"]
    assert mw["sanction-rustfs"]["ipAllowList"]["sourceRange"] == ["0.0.0.0/0", "::/0"]


def test_the_tool_plans_without_confirm_and_cuts_and_lifts_with_it(tmp_path, monkeypatch, capsys):
    conf = tmp_path / "stacks" / "infra" / "traefik" / "conf.d"
    conf.mkdir(parents=True)
    (conf / "sanctions.yml").write_text(_origin.render("roles/pazny.traefik/templates/dynamic/sanctions.yml.j2",
                                                       nos_sanctions={}))
    monkeypatch.setenv("NOS_STACKS_DIR", str(tmp_path / "stacks"))
    monkeypatch.setattr(sanction, "RECORD", tmp_path / "sanctions.yml")
    monkeypatch.setattr(sanction, "containers", lambda sid: [])

    def cut():
        return yaml.safe_load((conf / "sanctions.yml").read_text())["http"]["middlewares"]["sanction-jellyfin"]

    assert sanction.main(["jellyfin", "--reason", "GHSA-6828"]) == 0
    assert cut()["ipAllowList"]["sourceRange"] == ["0.0.0.0/0", "::/0"], "a plan must change nothing"
    assert not (tmp_path / "sanctions.yml").exists()

    assert sanction.main(["jellyfin", "--reason", "GHSA-6828", "--confirm"]) == 0
    assert cut()["ipAllowList"]["sourceRange"] == ["127.0.0.1/32"]
    held = yaml.safe_load((tmp_path / "sanctions.yml").read_text())["sanctions"]
    assert held["jellyfin"]["reason"] == "GHSA-6828" and held["jellyfin"]["level"] == "edge"
    rerender = yaml.safe_load(_origin.render("roles/pazny.traefik/templates/dynamic/sanctions.yml.j2",
                                             nos_sanctions=held))["http"]["middlewares"]
    assert rerender["sanction-jellyfin"] == cut(), "a converge would lift what the tool cut"

    assert sanction.main(["jellyfin", "--lift", "--confirm"]) == 0
    assert cut()["ipAllowList"]["sourceRange"] == ["0.0.0.0/0", "::/0"]
    assert "jellyfin" not in (yaml.safe_load((tmp_path / "sanctions.yml").read_text())["sanctions"] or {})


def test_red_status_holds_a_sanction_in_view():
    spec = importlib.util.spec_from_file_location("red_status", REPO / "tools" / "red-status.py")
    red = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(red)
    lines = red.hold_lines({"sanctions": {"jellyfin": {"level": "edge", "at": "2026-10-24T20:00:00+00:00",
                                                         "reason": "GHSA-6828"}}})
    assert any("jellyfin sanctioned (edge)" in ln and "--lift" in ln for ln in lines), lines


def test_a_sanction_needs_a_reason_and_a_real_row(tmp_path, monkeypatch):
    monkeypatch.setattr(sanction, "RECORD", tmp_path / "sanctions.yml")
    assert sanction.main(["jellyfin", "--confirm"]) == 2
    assert sanction.main(["no-such-organ", "--reason", "x", "--confirm"]) == 2
    assert not (tmp_path / "sanctions.yml").exists()
