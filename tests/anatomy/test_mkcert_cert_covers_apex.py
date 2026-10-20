"""Anatomy gate — the local mkcert certificate covers the bare tenant domain.

THE SYMPTOM (2026-10-20, spark1). ``https://<tenant_domain>/`` is the landing
page (``landing_domain`` defaults to ``tenant_domain``) and the face redirect
target, yet the certificate ``tasks/tls-certs.yml`` mints carried only
``*.<tenant_domain>``. A wildcard never matches its own apex (RFC 6125 §6.4.3),
so every browser refused the front door while every subdomain worked.

TWO HALVES, BOTH CHECKED.
  * the mint command must name the apex, or a fresh host gets the bad cert;
  * the SAN check that decides whether to re-mint must list the apex AND must
    compare whole SAN entries: a substring ``grep -F spark1.example`` finds it
    inside ``*.spark1.example`` and reports the old certificate as complete,
    so an estate minted before the fix would never be re-minted.

CEILING. Reads the task file, not the certificate on a host; the effect is
``openssl x509 -ext subjectAltName`` on the live ``ssl_cert_path``.
"""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
TASKS = REPO / "tasks" / "tls-certs.yml"
APEX = "{{ tenant_domain | default('dev.local') }}"


def _tasks():
    out = []

    def walk(items):
        for t in items or []:
            out.append(t)
            walk(t.get("block"))

    walk(yaml.safe_load(TASKS.read_text()))
    return out


def _named(fragment):
    hits = [t for t in _tasks() if fragment in str(t.get("name", ""))]
    assert hits, f"no task named like {fragment!r} in {TASKS.name}"
    return hits[0]


def test_mint_command_names_the_apex():
    cmd = _named("Generate local dev wildcard certificate")["ansible.builtin.command"]
    assert f'"{APEX}"' in cmd, "mkcert is not asked for the bare tenant domain"


def test_required_sans_list_the_apex():
    sans = _named("Build list of required SSL SANs")["ansible.builtin.set_fact"]["_ssl_san_required"]
    assert APEX in sans, "the re-mint check never asks for the bare tenant domain"


def test_san_check_compares_whole_entries():
    shell = _named("Check if SSL cert covers all required SANs")["ansible.builtin.shell"]
    assert "grep -qxF" in shell, "a substring match lets *.<apex> stand in for <apex>"
