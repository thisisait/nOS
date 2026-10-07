"""Anatomy CI gate — CLAUDE.md carries no plugin count.

CLAUDE.md's own brief says: "Do not paste history, incident notes or counts
that move into this file." The plugin count did exactly that: it claimed 65
while 67 manifests existed, then had to be bumped by hand on every new plugin.
Until 2026-10-07 this gate pinned the printed count to the loader's; now it
refuses the count altogether — the loader is the reader for that number
(`load_plugins.discover`), the prose only says plugins exist.

The loader-vs-filesystem half stays: every plugin dir carries a plugin.yml.
"""

from __future__ import annotations

import pathlib
import re

# tests/conftest.py adds files/anatomy/ to sys.path.
from module_utils import load_plugins  # type: ignore  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO / "files" / "anatomy" / "plugins"
CLAUDE_MD = REPO / "CLAUDE.md"

_COUNT_RE = re.compile(r"~?\d+\s+(anatomy plugins|FOSS Docker services)")


def _discovered_count() -> int:
    return len(load_plugins.discover(PLUGINS_ROOT))


def _filesystem_count() -> int:
    return sum(
        1 for d in PLUGINS_ROOT.iterdir() if d.is_dir() and (d / "plugin.yml").is_file()
    )


def test_loader_matches_filesystem():
    """Every plugin dir carries a plugin.yml — loader sees them all."""
    assert _discovered_count() == _filesystem_count()


def test_claude_md_carries_no_moving_count():
    """CLAUDE.md names plugins and services without a number in front."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    hits = [m.group(0) for m in _COUNT_RE.finditer(text)]
    assert not hits, (
        f"CLAUDE.md carries a count that moves: {hits}. The brief forbids counts "
        f"here; the loader ({_discovered_count()} plugins today) is the reader."
    )
