"""The KEAP pin must never land on a tag with a cancelled schema.

`v1.19.0` is a real, immutable, published KEAP tag that shipped the numeric
user-root scheme (`90`–`99`) — a design both sides then cancelled in favour of
slug ids. `USER_ROOT_MIN` is set in that tag and zero in every tag after it.

Pinned there, `registerExtNode` accepts two-digit roots only, so the slug root
`nos` is rejected with a bare `null`. The root is never created, every
self-model card anchored under it resolves to nothing, and — the part that makes
this worth a gate — **nothing is logged**. A converge goes green and the whole
nOS constellation is simply absent from the map.

The KEAP side deliberately did NOT retract the tag: rewriting a published tag to
mean something else is worse than a documented trap. So the trap is made loud on
this side instead. This is `docs/doctrine/gates.md` applied to itself — a known
hazard that fails silently is exactly the thing that earns a mechanical check
rather than a comment.

Offline: pure text read of the two pin sites.
"""

from __future__ import annotations

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
ROLE_DEFAULTS = ROOT / "roles/pazny.keap/defaults/main.yml"

# Tags whose schema was cancelled after release. Append (never remove) if
# another published tag turns out to carry a retracted design.
CANCELLED = {
    "1.19.0": (
        "ships the cancelled numeric user-root scheme (USER_ROOT_MIN set); "
        "the slug root `nos` is rejected with a bare null, so the self-model "
        "constellation vanishes with no log line. Use v1.20.0 or newer."
    ),
}


def _norm(tag: str) -> str:
    return str(tag).strip().lstrip("vV")


def _role_pin() -> str:
    return _norm(yaml.safe_load(ROLE_DEFAULTS.read_text())["keap_repo_ref"])


def _config_pins() -> dict:
    cfg = yaml.safe_load((ROOT / "default.config.yml").read_text())
    return {k: _norm(v) for k, v in cfg.items() if k in ("keap_version", "keap_repo_ref")}


def test_role_pin_is_not_a_cancelled_tag():
    pin = _role_pin()
    assert pin not in CANCELLED, (
        f"keap_repo_ref is pinned to v{pin} — {CANCELLED.get(pin, '')}"
    )


def test_config_pins_are_not_cancelled_tags():
    for var, pin in _config_pins().items():
        assert pin not in CANCELLED, (
            f"{var} is pinned to v{pin} — {CANCELLED.get(pin, '')}"
        )


def test_the_trap_is_documented_where_the_pin_is_edited():
    """A gate catches it; a comment stops it being written in the first place.

    The hazard fires at pin-bump time, so the warning has to live at the pin
    site — not only in a spec the person bumping a version will not open.
    """
    src = ROLE_DEFAULTS.read_text()
    assert "v1.19.0" in src and "NEVER PIN" in src.upper(), (
        "the v1.19.0 trap must be documented next to keap_repo_ref itself"
    )


def test_pins_agree_with_each_other():
    """A split pin builds one image and runs another — the version-shadow class."""
    cfg = _config_pins()
    if "keap_version" in cfg:
        assert cfg["keap_version"] == _role_pin(), (
            f"keap_version ({cfg['keap_version']}) != keap_repo_ref ({_role_pin()}) "
            "— the image tag and the built source would disagree"
        )
