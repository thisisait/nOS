"""nOS n8n ARES/ADIS template: n8n Schedule is the clock; webhook stays for on-create.

Pulse fire (ares-verify-base) remains until exec-watch is seen live.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "ares-dtt.py"
PULL = REPO / "files/anatomy/n8n/templates/nos-pull-ares-registry.json"
ARES = REPO / "tests/fixtures/ares-registry.json"
ADIS = REPO / "tests/fixtures/ares-adis-unreliable.xml"
SECRETISH = re.compile(r"(sk-|Bearer [A-Za-z0-9._-]{12,}|_pw_|api[_-]?key\s*[:=])", re.I)
PRIVATE = re.compile(r"127\.0\.0\.1|localhost|10\.\d+\.\d+\.\d+|192\.168\.|172\.(1[6-9]|2\d|3[0-1])\.")


def _wf() -> dict:
    return json.loads(PULL.read_text(encoding="utf-8"))


def _nodes(wf: dict) -> dict[str, dict]:
    return {n["name"]: n for n in wf["nodes"]}


def test_oracle_projects_fixture_onto_registry_row():
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--ares-file", str(ARES), "--adis-file", str(ADIS),
         "--ico", "00000131", "--party", "party-ico-00000131"],
        cwd=REPO, capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    row = json.loads(proc.stdout)
    assert row["slug"] == "reg-ico-00000131"
    assert row["ares_found"] is True
    assert row["vat_reliability"] == "unreliable"
    assert row["legal_name_ares"] == "Alfa s.r.o."
    # The seat as a RÚIAN address point — the geo projection's join key.
    assert row["sidlo_ruian_adm"] == 21700184


def test_graph_carries_the_seat_address_point_like_the_oracle():
    code = _nodes(_wf())["Format"]["parameters"]["jsCode"]
    assert "sidlo.kodAdresnihoMista" in code and "row.sidlo_ruian_adm" in code


def test_oracle_treats_missing_ares_as_not_a_payer():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ares_dtt", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    row = mod.project(ico="12345678", party="party-ico-12345678", ares=None, vat="unknown", when=0)
    assert row["ares_found"] is False
    assert row["vat_reliability"] == "not_payer"


def test_pull_template_is_webhook_then_ares_adis_upsert():
    wf = _wf()
    assert wf["meta"]["nos"]["clock"] == "n8n-schedule"
    assert wf["meta"]["nos"]["table"] == "party-registry-status"
    nodes = _nodes(wf)
    assert nodes["Webhook"]["type"] == "n8n-nodes-base.webhook"
    assert nodes["Webhook"]["parameters"]["path"] == "nos-ares-registry"
    assert nodes["Schedule"]["type"] == "n8n-nodes-base.scheduleTrigger"
    assert nodes["Schedule"]["parameters"]["rule"]["interval"][0]["expression"] == "10 5 * * *"
    assert "ares.gov.cz" in nodes["Fetch ARES"]["parameters"]["url"]
    assert "adisrws.mfcr.cz" in nodes["Fetch ADIS"]["parameters"]["url"]
    upsert = nodes["Upsert DTT"]["parameters"]["url"]
    assert "party-registry-status/rows" in upsert
    assert "$vars.keapBase" in upsert
    blob = PULL.read_text()
    assert not SECRETISH.search(blob)
    assert not PRIVATE.search(blob)


def test_the_pack_carries_its_own_clock():
    """The ARES pull is scheduled inside n8n (deleted Pulse clock, 2026-10-02)."""
    wf = json.loads((REPO / "files/anatomy/n8n/templates/nos-pull-ares-registry.json").read_text())
    assert any(n["type"] == "n8n-nodes-base.scheduleTrigger" for n in wf["nodes"])
