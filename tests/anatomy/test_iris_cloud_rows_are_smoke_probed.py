"""Each cloud row Iris may bind is asked by the classic smoke, and a missing key is a SKIP.

WHY. A cloud row armed in config.yml with a dead key or a wrong base_url smoked nothing: no catalog
row asked any LLM backend (2026-10-17, ruling: Iris on anthropic-api / minimax-api like mistral-eu).
The probe POSTs one 1-token chat completion with the row's key, only when the row is armed; with no
key in ~/.nos/secrets.yml it is SKIPPED with the reason — never red (nothing is broken yet) and never
green (nothing was asked). Offline: the network is refused here, the secret lookup is stubbed.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def _smoke():
    spec = importlib.util.spec_from_file_location("_smoke", REPO / "tools" / "nos-smoke.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cloud_rows() -> dict:
    backends = yaml.safe_load((REPO / "state/habitat/llm-backends.yml").read_text())["backends"]
    iris = yaml.safe_load((REPO / "files/anatomy/agents/iris/agent.yml").read_text())
    rows = {r: backends[r] for r in iris["model"]["backends_allowed"] if not backends[r].get("local")}
    assert {"mistral-eu", "anthropic-api", "minimax-api"} <= set(rows), rows
    return rows


def _entries(**vars_dict) -> dict:
    smoke = _smoke()
    catalog = yaml.safe_load((REPO / "state/smoke-catalog.yml").read_text())
    rows = smoke.merge_catalog([], catalog.get("smoke_endpoints") or [], catalog.get("smoke_defaults") or {}, vars_dict)
    return {r["id"]: r for r in rows}


def test_each_cloud_row_of_iris_has_a_keyed_probe_gated_on_its_flag():
    rows = _cloud_rows()
    flags = {b["enabled_flag"]: True for b in rows.values()}
    armed = _entries(**flags, anthropic_api_model="claude-haiku-5-5", minimax_model="MiniMax-M2", mistral_model="m")
    for name, b in rows.items():
        e = armed.get(f"llm-{name}")
        assert e, f"no smoke row llm-{name}"
        assert e["url"] == b["base_url"] + "/chat/completions", e["url"]
        assert (e.get("method"), e.get("bearer_secret"), e.get("when")) == \
            ("POST", b["auth_secret"].removeprefix("nos:"), b["enabled_flag"]), name
        assert e.get("skip_without_secret") is True, f"{name}: no key must skip, not fail"
        assert e.get("require_json") == "choices", f"{name}: a 200 without an answer is not an answer"
        model = e["body"]["model"]
        assert model and "{{" not in model, f"{name}: the body's model id is not resolved: {model!r}"
        assert e["body"].get("max_tokens") == 1, f"{name}: the probe asks for one token"
    assert not [i for i in _entries() if i.startswith("llm-")], "an unarmed row is never probed"


@pytest.fixture
def no_network(monkeypatch):
    smoke = _smoke()

    def refuse(*_a, **_k):
        raise AssertionError("the smoke tried the network")
    monkeypatch.setattr(smoke.urllib.request, "build_opener", refuse)
    monkeypatch.setattr(smoke.urllib.request, "urlopen", refuse)
    return smoke


def test_a_missing_key_skips_with_the_reason_and_is_neither_red_nor_green(no_network, monkeypatch):
    smoke = no_network
    monkeypatch.setattr(smoke, "_secret", lambda name: None)
    entry = _entries(anthropic_api_enabled=True, anthropic_api_model="claude-haiku-5-5")["llm-anthropic-api"]
    r = smoke.probe(entry)
    assert r.skipped and not r.ok, (r.skipped, r.ok)
    assert "anthropic_api_key" in r.error and "skipped" in r.error.lower(), r.error
    table = smoke.render_table([r])
    assert "SKIP" in table and "❌" not in table and "✅" not in table, table


def test_a_row_without_skip_still_fails_on_a_missing_secret(no_network, monkeypatch):
    """The skip is opt-in per row: cortex-executor's missing token stays a red."""
    smoke = no_network
    monkeypatch.setattr(smoke, "_secret", lambda name: None)
    r = smoke.probe({"id": "x", "url": "https://h/", "method": "POST", "bearer_secret": "k", "expect": [200]})
    assert not r.ok and not r.skipped
