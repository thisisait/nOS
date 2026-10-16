"""The face's colours and glass are the design system's glass-face theme, generated, not typed.

Why a gate: operator ruling 2026-10-16 — the design system (thisisait/design, vendored in
files/anatomy/design/) wins over the face's own app.css values. The face keeps its variable
names (--bg, --glass, --ok ...) as aliases, rendered by tools/design-sync.py into
src/lib/design/tokens.css. Two copies of one colour drift the day app.css sets it by hand.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
DESIGN = REPO / "files/anatomy/design"
FACE = REPO / "files/anatomy/face/src"
TOKENS_CSS = FACE / "lib/design/tokens.css"
APP_CSS = FACE / "app.css"
THEME = "glass-face"
# `--name: value; /* token */` — every generated property names its design source.
DECL = re.compile(r"^\s*(--[\w-]+):\s*([^;]+);\s*/\*\s*([\w-]+)\s*\*/", re.M)
COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")


def _sync():
    spec = importlib.util.spec_from_file_location("design_sync", REPO / "tools/design-sync.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["design_sync"] = mod
    spec.loader.exec_module(mod)
    return mod


def _generated() -> dict[str, tuple[str, str]]:
    return {n: (v.strip(), t) for n, v, t in DECL.findall(TOKENS_CSS.read_text())}


def _root(css: str) -> str:
    m = re.search(r":root\s*\{(.*?)\}", css, re.S)
    return m[1] if m else ""


def test_tokens_css_is_what_design_sync_writes():
    sha = re.search(r"commit `([0-9a-f]+)`", (DESIGN / "README.md").read_text())[1]
    expected = _sync().render_face_css(json.loads((DESIGN / "tokens.json").read_text()),
                                       (DESIGN / "components.css").read_text(), sha)
    assert TOKENS_CSS.read_text() == expected, "face tokens.css is stale: run tools/design-sync.py"


def test_every_face_colour_equals_its_glass_face_token():
    colours = {c["name"]: c["value"][THEME] for c in json.loads((DESIGN / "tokens.json").read_text())["color"]["tokens"]}
    gen = _generated()
    assert {"--bg", "--fg", "--glass", "--accent", "--ok", "--warn", "--bad"} <= set(gen), sorted(gen)
    wrong = {n: (v, t, colours.get(t)) for n, (v, t) in gen.items()
             if n != "--glass-filter" and colours.get(t) != v}
    assert not wrong, f"face value != design {THEME} token: {wrong}"


def test_the_glass_effect_is_the_design_css_value():
    """tokens.json has no effect group; the value is the vendored design CSS's glass rule."""
    src = re.search(r"\bbackdrop-filter:\s*([^;]+);", (DESIGN / "components.css").read_text())
    assert src, "vendored components.css carries no backdrop-filter"
    assert _generated().get("--glass-filter", ("",))[0] == src[1].strip()


def test_app_css_imports_the_tokens_and_types_no_colour_they_own():
    app = APP_CSS.read_text()
    assert re.match(r"\s*@import\s+['\"]\./lib/design/tokens\.css['\"];", app), "app.css must import tokens.css first"
    owned = sorted(n for n in _generated() if re.search(rf"^\s*{re.escape(n)}\s*:", app, re.M))
    assert not owned, f"app.css re-sets generated variables: {owned}"
    typed = COLOUR.findall(_root(app))
    assert not typed, f"app.css :root hand-types colours {typed}: map them to a design token or derive them"
    assert not re.search(r"backdrop-filter:\s*blur\(", app), "the glass effect is var(--glass-filter), not typed"
