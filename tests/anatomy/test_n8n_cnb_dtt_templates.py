"""nOS n8n templates: ČNB pull + DTT push, scored by the Python oracle.

The workflows are importable JSON. They do not hold tokens. KEAP hops use
$vars.keapBase (operator-set) so the committed graph never names RFC-1918.
Live n8n→KEAP still needs n8n_ssrf_allowed_hostnames=<keap_domain> — that is
an operator opt-in, not a default hole (test_n8n_ssrf_protection.py).
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "cnb-dtt.py"
SCHEMA = REPO / "files/anatomy/n8n/templates/cnb-fx.schema.json"
FIXTURE = REPO / "tests/fixtures/cnb-denni_kurz.txt"
PULL = REPO / "files/anatomy/n8n/templates/nos-pull-cnb-fx.json"
PUSH = REPO / "files/anatomy/n8n/templates/nos-push-dtt-webhook.json"
CNB_URL = (
    "https://www.cnb.cz/cs/financni-trhy/devizovy-trh/"
    "kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/denni_kurz.txt"
)
SECRETISH = re.compile(r"(sk-|Bearer [A-Za-z0-9._-]{12,}|_pw_|api[_-]?key\s*[:=])", re.I)
PRIVATE = re.compile(r"127\.0\.0\.1|localhost|10\.\d+\.\d+\.\d+|192\.168\.|172\.(1[6-9]|2\d|3[0-1])\.")


def _load_cnb():
    spec = importlib.util.spec_from_file_location("cnb_dtt", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wf(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _nodes(wf: dict) -> dict[str, dict]:
    return {n["name"]: n for n in wf["nodes"]}


def test_oracle_projects_fixture_onto_schema_columns():
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--cnb-file", str(FIXTURE), "--schema-file", str(SCHEMA)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)
    by_slug = {r["slug"]: r for r in rows}
    assert set(by_slug) == {"2026-09-20-EUR", "2026-09-20-USD", "2026-09-20-JPY"}
    assert by_slug["2026-09-20-EUR"]["rate"] == pytest.approx(24.330)
    assert by_slug["2026-09-20-JPY"]["rate"] == pytest.approx(0.13456)  # per 100 yen
    keys = {c["key"] for c in json.loads(SCHEMA.read_text())["columns"]}
    for row in rows:
        assert set(row) <= keys
        assert "country" not in row


def test_oracle_refuses_a_schema_the_parser_cannot_fill():
    mod = _load_cnb()
    rows = mod.parse_cnb(FIXTURE.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="missing required"):
        mod.project(rows, {"columns": [{"key": "iban", "required": True}]})


def test_pull_template_is_cnb_then_schema_then_upsert():
    wf = _wf(PULL)
    assert wf["meta"]["nos"]["direction"] == "pull"
    nodes = _nodes(wf)
    assert set(nodes) == {"Schedule", "Fetch CNB", "Fetch DTT schema", "Format", "Upsert DTT"}
    assert nodes["Fetch CNB"]["parameters"]["url"] == CNB_URL
    schema_url = nodes["Fetch DTT schema"]["parameters"]["url"]
    upsert_url = nodes["Upsert DTT"]["parameters"]["url"]
    assert "/agent/v1/tables/cnb-fx" in schema_url
    assert "/agent/v1/tables/cnb-fx/rows" in upsert_url
    assert "$vars.keapBase" in schema_url and "$vars.keapBase" in upsert_url
    blob = PULL.read_text()
    assert not SECRETISH.search(blob)
    assert not PRIVATE.search(blob)


def test_push_template_is_webhook_then_dtt_then_callback():
    wf = _wf(PUSH)
    assert wf["meta"]["nos"]["direction"] == "push"
    nodes = _nodes(wf)
    assert nodes["Webhook"]["type"] == "n8n-nodes-base.webhook"
    assert nodes["Webhook"]["parameters"]["path"] == "nos-dtt-push"
    fetch = nodes["Fetch DTT rows"]["parameters"]["url"]
    out = nodes["Push callback"]["parameters"]["url"]
    assert "/agent/v1/tables/" in fetch and "$json.table" in fetch
    assert "callback" in out
    blob = PUSH.read_text()
    assert not SECRETISH.search(blob)
    assert not PRIVATE.search(blob)
    assert "cnb.cz" not in blob


def test_ssrf_defaults_still_do_not_allowlist_keap():
    defaults = (REPO / "roles/pazny.n8n/defaults/main.yml").read_text()
    assert 'n8n_ssrf_allowed_hostnames: ""' in defaults
