"""A persisted n8n API key is probed, not trusted.

Blank 2026-09-29: ~/.nos/secrets.yml survives a data wipe and still held the
API key of the deleted database; the fresh n8n answered 401 and the sync
aborted every from-blank converge. The tool must re-mint when the server
disowns the stored key, and must leave a live key alone.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("n8n_pack", REPO / "tools/n8n-pack.py")
n8n_pack = importlib.util.module_from_spec(spec)
sys.modules["n8n_pack"] = n8n_pack
spec.loader.exec_module(n8n_pack)


def _fake_http(live: set[str]):
    calls: list[str] = []

    def http_json(method, url, api_key="", cookie="", body=None):
        calls.append(f"{method} {url.split('/rest/')[-1] if '/rest/' in url else url}")
        if url.endswith("/rest/login"):
            return 200, {}, "n8n-auth=cookie; Path=/"
        if url.endswith("/rest/api-keys/scopes"):
            return 200, {"data": ["workflow:read", "workflow:activate"]}, ""
        if url.endswith("/rest/api-keys"):
            assert set(body["scopes"]) == {"workflow:read", "workflow:activate"}, body["scopes"]
            return 201, {"data": {"rawApiKey": "fresh-key"}}, ""
        if "/api/v1/workflows" in url:
            return (200, {"data": []}, "") if api_key in live else (401, {"message": "unauthorized"}, "")
        raise AssertionError(url)

    return http_json, calls


def test_a_stale_key_is_reminted_and_persisted(tmp_path: Path, monkeypatch) -> None:
    secrets = tmp_path / "secrets.yml"
    secrets.write_text("n8n_api_key: stale-key\n")
    http_json, calls = _fake_http(live={"fresh-key"})
    monkeypatch.setattr(n8n_pack, "http_json", http_json)
    assert n8n_pack.ensure_api_key("http://n8n", secrets, "a@b", "pw") == "fresh-key"
    assert yaml.safe_load(secrets.read_text())["n8n_api_key"] == "fresh-key"
    assert any(c.endswith("login") for c in calls) and any(c.endswith("api-keys") for c in calls)


def test_the_mint_asks_only_for_scopes_the_server_offers(tmp_path: Path, monkeypatch) -> None:
    """2.37.10 answers 400 "Invalid scopes for user role" to a name it does not
    list; the fake above asserts the POST body is the intersection."""
    http_json, _ = _fake_http(live=set())
    monkeypatch.setattr(n8n_pack, "http_json", http_json)
    assert n8n_pack.mint_api_key("http://n8n", "cookie") == "fresh-key"


def test_a_live_key_is_kept(tmp_path: Path, monkeypatch) -> None:
    secrets = tmp_path / "secrets.yml"
    secrets.write_text("n8n_api_key: live-key\n")
    http_json, calls = _fake_http(live={"live-key"})
    monkeypatch.setattr(n8n_pack, "http_json", http_json)
    assert n8n_pack.ensure_api_key("http://n8n", secrets, "a@b", "pw") == "live-key"
    assert not any(c.endswith("login") for c in calls), "a live key was re-minted"
