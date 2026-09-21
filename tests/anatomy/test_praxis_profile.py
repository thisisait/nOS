"""Anatomy gate — the consulting-firm Mac overlay (profiles/praxis.yml).

RETRO-RED: before this file landed, `profiles/praxis.yml` did not exist.
`PROFILE.is_file()` fails on that tree. Flag asserts fail next: committed
defaults leave WordPress and the consulting fixture off.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PROFILE = REPO / "profiles" / "praxis.yml"


def test_the_praxis_profile_file_exists():
    assert PROFILE.is_file(), (
        "profiles/praxis.yml is missing — the first consulting-firm Mac "
        "has no deployable overlay (`nos -e @profiles/praxis.yml`)"
    )


def test_the_praxis_profile_pins_the_consulting_firm_pack():
    prof = yaml.safe_load(PROFILE.read_text(encoding="utf-8")) or {}
    assert prof.get("install_firefly") is False
    assert prof.get("install_erpnext") is False
    assert prof.get("install_dolibarr") is True
    assert prof.get("install_wordpress") is True
    assert prof.get("keap_seed_consulting_fixture") is True
