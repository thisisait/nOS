"""The nos-cc theme is the design system's glass-face theme, generated, not typed.

Why a gate: tools/cc/theme.py is a rendering of files/anatomy/design/tokens.json.
Two copies of one fact drift the day one is edited by hand; this test fails on
that day. Regenerate with `python3 tools/design-sync.py` (or sync from a design
checkout with `python3 tools/design-sync.py ../design`).
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
TOKENS = REPO / "files/anatomy/design/tokens.json"
README = REPO / "files/anatomy/design/README.md"
THEME_PY = REPO / "tools/cc/theme.py"


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_vendored_tokens_carry_the_face_theme():
    tokens = json.loads(TOKENS.read_text())
    ids = [t["id"] for t in tokens["color"]["themes"]]
    assert "glass-face" in ids, ids
    for c in tokens["color"]["tokens"]:
        assert "glass-face" in c["value"], f"{c['name']} has no glass-face value"


def test_readme_pins_the_design_commit():
    assert re.search(r"commit `[0-9a-f]{7,}`", README.read_text())


def test_theme_py_is_generated_from_the_vendored_tokens():
    sync = _load(REPO / "tools/design-sync.py", "design_sync")
    sha = re.search(r"commit `([0-9a-f]+)`", README.read_text())[1]
    expected = sync.render_theme(json.loads(TOKENS.read_text()), sha)
    assert THEME_PY.read_text() == expected, "tools/cc/theme.py is stale: run tools/design-sync.py"


def test_theme_values_are_opaque_hex():
    theme = _load(THEME_PY, "cc_theme")
    for k, v in theme.VALUES.items():
        assert re.fullmatch(r"#[0-9a-f]{6}", v), f"{k}={v!r} — a terminal cannot blend rgba"
    assert theme.THEME_NAME == "ait-glass-face"
