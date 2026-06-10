"""W6.5 gates (2026-06-10) — lucide tree-shake stays complete.

The Hub loads lucide-slim.js (~8 KB, ~36 glyphs) instead of the full 402 KB
bundle. The risk of a curated subset is silent drift: a NEW plugin manifest
icon that isn't in the subset renders an empty span with no error anywhere.
This gate closes the loop: every `hub_card.icon` declared by any plugin must
resolve — via the hub-icons.js ALIAS map where applicable — to a glyph
present in lucide-slim.js.
"""
from __future__ import annotations

import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]

SLIM = REPO / "files/anatomy/wing/www/assets/lucide-slim.js"
HUB_ICONS = REPO / "files/anatomy/wing/www/assets/hub-icons.js"
HUB_TPL = REPO / "files/anatomy/wing/app/Templates/Hub/default.latte"
PLUGINS = REPO / "files/anatomy/plugins"


def _slim_icon_names() -> set[str]:
    src = SLIM.read_text()
    m = re.search(r"var ICONS = (\{.*?\});\n", src, re.S)
    assert m, "lucide-slim.js lost its ICONS map"
    return set(json.loads(m.group(1)).keys())


def _alias_map() -> dict[str, str]:
    src = HUB_ICONS.read_text()
    body = src[src.index("const ALIAS = {"):]
    body = body[: body.index("};")]
    return dict(re.findall(r"'([a-z0-9-]+)':\s*'([a-z0-9-]+)'", body))


def _declared_icons() -> set[str]:
    out = set()
    for f in sorted(PLUGINS.glob("*/plugin.yml")):
        for m in re.finditer(r"^\s*icon:\s*[\"']?([a-z0-9-]+)[\"']?\s*$",
                             f.read_text(), re.M):
            out.add(m.group(1))
    return out


def test_hub_loads_slim_not_full_bundle():
    src = HUB_TPL.read_text()
    assert "lucide-slim.js" in src
    assert "lucide.min.js" not in src, (
        "the Hub regressed to the 402 KB full bundle"
    )


def test_slim_is_actually_slim():
    assert SLIM.stat().st_size < 50_000, (
        f"lucide-slim.js is {SLIM.stat().st_size} bytes — that's not slim; "
        "regenerate the subset instead of pasting the full bundle"
    )


def test_every_declared_icon_resolves_in_slim():
    slim = _slim_icon_names()
    alias = _alias_map()
    missing = sorted(
        name for name in _declared_icons()
        if alias.get(name, name) not in slim
    )
    assert not missing, (
        f"plugin manifests declare icons with no glyph in lucide-slim.js: "
        f"{missing}. Add an ALIAS in hub-icons.js or regenerate the subset "
        "(instructions in the lucide-slim.js header)."
    )


def test_alias_targets_exist_in_slim():
    slim = _slim_icon_names()
    stale = sorted(t for t in _alias_map().values() if t not in slim)
    assert not stale, f"ALIAS targets missing from the slim subset: {stale}"
