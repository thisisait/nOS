"""Endpoint + token resolution priority."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
import tempfile

import pytest

from module_utils.nos_authentik_client import (
    AuthentikApiError,
    resolve_endpoint,
    resolve_token,
)


def test_resolve_endpoint_explicit_wins_over_port_and_domain():
    url = resolve_endpoint(
        explicit="https://explicit.example/api/v3",
        authentik_port=9003,
        authentik_domain="auth.dev.local",
    )
    assert url == "https://explicit.example/api/v3"


def test_resolve_endpoint_port_wins_over_domain():
    url = resolve_endpoint(authentik_port=9003, authentik_domain="auth.dev.local")
    assert url == "http://127.0.0.1:9003/api/v3"


def test_resolve_endpoint_falls_back_to_domain():
    url = resolve_endpoint(authentik_domain="auth.dev.local")
    assert url == "https://auth.dev.local/api/v3"


def test_resolve_endpoint_fails_with_nothing():
    with pytest.raises(AuthentikApiError):
        resolve_endpoint()


def test_resolve_token_explicit_wins(monkeypatch):
    monkeypatch.setenv("ANSIBLE_AUTHENTIK_TOKEN", "env-tok")
    assert resolve_token(explicit="explicit-tok") == "explicit-tok"


def test_resolve_token_secrets_file_before_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ANSIBLE_AUTHENTIK_TOKEN", "env-tok")
    sec = tmp_path / "secrets.yml"
    sec.write_text("authentik_bootstrap_token: file-tok\n")
    assert resolve_token(secrets_path=str(sec)) == "file-tok"


def test_resolve_token_falls_back_to_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ANSIBLE_AUTHENTIK_TOKEN", "env-tok")
    # non-existent secrets file
    assert resolve_token(secrets_path=str(tmp_path / "nope.yml")) == "env-tok"


def test_resolve_token_raises_when_nothing(monkeypatch, tmp_path):
    monkeypatch.delenv("ANSIBLE_AUTHENTIK_TOKEN", raising=False)
    with pytest.raises(AuthentikApiError):
        resolve_token(secrets_path=str(tmp_path / "nope.yml"))
