"""Anatomy gates for Wing operator-UX upgrades (W4, 2026-05-17).

Pins the live-badge + keyboard-nav contracts so a future refactor can't
silently drop them. Pre-W4, the .tab-key chips ('Hub 1', 'Inbox 2', ...)
suggested keyboard navigation but no JS was wired — the chips were
purely decorative. Pre-W4, the inbox-unread count lived in
NotificationRepository::countUnread() but never reached the top nav,
so operators had to click /inbox to find out.
"""

from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
ASSETS = REPO / "files/anatomy/wing/www/assets"
LAYOUT = REPO / "files/anatomy/wing/app/Templates/@layout.latte"
BASE_PRESENTER = REPO / "files/anatomy/wing/app/Presenters/BasePresenter.php"
QUESTION_REPO = REPO / "files/anatomy/wing/app/Model/AgentQuestionRepository.php"
KEYBOARD_JS = ASSETS / "keyboard-nav.js"


# ── Live unread/pending badges ─────────────────────────────────────────


def test_base_presenter_injects_count_repos():
    """BasePresenter @inject's NotificationRepository + AgentQuestionRepository
    so every subclass gets badge counts for free (no constructor edits).
    (A11 retired 2026-08-08: the approvals badge — EventRepository — became
    the open-questions badge.)"""
    src = BASE_PRESENTER.read_text()
    assert "@inject" in src
    assert "NotificationRepository" in src
    assert "AgentQuestionRepository" in src


def test_base_presenter_populates_badge_counts():
    """beforeRender computes both counts and pins them onto the template
    namespace. Try/catch wrap protects against a transient DB blip from
    blowing up the entire page render."""
    src = BASE_PRESENTER.read_text()
    assert "unreadInboxCount" in src
    assert "openQuestionsCount" in src
    assert "countUnread()" in src
    assert "countOpen()" in src
    # Defensive try/catch — a missing repo at request time shouldn't 500.
    assert "Throwable" in src


def test_question_repository_exposes_countOpen():
    """The badge needs a count-only helper (W4 pattern) that mirrors
    listOpen()'s deadline exclusion, so the number on the tab can never
    disagree with the rows on the page."""
    src = QUESTION_REPO.read_text()
    assert "function countOpen" in src
    body = src[src.find("function countOpen"):]
    body = body[: body.find("\n\t}")]
    assert "expires_at IS NULL OR expires_at >" in body, (
        "countOpen() no longer excludes past-deadline questions — the badge "
        "would count rows the page refuses to show."
    )


def test_layout_renders_badges_conditionally():
    """The .tab-count slot must appear only when count > 0 (Latte
    {if} guard) so a quiet inbox doesn't show a stale '0' bubble."""
    src = LAYOUT.read_text()
    assert "$unreadInboxCount" in src
    assert "$openQuestionsCount" in src
    assert 'class="tab-count"' in src
    # Both badges are inside {if ... > 0} guards.
    assert "$unreadInboxCount ?? 0) > 0" in src
    assert "$openQuestionsCount ?? 0) > 0" in src


# ── Keyboard nav ───────────────────────────────────────────────────────


def test_keyboard_nav_script_present():
    assert KEYBOARD_JS.is_file()
    src = KEYBOARD_JS.read_text()
    # Listens for keydown.
    assert "keydown" in src
    # Inspects .tab-key chip text to find the matching tab.
    assert ".tab-key" in src or "tab-key" in src
    # Skips while typing — search inputs need their digit keys.
    assert "isTyping" in src or "isContentEditable" in src


def test_layout_loads_keyboard_nav():
    """The script is loaded from @layout.latte so every authenticated
    page has the digit-key shortcut wired."""
    src = LAYOUT.read_text()
    assert "keyboard-nav.js" in src


# ── End-to-end shape gates ─────────────────────────────────────────────


def test_tab_count_css_rule_consumed_by_layout():
    """style.css declared `.tab-count` in W1; W4 puts it to use in the
    layout. Pin both ends so they don't drift apart."""
    css = (ASSETS / "style.css").read_text()
    layout = LAYOUT.read_text()
    assert ".tab-count" in css
    assert "tab-count" in layout
