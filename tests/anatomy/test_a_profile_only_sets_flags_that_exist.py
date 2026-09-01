"""Anatomy CI gate — every key a profile sets must be a variable something reads.

A profile is a pile of `-e` extra-vars, and extra-vars are the HIGHEST
precedence layer in Ansible — which also means a misspelled one is completely
silent. `install_open_webui: false` looks like it turns Open WebUI off. The real
variable is `install_openwebui`. The typo sets a variable nothing reads, the
service starts anyway, and the profile's own comment claims 696 MiB was saved.

MEASURED 2026-09-01 while writing profiles/dev-minimal.yml: FOUR of its 63 keys
were wrong on the first pass — one spelling (`install_open_webui`) and three
that are not role flags at all (`documenso`, `twofauth`, `roundcube` are Tier-2
MANIFEST apps, toggled by `meta.enabled` in apps/<name>.yml). None would have
errored. All four were caught by rendering the profile against the config
rather than reading it.

The estate already has the end state of this defect committed elsewhere:
`install_cask_apps` is presented as a user-facing toggle in docs/index.html
with `default_enabled: true` and NOTHING implements it.

WHAT THIS GATE DELIBERATELY DOES NOT CHECK. A first draft also refused any
profile that pinned a fact apps_runner sets dynamically (`install_qdrant`). Its
first act was to fail all-on.yml, where the pin is deliberate, commented and
correct — the profile wants the feature_flag wiring on regardless of the
catalog. "Know what you are pinning" is not cheaply gateable, and a gate whose
opening move is a false positive on committed code teaches people to ignore it.
The declaration check below is the part that actually catches mistakes.

So: every key in profiles/*.yml must be declared in default.config.yml. That is
the artifact check — not "does it look like a flag".
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
