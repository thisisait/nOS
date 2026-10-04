"""A profile key that resolves to nothing is silently inert.

Profiles are extra-var overlays: `nos -e @profiles/praxis.yml`. Ansible does not
complain about a key nobody reads, so `install_uptimekuma: false` (no
underscore) would look like a decision and change nothing. Nothing checked.

WHAT THIS PINS, and why each part:

1. EVERY key a profile sets is declared somewhere that loads — default.config.yml,
   default.credentials.yml, or a role default. This is the silent-inert check.
   It was green when written (2026-09-27); it is preventive, which is the point
   of writing it before the first typo rather than after.

2. A profile declares its AXIS. Four were already in use without being named:
     use-case     which services, for whom          praxis
     policy       posture, barely any service flags gov-local
     service-set  the size of the estate            all-on, dev-minimal
     environment  what the host cannot do           cloud-e2e
     constraint   what the MEDIUM cannot take       flash
   The axis is what makes composition legible: a reader who knows `flash` is a
   constraint knows it only subtracts, without reading it.

3. A CONSTRAINT profile may only subtract. The moment one enables a service it
   is expressing a want, and `use-case + constraint` stops being something you
   can reason about in either order. This is the invariant that makes the
   folder a system rather than five files.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROFILES = sorted((REPO / "profiles").glob("*.yml"))
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

AXES = {"use-case", "policy", "service-set", "environment", "constraint"}

#: Where a variable may be declared such that a profile overlay actually reaches
#: something. Role defaults count: they load during stack-up, which is after the
#: overlay is applied.
def _declared() -> set[str]:
    names: set[str] = set()
    for p in [*ni.default_layers(), REPO / "default.credentials.yml",
              *(REPO / "roles").glob("*/defaults/main.yml")]:
        if p.is_file():
            names |= set(re.findall(r"^([a-z_][a-z0-9_]*):", p.read_text(encoding="utf-8"), re.M))
    return names


def _keys(path: Path) -> list[tuple[str, str]]:
    """Top-level `key: value` pairs a profile sets."""
    return re.findall(r"^([a-z_][a-z0-9_]*):[ \t]*(\S*)",
                      path.read_text(encoding="utf-8"), re.M)


def _axis(path: Path) -> str | None:
    m = re.search(r"^#\s*axis:\s*([a-z-]+)\s*$", path.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def test_there_are_profiles_to_check():
    """An empty glob must not read as a pass."""
    assert PROFILES, "no profiles found — this gate would vacuously pass"


@pytest.mark.parametrize("path", PROFILES, ids=lambda p: p.name)
def test_every_profile_key_resolves_to_a_declared_variable(path):
    declared = _declared()
    unknown = sorted({k for k, _ in _keys(path)} - declared)
    assert not unknown, (
        f"{path.name} sets key(s) nothing declares: {unknown}. Ansible will "
        "accept the overlay and read none of them, so the profile looks like a "
        "decision and changes nothing. Check the spelling against "
        "default.config.yml or the owning role's defaults."
    )


@pytest.mark.parametrize("path", PROFILES, ids=lambda p: p.name)
def test_every_profile_declares_its_axis(path):
    axis = _axis(path)
    assert axis is not None, (
        f"{path.name} has no `# axis:` line. Profiles compose, and a reader "
        f"cannot compose safely without knowing which kind this is. One of: "
        f"{sorted(AXES)}"
    )
    assert axis in AXES, f"{path.name}: unknown axis {axis!r}; expected one of {sorted(AXES)}"


@pytest.mark.parametrize("path", [p for p in PROFILES if _axis(p) == "constraint"],
                         ids=lambda p: p.name)
def test_a_constraint_profile_only_subtracts(path):
    enabled = [k for k, v in _keys(path) if v.lower() in ("true", "yes")]
    assert not enabled, (
        f"{path.name} declares itself a constraint but ENABLES {enabled}. A "
        "constraint says what the hardware cannot take; enabling something is a "
        "want, and wants belong in a use-case profile. Otherwise "
        "`use-case + constraint` depends on which was read first."
    )
