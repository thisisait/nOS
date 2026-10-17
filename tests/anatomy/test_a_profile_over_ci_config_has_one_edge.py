"""A profile layered over CI's tests/config.yml leaves exactly one edge proxy.

The All-on lane (ci.yml: cp tests/config.yml, then -e @profiles/all-on.yml) died in its preflight on
the v0.17-beta release PR: tests/config.yml sets install_nginx: true, the profile install_traefik:
true, and '[Preflight] Refuse if BOTH install_nginx and install_traefik are true' stopped it after
one minute - a lane that tests nothing. A profile that picks an edge names both flags.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def test_every_profile_over_the_ci_config_has_one_edge():
    base = yaml.safe_load((REPO / "tests/config.yml").read_text(encoding="utf-8")) or {}
    bad = []
    for p in sorted((REPO / "profiles").glob("*.yml")):
        prof = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not ({"install_nginx", "install_traefik"} & set(prof)):
            continue  # a profile that does not touch the edge keeps the base's choice
        cfg = {**base, **prof}
        if cfg.get("install_nginx") is True and cfg.get("install_traefik") is True:
            bad.append(p.name)
    assert not bad, f"over tests/config.yml these profiles turn on both nginx and traefik: {bad}"
