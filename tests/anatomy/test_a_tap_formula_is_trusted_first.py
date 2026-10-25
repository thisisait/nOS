"""A formula from a non-official tap is trusted before it is installed.

MEASURED 2026-10-25: Homebrew 7.0.10 refused `oven-sh/bun/bun` ("Refusing to load formula …
from untrusted tap") and the converge died at tasks/bun.yml, after it had persisted a rotated
Wing bearer and before Wing was provisioned with it. Read from the YAML: every
community.general.homebrew install of a `<user>/<tap>/<formula>` name is preceded, in the same
file, by an include of tasks/brew-trust.yml naming it; tap formulae the homebrew role installs by
short name are listed in homebrew_trusted_formulae.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
INSTALL = {"community.general.homebrew", "homebrew"}
INCLUDE = {"ansible.builtin.include_tasks", "include_tasks", "ansible.builtin.import_tasks", "import_tasks"}


def _files():
    yield from sorted((REPO / "tasks").rglob("*.yml"))
    yield from sorted(REPO.glob("roles/*/tasks/*.yml"))


def _names(v) -> list[str]:
    return [v] if isinstance(v, str) else list(v or [])


def test_every_tap_formula_install_is_trusted_first():
    missing = []
    for f in _files():
        tasks = yaml.safe_load(f.read_text(encoding="utf-8")) or []
        if not isinstance(tasks, list):
            continue
        trusted: set[str] = set()
        for t in tasks:
            if not isinstance(t, dict):
                continue
            inc = next((t[k] for k in INCLUDE & t.keys()), None)
            if isinstance(inc, str) and inc.split()[0].endswith("brew-trust.yml"):
                trusted.update(_names((t.get("vars") or {}).get("brew_trust_formulae")))
            for mod in INSTALL & t.keys():
                for name in _names((t[mod] or {}).get("name")):
                    if name.count("/") == 2 and name not in trusted:
                        missing.append(f"{f.relative_to(REPO)}: {t.get('name')} installs {name}")
    assert not missing, "tap formulae installed with no brew-trust before them:\n  " + "\n  ".join(missing)


def test_the_homebrew_role_trusts_its_tap_formulae():
    cfg = yaml.safe_load((REPO / "config.d/20-host-software.yml").read_text(encoding="utf-8"))
    taps = {t if isinstance(t, str) else t["name"] for t in cfg["homebrew_taps"]}
    trusted = set(cfg.get("homebrew_trusted_formulae") or [])
    assert all(any(f.startswith(tap + "/") for tap in taps) for f in trusted), "a trusted formula from a tap not tapped"
    assert "infisical/get-cli/infisical" in trusted, "the infisical CLI comes from the infisical/get-cli tap"
    role = (REPO / "roles/pazny.mac.homebrew/tasks/main.yml").read_text(encoding="utf-8")
    assert role.index("homebrew_taps") < role.index("brew-trust.yml") < role.index("homebrew_installed_packages"), \
        "the role must trust after tapping and before installing"
