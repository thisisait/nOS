"""A tenant the operator calls local is local to every reader, whatever its TLD.

spark1 (2026-10-22): tenant_domain spark1-dgx.bosch.com, config.yml says
tenant_domain_is_local: true (mkcert, not a public CA). The e2e suite decided TLS by
the TLD alone, verified the mkcert chain against certifi and failed 44 probes with
CERTIFICATE_VERIFY_FAILED. nos_identity.is_local_host is the one answer: the
resolved flag for the tenant and its subdomains, the TLD class for any other name.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import nos_identity as ni  # noqa: E402

DEFAULT = """tenant_domain: "dev.local"
tenant_domain_is_local: "{{ (tenant_domain | default('')).endswith(('.local', '.lan')) }}"
"""


def _layers(tmp_path, config: str, monkeypatch) -> list[Path]:
    ni.local_tld_suffixes()  # cached from the real defaults before REPO points at tmp_path
    monkeypatch.setattr(ni, "REPO", tmp_path)  # resolve_flag names each layer relative to the repo
    d, c = tmp_path / "default.config.yml", tmp_path / "config.yml"
    d.write_text(DEFAULT)
    c.write_text(config)
    return [d, c]


def test_the_operator_override_makes_a_public_tld_local(tmp_path, monkeypatch):
    paths = _layers(tmp_path, "tenant_domain: spark1.example.com\ntenant_domain_is_local: true\n", monkeypatch)
    assert ni.is_local_host("spark1.example.com", paths)
    assert ni.is_local_host("auth.spark1.example.com", paths), "a subdomain of the tenant"
    assert not ni.is_local_host("example.com", paths), "the parent is not the tenant"
    assert not ni.is_local_host("auth.pazny.eu", paths), "another name keeps its TLD class"


def test_without_an_override_the_tld_decides(tmp_path, monkeypatch):
    paths = _layers(tmp_path, "tenant_domain: pazny.eu\n", monkeypatch)
    assert not ni.is_local_host("auth.pazny.eu", paths)
    assert ni.is_local_host("auth.dev.local", paths)


def test_an_override_to_false_is_honoured(tmp_path, monkeypatch):
    paths = _layers(tmp_path, "tenant_domain: lab.local\ntenant_domain_is_local: false\n", monkeypatch)
    assert not ni.is_local_host("auth.lab.local", paths)
