#!/usr/bin/env python3
"""The manifest row is the only place a service's spellings meet.

A service is spelled four ways — `install_calibreweb`, manifest id
`calibre_web`, fragment `calibre-web.yml`, container `iiab-calibre-web-1` —
and every consumer that GUESSED a hop got a hop wrong: the compose prune's
separator-insensitive match cannot reach `calibre-web` from `calibreweb`, nor
`tileserver` from `offline_maps` by any rule at all. Ask the row instead.

Importable, not a CLI: `sys.path.insert(0, "<repo>/tools")`.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "state" / "manifest.yml"

#: In ansible precedence order, LOWEST first. A role default is a real
#: declaration and a reader that skips it answers "declared in no layer" about
#: a variable that is declared — `keap_repo_ref` lives only in role defaults.
CONFIG_LAYERS = ("roles/*/defaults/main.yml", "default.config.yml", "config.yml")


def layer_paths() -> list[Path]:
    """The layers that exist, LOWEST precedence first. One list, every reader."""
    return [p for p in (*sorted((REPO / "roles").glob("*/defaults/main.yml")),
                        REPO / "default.config.yml", REPO / "config.yml")
            if p.exists()]


def resolve_flag(flag: str) -> list[tuple[str, str]]:
    """Every layer that declares it, in precedence order. The LAST one wins."""
    pattern = re.compile(rf"^{re.escape(flag)}:\s*(\S+)", re.MULTILINE)
    seen: list[tuple[str, str]] = []
    for path in layer_paths():
        m = pattern.search(path.read_text(encoding="utf-8"))
        if m:
            seen.append((str(path.relative_to(REPO)), m.group(1).strip().strip('"\'')))
    return seen


def services() -> list[dict]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["services"]


def by_flag(flag: str) -> dict | None:
    """install_<x> -> the row, or None. The hop no consumer may guess."""
    return next((s for s in services() if s.get("install_flag") == flag), None)


def fragment_stem(row: dict) -> str | None:
    """<stacks_dir>/<stack>/overrides/<stem>.yml. None = owns no fragment."""
    if "fragment" in row:
        return row["fragment"]
    return row["id"] if row.get("stack") else None


def fragment_path(row: dict) -> str | None:
    stem = fragment_stem(row)
    return f"{row['stack']}/overrides/{stem}.yml" if stem else None


if __name__ == "__main__":  # self-check: the three hops no guess can make
    for flag, stem in (("install_calibreweb", "calibre-web"),
                       ("install_openwebui", "open-webui"),
                       ("install_offline_maps", "tileserver")):
        row = by_flag(flag)
        assert row and fragment_stem(row) == stem, (flag, row)
    assert fragment_stem(by_flag("install_qdrant")) is None
    assert fragment_stem(by_flag("install_gitea")) == "gitea"
    print("ok")
