"""Anatomy gates for Wing UI hygiene (W3 cleanup, 2026-05-17).

Pins the post-cleanup state so a future template addition can't silently
regress to inline <script> blocks, Czech language strings, hardcoded
`auth.dev.local`, or other patterns the cleanup retired.

Authoritative scope: `files/anatomy/wing/app/Templates/**/*.latte`.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
TEMPLATES = REPO / "files/anatomy/wing/app/Templates"


def _all_latte_files() -> list[pathlib.Path]:
    return sorted(TEMPLATES.rglob("*.latte"))


def test_no_inline_script_blocks_in_templates():
    """Every behaviour must live in www/assets/<page>.js, loaded via
    `<script src=...>`. Inline `<script>...</script>` blocks bypass the
    CSP-friendly + cacheable + lintable surface. Allowed: `<script src=...>`
    tags (those have a `src=` attribute on the same line as the `<script` token).
    """
    offenders: list[tuple[str, int]] = []
    # Two simple patterns instead of one negative-lookahead-over-[^>]* (which
    # py/bad-tag-filter flags as a bypassable HTML-tag filter + can't match
    # upper-case <SCRIPT>): flag a <script> opener that has NO src= attribute.
    # IGNORECASE closes the upper-case bypass the scanner warned about.
    open_tag = re.compile(r"<script[\s>]", re.IGNORECASE)
    has_src = re.compile(r"<script[^>]*\bsrc=", re.IGNORECASE)
    for path in _all_latte_files():
        for idx, line in enumerate(path.read_text().splitlines(), 1):
            if open_tag.search(line) and not has_src.search(line):
                offenders.append((str(path.relative_to(REPO)), idx))
    assert not offenders, (
        "inline <script> blocks remain in templates — extract them to "
        f"www/assets/<page>.js and load via <script src=...>: {offenders}"
    )


def test_no_inline_style_blocks_in_templates():
    """Same rule for inline `<style>...</style>` — must move to CSS modules
    in www/assets/. Note: inline `style="..."` attributes on individual
    elements are STILL ALLOWED (W3 didn't scope to those); W2 will
    consolidate them via utility classes.
    """
    offenders: list[tuple[str, int]] = []
    pattern = re.compile(r"<style(?![^>]*\bsrc=)[^>]*>")
    for path in _all_latte_files():
        for idx, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                offenders.append((str(path.relative_to(REPO)), idx))
    assert not offenders, (
        f"inline <style> blocks remain in templates: {offenders}"
    )


def test_no_hardcoded_authentik_dev_local_in_templates():
    """The Authentik domain must come from the template var
    `$authentikDomain` (populated by BasePresenter from AUTHENTIK_DOMAIN
    env). Hardcoded `auth.dev.local` breaks every public-TLD install.
    """
    offenders: list[tuple[str, int, str]] = []
    for path in _all_latte_files():
        for idx, line in enumerate(path.read_text().splitlines(), 1):
            if "auth.dev.local" in line:
                offenders.append((str(path.relative_to(REPO)), idx, line.strip()))
    assert not offenders, (
        f"hardcoded auth.dev.local in templates — use $authentikDomain: {offenders}"
    )


def test_html_lang_is_english():
    """Project doctrine: English everywhere (see CLAUDE.md 'Known Tech
    Debt' — Czech-language legacy retired with the nOS rebrand). The
    HTML lang attribute is the canonical declaration of page language;
    it must match the body content.
    """
    offenders: list[tuple[str, int]] = []
    for path in _all_latte_files():
        for idx, line in enumerate(path.read_text().splitlines(), 1):
            if 'lang="cs"' in line or "lang='cs'" in line:
                offenders.append((str(path.relative_to(REPO)), idx))
    assert not offenders, (
        f"lang=\"cs\" remains in templates: {offenders}"
    )


def test_base_presenter_exposes_authentik_domain():
    """BasePresenter must populate $authentikDomain so the layout's logout
    link renders the right value across dev (dev.local) + prod TLDs.
    """
    src = (REPO / "files/anatomy/wing/app/Presenters/BasePresenter.php").read_text()
    assert "authentikDomain" in src
    assert "AUTHENTIK_DOMAIN" in src


def test_layout_uses_authentik_domain_var():
    """The end-session link in @layout.latte must use $authentikDomain,
    not a hardcoded host."""
    src = (TEMPLATES / "@layout.latte").read_text()
    # Positive: var is referenced in the logout link.
    assert "$authentikDomain" in src
    # Negative: no hardcoded auth.dev.local survived in the layout.
    assert "auth.dev.local" not in src


def test_layout_subtitle_reflects_current_scope():
    """The pre-W3 subtitle was 'FOSS vulnerability monitoring, autonomous
    pentesting, upstream patch development' — accurate for the original
    A0 framing but stale once A8-A14 added inbox, agents, audit, GDPR,
    coexistence, approvals. Pin the new framing so a future commit can't
    revert it silently.
    """
    src = (TEMPLATES / "@layout.latte").read_text()
    assert "FOSS vulnerability monitoring, autonomous pentesting" not in src
