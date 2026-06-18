"""Anatomy CI gate for the planned-recipe visibility fix (F2).

The operator's live visual review of /upgrades found that a queued upgrade (e.g.
postgresql 16-to-17) rendered ONLY a static "planned → 17" badge with no way to
see WHAT the queued upgrade would do (its recipe / steps). This gate pins the
fix:

  1. UpgradeRepository::matrix() surfaces the queued recipe id as
     ``planned_recipe_id`` on the matrix row (so the badge can deep-anchor the
     specific recipe card).
  2. default.latte's "planned" badge is a LINK to /upgrades/<service> (the detail
     page that already renders recipe cards), deep-anchored to
     ``#recipe-<id>`` when the planned recipe id is known, plus an inline
     "view recipe" affordance. The matrix never duplicates recipe rendering.
  3. service.latte's recipe card carries an ``id="recipe-<id>"`` HTML anchor so
     the deep-link lands on the card that renders steps/changelog — the single
     recipe-rendering surface.

Regex-only (no PHP/Latte execution) — consistent with test_plan_choice_ui.py and
test_security_presenter_gates.py, so the gate runs on the pytest+pyyaml stack.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
REPOSITORY = WING / "app" / "Model" / "UpgradeRepository.php"
DEFAULT_LATTE = WING / "app" / "Templates" / "Upgrades" / "default.latte"
SERVICE_LATTE = WING / "app" / "Templates" / "Upgrades" / "service.latte"


# ── Repository: surface the planned recipe id ─────────────────────────


def test_matrix_surfaces_planned_recipe_id():
    """The matrix row must expose the queued recipe id so the badge can
    deep-link the specific recipe card (not just the service page)."""
    src = REPOSITORY.read_text()
    assert re.search(
        r"['\"]planned_recipe_id['\"]\s*=>\s*\$planned\[\$service\]\['recipe_id'\]",
        src,
    ), "UpgradeRepository::matrix() must set planned_recipe_id from the queued upgrades_planned row"


# ── default.latte: planned badge links to the recipe ──────────────────


def test_planned_badge_is_a_link_not_a_dead_span():
    """The planned badge must be an <a> deep-linking the service detail page —
    a static <span> gives the operator no way to see the recipe (the F2 bug)."""
    src = DEFAULT_LATTE.read_text()
    block = _planned_block(src)
    assert "<a " in block, (
        "the 'planned' badge must be a link (<a>), not a dead <span> — F2: surface the recipe"
    )
    assert 'href="/upgrades/{$row[\'service\']}' in block, (
        "the planned badge must link to /upgrades/<service> (the recipe-rendering detail page)"
    )


def test_planned_badge_deep_anchors_the_recipe_card():
    """When the planned recipe id is known the link must anchor the specific
    recipe card (#recipe-<id>), so the operator lands on WHAT the upgrade does."""
    src = DEFAULT_LATTE.read_text()
    block = _planned_block(src)
    assert "planned_recipe_id" in block, (
        "default.latte must read planned_recipe_id to build the deep-anchor"
    )
    assert "#recipe-" in block, (
        "the planned link must deep-anchor #recipe-<id> when the recipe id is known"
    )


def test_planned_badge_keeps_the_target_arrow():
    """Behaviour-preserving: the badge still shows 'planned → <target>'."""
    block = _planned_block(DEFAULT_LATTE.read_text())
    assert "planned" in block and "planned_target" in block, (
        "the planned badge must keep rendering 'planned → <planned_target>'"
    )


def test_view_recipe_affordance_present():
    """An explicit 'view recipe' affordance makes the intent legible (the badge
    alone reads as status, not a link)."""
    block = _planned_block(DEFAULT_LATTE.read_text())
    assert "view recipe" in block, (
        "default.latte must surface a 'view recipe' affordance beside the planned badge"
    )


def test_matrix_does_not_duplicate_recipe_rendering():
    """The matrix must LINK to the recipe surface, never re-render recipe steps
    inline (the detail page owns recipe rendering — keep it the single surface)."""
    block = _planned_block(DEFAULT_LATTE.read_text())
    # Recipe step/changelog rendering lives only on service.latte. The matrix's
    # planned block must not pull a recipe's steps/changelog/notes.
    for leak in ("upg-recipe-body", "changelog_url", "$r['steps']", "upg-recipe-actions"):
        assert leak not in block, (
            f"default.latte planned block must not duplicate recipe rendering (found {leak})"
        )


# ── service.latte: the deep-link target exists ────────────────────────


def test_recipe_card_has_anchor_id():
    """The detail page recipe card must carry id="recipe-<id>" so the matrix's
    #recipe-<id> deep-link lands on the card that renders the recipe steps."""
    src = SERVICE_LATTE.read_text()
    assert re.search(
        r'<article\s+id="recipe-\{\$r\[\'id\'\]\}"',
        src,
    ), "service.latte recipe card must carry id=\"recipe-{$r['id']}\" (the deep-link target)"


def test_detail_page_renders_recipe_content():
    """Confirm the deep-link lands on REAL content — the recipe card renders the
    from→to, severity, and changelog/notes (the recipe surface F2 links to)."""
    src = SERVICE_LATTE.read_text()
    assert "upg-recipe-from-to" in src, "service.latte must render the recipe from→to range"
    assert "sev-badge" in src, "service.latte must render the recipe severity badge"
    assert "changelog" in src or "notes" in src, (
        "service.latte must render the recipe changelog/notes (the 'what it does' detail)"
    )


# ── helper ────────────────────────────────────────────────────────────


def _planned_block(src: str) -> str:
    """Extract the {if !empty($row['planned'])} … {elseif …} arm of default.latte
    so assertions scope to the planned-badge rendering only."""
    start = src.find("{if !empty($row['planned'])}")
    assert start != -1, "default.latte missing the {if !empty($row['planned'])} arm"
    end = src.find("{elseif", start)
    assert end != -1, "default.latte planned arm missing its {elseif} terminator"
    return src[start:end]
