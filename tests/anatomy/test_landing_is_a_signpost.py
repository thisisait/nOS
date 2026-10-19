"""The landing page signposts what is routed, and never shares the root domain.

roles/pazny.landing (2026-10-19) serves the estate's root domain to its own
people. Three things keep it honest: its cards come from the plugin harvest
filtered to hosts Traefik actually routes (a card to a 404 is worse than
none), it refuses to run beside apex (both claim the root domain), and it
hands out only the PUBLIC half of the local CA.
"""
from __future__ import annotations

import pathlib

import yaml

ROLE = pathlib.Path(__file__).resolve().parents[2] / "roles" / "pazny.landing"


def _tasks() -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())


def test_cards_are_the_routed_harvest():
    fact = next(t for t in _tasks() if "_landing_cards" in (t.get("ansible.builtin.set_fact") or {}))
    expr = fact["ansible.builtin.set_fact"]["_landing_cards"]
    assert "_landing_routed.stdout_lines" in expr and "selectattr('url', 'search'" in expr
    routed = next(t for t in _tasks() if t.get("register") == "_landing_routed")
    assert "Host(`" in routed["ansible.builtin.shell"] and "conf.d" in routed["ansible.builtin.shell"]


def test_it_refuses_to_share_the_root_domain_with_apex():
    first = _tasks()[0]
    assert "install_apex" in first["ansible.builtin.assert"]["that"]


def test_only_the_public_half_of_the_ca_is_served():
    ca = next(t for t in _tasks() if "nos-root-ca.pem" in str(t.get("ansible.builtin.copy", {}).get("dest", "")))
    src = ca["ansible.builtin.copy"]["src"]
    assert src.endswith("rootCA.pem") and "key" not in src.lower()
