"""Anatomy gates for Wing design tokens (W2, 2026-05-17).

Pins the tokens.css contract so a future stylesheet refactor can't drop
the semantic --color-* / --space-* / --radius-* / --font-* / --shadow-*
scales the rest of the system depends on. Also locks the back-compat
aliases (--bg / --surface / --text / etc.) — pre-W2 per-page CSS still
references them; removing the aliases mid-migration would silently break
6 pages.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
ASSETS = REPO / "files/anatomy/wing/www/assets"
TOKENS = ASSETS / "tokens.css"
LAYOUT = REPO / "files/anatomy/wing/app/Templates/@layout.latte"
HOMEPAGE = REPO / "files/anatomy/wing/app/Templates/Homepage/default.latte"


def test_tokens_css_present():
    assert TOKENS.is_file()


def test_tokens_loaded_first_in_layout():
    """tokens.css must load BEFORE style.css so :root + utility classes
    are available everywhere."""
    src = LAYOUT.read_text()
    tokens_pos = src.find("tokens.css")
    style_pos = src.find("style.css")
    assert tokens_pos > 0
    assert style_pos > 0
    assert tokens_pos < style_pos, (
        "tokens.css must load before style.css in @layout.latte"
    )


def test_tokens_loaded_in_homepage():
    """Homepage uses {layout none} so it doesn't inherit the layout's
    `<link>` tags — it must load tokens explicitly."""
    src = HOMEPAGE.read_text()
    assert "tokens.css" in src


def test_tokens_declare_full_color_scale():
    """All semantic color slots required by tokens-aware page CSS."""
    css = TOKENS.read_text()
    for token in (
        "--color-bg", "--color-surface", "--color-surface2", "--color-border",
        "--color-text", "--color-text2", "--color-accent",
        "--color-success", "--color-danger", "--color-warning",
        "--color-severity-critical", "--color-severity-high",
        "--color-severity-medium", "--color-severity-low",
        "--color-severity-info",
    ):
        assert token in css, f"missing color token: {token}"


def test_tokens_declare_full_spacing_radius_font_shadow_scales():
    css = TOKENS.read_text()
    for token in (
        "--space-xs", "--space-sm", "--space-md", "--space-lg",
        "--space-xl", "--space-2xl",
        "--radius-sm", "--radius-md", "--radius-lg", "--radius-pill",
        "--font-sans", "--font-mono",
        "--shadow-sm", "--shadow-md",
    ):
        assert token in css, f"missing scale token: {token}"


def test_tokens_keep_legacy_aliases_for_pre_w2_css():
    """Pre-W2 per-page CSS (migrations.css, coexistence.css, timeline.css,
    upgrades.css, widgets.css) references --bg / --surface / --text / etc.
    The aliases in tokens.css map them to the new --color-* names. Removing
    these aliases mid-migration silently breaks 6 pages.
    """
    css = TOKENS.read_text()
    # Sample of the back-compat aliases that MUST stay defined.
    for alias in ("--bg:", "--surface:", "--text:", "--accent:", "--red:", "--green:", "--orange:"):
        assert alias in css, f"missing back-compat alias: {alias}"


def test_tokens_carry_utility_classes():
    css = TOKENS.read_text()
    for klass in (
        ".text-muted", ".text-mono", ".text-small",
        ".flex", ".items-center", ".gap-md",
        ".empty-state",
    ):
        assert klass in css, f"missing utility class: {klass}"
