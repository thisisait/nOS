"""Anatomy CI gate — CLAUDE.md anatomy-plugin count stays honest.

CLAUDE.md line 7 advertises the number of anatomy plugins ("N anatomy plugins
for cross-service wiring"). That count drifted silently as plugins were added
(it claimed 65 while 67 plugin.yml manifests existed on disk, after
authentik-tofu-drift-base + hermes-base landed). No gate caught it.

This pins the prose to ground truth: the count CLAUDE.md prints must equal the
number of plugins the loader actually discovers (one per
files/anatomy/plugins/<name>/plugin.yml).
"""

from __future__ import annotations

import pathlib
import re

# tests/conftest.py adds files/anatomy/ to sys.path.
from module_utils import load_plugins  # type: ignore  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
PLUGINS_ROOT = REPO / "files" / "anatomy" / "plugins"
CLAUDE_MD = REPO / "CLAUDE.md"

_COUNT_RE = re.compile(r"(\d+)\s+anatomy plugins for cross-service wiring")


def _discovered_count() -> int:
    return len(load_plugins.discover(PLUGINS_ROOT))


def _filesystem_count() -> int:
    return sum(
        1 for d in PLUGINS_ROOT.iterdir() if d.is_dir() and (d / "plugin.yml").is_file()
    )


def test_loader_matches_filesystem():
    """Every plugin dir carries a plugin.yml — loader sees them all."""
    assert _discovered_count() == _filesystem_count()


def test_claude_md_plugin_count_is_accurate():
    """CLAUDE.md line 7's plugin count == the real discovered count."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    m = _COUNT_RE.search(text)
    assert m, "CLAUDE.md must state '<N> anatomy plugins for cross-service wiring'"
    claimed = int(m.group(1))
    actual = _discovered_count()
    assert claimed == actual, (
        f"CLAUDE.md claims {claimed} anatomy plugins but {actual} plugin.yml "
        f"manifests exist under {PLUGINS_ROOT.relative_to(REPO)}/"
    )
