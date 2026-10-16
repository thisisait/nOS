"""Gate: the SSO tools verify a local TLD against the mkcert root CA.

Client host 2026-10-16 (tenant_domain jan.internal): the [Identities] task
printed 33 urllib3 InsecureRequestWarnings for auth./keap.jan.internal —
nos-first-login ran with verify=False although the estate minted that CA.
No CA on disk: one stderr line, then unverified without a warning per request.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import warnings
from pathlib import Path

import pytest

pytest.importorskip("requests")
from urllib3.exceptions import InsecureRequestWarning  # noqa: E402

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
import nos_sso  # noqa: E402


@pytest.fixture
def ca(tmp_path, monkeypatch):
    (tmp_path / "rootCA.pem").write_text("-----BEGIN CERTIFICATE-----\n")
    monkeypatch.setenv("CAROOT", str(tmp_path))
    return str(tmp_path / "rootCA.pem")


@pytest.fixture
def no_ca(tmp_path, monkeypatch):
    monkeypatch.setenv("CAROOT", str(tmp_path / "none"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "")


def test_a_local_tld_verifies_against_the_mkcert_root(ca):
    assert nos_sso.tls_verify(local=True) == ca
    assert nos_sso.tls_verify(local=False) is True


def test_no_ca_falls_back_once_and_quietly(no_ca, capsys):
    with warnings.catch_warnings(record=True) as seen:
        assert nos_sso.tls_verify(local=True) is False
        warnings.warn("probe", InsecureRequestWarning)
    assert not seen
    assert len(capsys.readouterr().err.strip().splitlines()) == 1


def _tool(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), TOOLS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("tool,argv", [
    ("nos-first-login.py", []),
    ("woodpecker-token.py", ["--user=akadmin", "--gitea-public=https://git.jan.internal",
                             "--woodpecker-public=https://ci.jan.internal"]),
])
def test_both_sso_tools_pass_the_ca(tool, argv, ca, monkeypatch):
    mod = _tool(tool)
    got = []

    def login(*a, verify=None, **k):
        got.append(verify)
        raise RuntimeError("stop")

    monkeypatch.setattr(mod, "login", login)
    monkeypatch.setattr(mod, "loopback_for_unresolvable", lambda: None)
    monkeypatch.setattr(mod, "_plan", lambda: [], raising=False)
    monkeypatch.setenv("NOS_FIRST_LOGIN", json.dumps([{"name": "akadmin", "password": "x"}]))
    monkeypatch.setenv("SSO_PASSWORD", "x")
    mod.main(["--auth-host=auth.jan.internal", "--local-tld", *argv])
    assert got == [ca]
