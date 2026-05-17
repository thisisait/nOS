"""Anatomy gates for Wing IA (W1 information architecture, 2026-05-17).

W1 reshapes the top-nav from 12 flat tabs (mixing operate / insights /
security / platform with no visual hierarchy) into 5 visual groups
separated by CSS `.tab-sep::before` dividers. Pins:

  * the new tab set (drops fragment-targeted Timeline/Components,
    adds Migrations/Upgrades/Coexistence/GDPR which had presenters but
    no nav entry),
  * the group separator CSS,
  * the right-aligned Help+Admin section.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
LAYOUT = REPO / "files/anatomy/wing/app/Templates/@layout.latte"
STYLE = REPO / "files/anatomy/wing/www/assets/style.css"


def test_top_nav_carries_every_grouped_tab():
    """The 13 active nav entries (12 always-visible + Admin gated) must
    all be present in the layout's `.tabs` block."""
    src = LAYOUT.read_text()
    # Operate group
    assert 'href="/hub"' in src
    assert 'href="/inbox"' in src
    assert 'href="/approvals"' in src
    # Insights group
    assert 'href="/dashboard"' in src
    assert 'href="/timeline"' in src
    assert 'href="/audit"' in src
    assert 'href="/agents"' in src
    # Security group
    assert 'href="/pentest"' in src
    assert 'href="/remediation"' in src
    assert 'href="/gdpr"' in src
    # Platform group
    assert 'href="/migrations"' in src
    assert 'href="/upgrades"' in src
    assert 'href="/coexistence"' in src
    # Right-aligned
    assert 'href="/help"' in src
    assert 'href="/admin"' in src


def test_fragment_only_tabs_retired():
    """Pre-W1 the layout carried `Timeline` + `Components` as top-level
    tabs targeting `/dashboard#timeline` / `/dashboard#components`
    fragment anchors. Both were confusing (clicked tab → URL fragment
    that the Dashboard presenter handled with JS scrolling). Timeline
    is now its own top-level (`/timeline` — there's already a
    TimelinePresenter); Components is just a Dashboard section, no
    longer a top-level tab.
    """
    src = LAYOUT.read_text()
    assert "/dashboard#timeline" not in src
    assert "/dashboard#components" not in src
    assert 'data-tab="components"' not in src


def test_top_nav_has_5_group_separators():
    """W1 visual contract: 5 groups, 4 dividers between them. The
    `.tab-sep` modifier draws a vertical line via ::before, so we count
    its occurrences in the layout. (Tabs marked .tab-sep are the FIRST
    of each non-Operate group.)
    """
    src = LAYOUT.read_text()
    # 4 separators between 5 groups: Insights / Security / Platform / Help.
    # Count usage in class attributes, not in comments — the layout
    # carries a `.tab-sep` reference in a {* ... *} comment block.
    import re
    matches = re.findall(r'class="[^"]*\btab-sep\b', src)
    assert len(matches) == 4, (
        f"expected 4 .tab-sep class-usages (Insights/Security/Platform/Help "
        f"group starts), got {len(matches)}: {matches}"
    )


def test_admin_tab_uses_class_not_inline_style():
    """Pre-W1 the Admin tab was visually distinct via an inline style
    attribute (`margin-left:auto; color:#d11; font-weight:600`). W1
    promotes those rules to .tab-right + .tab-admin classes so they're
    style-system citizens, not magic inline strings."""
    src = LAYOUT.read_text()
    # The Admin block must use the class, not the inline-style hack.
    assert "tab-admin" in src
    # The pre-W1 inline-style remnant must be gone.
    assert "color:#d11" not in src
    assert "margin-left:auto" not in src or "tab-right" in src


def test_style_css_carries_separator_rules():
    css = STYLE.read_text()
    assert ".tab-sep::before" in css
    assert ".tab-right" in css
    assert ".tab-admin" in css
    # W4 unread-count slot pre-declared (wiring lands in W4).
    assert ".tab-count" in css
