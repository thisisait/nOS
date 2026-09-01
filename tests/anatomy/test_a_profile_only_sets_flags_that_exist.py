"""Anatomy CI gate — every key a profile sets must be a variable something reads.

Profiles are extra-vars, the highest-precedence layer, so a misspelled key is
SILENT. MEASURED 2026-09-01: 4 of dev-minimal's 63 keys were wrong on the first
pass — `install_open_webui` (really `install_openwebui`) plus three Tier-2
manifest apps that have no role flag at all. None errored; each would have left
its service running while the profile claimed the memory back.

A first draft also refused pinning apps_runner's dynamic `install_qdrant`. It
failed all-on.yml, where the pin is deliberate and commented — dropped, because
a gate that opens with a false positive on correct code gets ignored.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
PROFILES = sorted((REPO / "profiles").glob("*.yml"))


def _declared() -> set[str]:
    txt = (REPO / "default.config.yml").read_text(encoding="utf-8")
    return set(re.findall(r"^([a-z0-9_]+):", txt, re.M))


def test_the_sweep_finds_profiles():
    """Positive control — an empty glob makes everything below vacuous."""
    assert len(PROFILES) >= 2, (
        f"only {len(PROFILES)} profile(s) found; the glob has stopped matching")


@pytest.mark.parametrize("path", PROFILES, ids=lambda p: p.name)
def test_every_key_is_a_declared_variable(path):
    prof = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    unknown = sorted(k for k in prof if k not in _declared())
    assert not unknown, (
        f"{path.name} sets {len(unknown)} key(s) that default.config.yml does "
        f"not declare. Extra-vars are the highest precedence layer, so a "
        f"misspelled one is SILENT — the service it names keeps running while "
        f"the profile claims it was turned off:\n  " + "\n  ".join(unknown))
