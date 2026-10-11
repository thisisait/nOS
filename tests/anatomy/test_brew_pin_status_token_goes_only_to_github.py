"""The GitHub token leaves tools/brew-pin-status.py only for api.github.com.

`"api.github.com" in url` also matches https://api.github.com.example.net/ and
any URL that carries the string in its path or query, so the operator's token
would be sent to that host. The check must read the parsed hostname.
"""
from __future__ import annotations

import importlib.util
import io
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "brew_pin_status", REPO / "tools" / "brew-pin-status.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _auth_sent(monkeypatch, url: str) -> bool:
    mod = _load()
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append(req.get_header("Authorization"))
        return io.BytesIO(b"{}")

    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    mod._get(url)
    return seen[0] is not None


def test_the_token_goes_to_api_github_com(monkeypatch):
    assert _auth_sent(monkeypatch, "https://api.github.com/repos/x/y/commits")


def test_the_token_never_goes_to_a_lookalike_host(monkeypatch):
    for url in ("https://api.github.com.example.net/x",
                "https://example.net/?u=api.github.com"):
        assert not _auth_sent(monkeypatch, url), f"token sent to {url}"
