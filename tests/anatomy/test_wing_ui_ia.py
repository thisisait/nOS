"""Anatomy gates for Wing IA (W1 information architecture, 2026-05-17;
W5 burger overlay, 2026-05-26).

W1 reshaped the top-nav from 12 flat tabs into 5 visual groups. W5
(operator request) then moved the nav off the horizontal bar entirely:
a burger button in the header toggles a fullscreen overlay where the 5
groups are `.nav-overlay-group` sections with `<h2>` labels. The
`.tab-sep::before` separators are retired; the links keep `.tab` +
`.tab-key` so keyboard-nav.js and the unread/pending counts survive.
Pins:

  * the full nav entry set (every group's links present),
  * the 5 grouped overlay sections,
  * the burger + overlay CSS,
  * the Admin entry as a class (not an inline-style hack).
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
LAYOUT = REPO / "files/anatomy/wing/app/Templates/@layout.latte"
STYLE = REPO / "files/anatomy/wing/www/assets/style.css"


def test_top_nav_carries_every_grouped_tab():
    """The active nav entries (always-visible + Admin gated) must all be
    present in the layout's `.tabs` block. (The Approvals tab left the roster
    on 2026-08-08 with A11's retirement — approvals are answered on /inbox,
    and a nav entry pointing at a redirect would be a button that lies.)"""
    src = LAYOUT.read_text()
    # Operate group
    assert 'href="/hub"' in src
    assert 'href="/inbox"' in src
    assert 'href="/approvals"' not in src, (
        "the Approvals tab is back in the layout — /approvals has been a "
        "redirect to /inbox since A11's retirement (2026-08-08); either the "
        "surface was resurrected (see test_approval_queue_event_backed.py) "
        "or this is a stale nav entry."
    )
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


def test_top_nav_has_5_group_sections():
    """W5 visual contract: 5 grouped sections inside the burger overlay,
    each introduced by an `<h2>` label (Operate / Insights / Security /
    Platform / More). Pins the grouping that replaced the W1 `.tab-sep`
    dividers.
    """
    src = LAYOUT.read_text()
    import re
    groups = re.findall(r'class="nav-overlay-group"', src)
    assert len(groups) == 5, (
        f"expected 5 .nav-overlay-group sections, got {len(groups)}"
    )
    for label in ("Operate", "Insights", "Security", "Platform", "More"):
        assert f"<h2>{label}</h2>" in src, f"missing nav group label {label}"
    # The retired horizontal-separator modifier must be gone.
    assert not re.findall(r'class="[^"]*\btab-sep\b', src), (
        ".tab-sep separators are retired in W5 — the overlay uses <h2> group labels"
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


def test_style_css_carries_nav_overlay_rules():
    """W5: the burger + fullscreen-overlay CSS must be present, and the
    unread/pending count + admin-emphasis classes are retained (the
    overlay links reuse them)."""
    css = STYLE.read_text()
    assert ".nav-burger" in css
    assert ".nav-overlay" in css
    assert ".nav-overlay-group" in css
    assert ".tab-admin" in css
    assert ".tab-count" in css
    # Body-scroll lock while the overlay is open.
    assert "body.nav-open" in css


def test_dashboard_no_dead_in_page_tabs():
    """Dashboard rewrite (2026-05-17): the pre-rewrite template carried
    3 in-page tab-content blocks (`tab-overview` / `tab-timeline` /
    `tab-components`) toggled by JS driven by the now-retired
    /dashboard#... fragment-anchor top-nav tabs. With the top-nav
    drivers gone (W1), all 3 sections rendered simultaneously and the
    'Components moved to Hub' dead surface stayed visible. The flat
    rewrite drops the `tab-content` soup. Pin so a refactor can't
    re-introduce the dead structure."""
    dashboard = REPO / "files/anatomy/wing/app/Templates/Dashboard/default.latte"
    src = dashboard.read_text()
    assert 'id="tab-overview"' not in src
    assert 'id="tab-timeline"' not in src
    assert 'id="tab-components"' not in src
    assert "Components moved to Hub" not in src
    # New coherent sections present.
    assert "Operator attention" in src
    assert "Next scan batch" in src
    assert "Pentest target coverage" in src
    assert "Recent advisories" in src
    assert "empty-state" in src   # uses the W2 utility component
