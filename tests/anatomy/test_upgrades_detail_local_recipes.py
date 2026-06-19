"""Anatomy CI gate for the /upgrades/<service> detail-page recipes fix (F4).

The operator's live visual review found that the service DETAIL page
(/upgrades/<service>) rendered EMPTY — no recipe cards — even though the matrix
LIST page (/upgrades) showed the recipes fine. Root cause:
``UpgradeRepository::forService()`` sourced its ``{service, docs_url, recipes:[]}``
from a LIVE Bone/BoxAPI call (``GET /api/upgrades/<service>``) that returns
null/empty here, whereas ``matrix()`` reads the LOCAL ``upgrade_recipes`` SQLite
table (which IS populated). The detail page is the single recipe-rendering
surface (it owns the F2 ``#recipe-<id>`` deep-link target), so it must NOT depend
on a live Bone call.

This gate pins the fix:

  1. ``UpgradeRepository::forService()`` builds its recipe list from the LOCAL
     ``upgrade_recipes`` table (the same offline source as ``matrix()``), ordered
     ``to_version DESC``, NOT from a Bone-only call. Any BoxAPI use is an OPTIONAL
     best-effort overlay that never empties the recipe list.
  2. ``UpgradesPresenter::renderService()`` spreads ``$data['recipes']`` (and
     ``docs_url`` / ``installed``) into the TOP-LEVEL template vars service.latte
     reads — without the spread the page rendered the empty state regardless.
  3. ``notFound`` stays correct: true only when the service has no recipes at all.

Regex/source-only (no PHP execution) — consistent with test_planned_recipe_link.py
and test_plan_choice_ui.py, so the gate runs on the pytest+pyyaml stack (the
functional twin lives in tests/wing-api/test_upgrade_repository.php, which needs
composer and is --ignore'd in CI).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
REPOSITORY = WING / "app" / "Model" / "UpgradeRepository.php"
PRESENTER = WING / "app" / "Presenters" / "UpgradesPresenter.php"
SERVICE_LATTE = WING / "app" / "Templates" / "Upgrades" / "service.latte"


def _for_service_body(src: str) -> str:
    """Extract the body of UpgradeRepository::forService()."""
    start = src.find("public function forService(")
    assert start != -1, "UpgradeRepository::forService() not found"
    # forService is followed by getRecipe(); scope to the next public function.
    end = src.find("public function getRecipe(", start)
    assert end != -1, "could not bound forService() body (getRecipe gone?)"
    return src[start:end]


# ── Repository: recipes come from the LOCAL catalog, not a live Bone call ──


def test_for_service_reads_local_upgrade_recipes_table():
    """forService() MUST source its recipes from the local upgrade_recipes table
    (the same offline source matrix() reads) — the fix for the empty detail page."""
    body = _for_service_body(REPOSITORY.read_text())
    assert "upgrade_recipes" in body, (
        "forService() must SELECT from the local upgrade_recipes table "
        "(the offline catalog), not source recipes from a live Bone call"
    )
    assert "->where('service', $service)" in body, (
        "forService() must scope the catalog query to the requested service"
    )
    assert "to_version DESC" in body or "to_version', 'DESC'" in body, (
        "forService() must order recipes to_version DESC (matrix's order — [0] is latest)"
    )


def test_for_service_recipes_not_sourced_from_bone():
    """The recipe LIST must not be whatever Bone returned. A Bone outage / null
    body must never empty the recipes — the local catalog is authoritative."""
    body = _for_service_body(REPOSITORY.read_text())
    # The pre-fix code did `return $resp['body'];` straight from the Bone GET —
    # which is exactly what produced the empty page. That must be gone.
    assert "return $resp['body'];" not in body, (
        "forService() must NOT return the raw Bone body as the recipe payload "
        "(that is the F4 bug — Bone returns empty here)"
    )
    # The assembled payload's recipes key must be built locally (a $recipes var
    # populated from the catalog loop), not handed over from $resp.
    assert re.search(r"['\"]recipes['\"]\s*=>\s*\$recipes", body), (
        "forService() must return its locally-built $recipes array"
    )


def test_for_service_maps_template_keys():
    """Each recipe must carry the keys service.latte's card renders so the cards
    actually populate (id / from_regex / to / severity / coexistence_supported)."""
    body = _for_service_body(REPOSITORY.read_text())
    for key in ("'id'", "'from_regex'", "'to'", "'severity'", "'coexistence_supported'"):
        assert key in body, (
            f"forService() recipe rows must carry {key} (a key service.latte reads)"
        )


def test_for_service_bone_overlay_is_optional_best_effort():
    """If BoxAPI is still consulted it must be a guarded, best-effort overlay that
    can never throw the recipe list away (wrapped so a Bone outage is invisible)."""
    body = _for_service_body(REPOSITORY.read_text())
    if "$this->box->get(" in body:
        assert "try {" in body and "catch" in body, (
            "any forService() Bone call must be in a try/catch best-effort overlay "
            "so a Bone outage never empties the locally-sourced recipe list"
        )


def test_for_service_returns_null_only_when_no_recipes():
    """notFound correctness: forService() returns null ONLY when the catalog has
    no recipes for the service (so the presenter's notFound flag stays honest)."""
    body = _for_service_body(REPOSITORY.read_text())
    assert re.search(r"\$recipes\s*===\s*\[\]", body), (
        "forService() must return null when (and only when) there are no recipes"
    )


# ── Presenter: spread the local payload into the template's top-level vars ──


def test_render_service_spreads_recipes_to_top_level():
    """service.latte reads top-level {$recipes}/{$docs_url}/{$installed}, NOT
    {$data[...]} — renderService() must set those vars or the page is empty."""
    src = PRESENTER.read_text()
    start = src.find("public function renderService(")
    assert start != -1, "UpgradesPresenter::renderService() not found"
    body = src[start:]
    assert re.search(r"\$this->template->recipes\s*=\s*\$data\['recipes'\]", body), (
        "renderService() must spread $data['recipes'] into $this->template->recipes "
        "(service.latte reads the top-level {$recipes}, not {$data[...]})"
    )
    assert "$this->template->docs_url" in body, (
        "renderService() must expose docs_url for the 'Upstream docs' link"
    )
    assert "$this->template->installed" in body, (
        "renderService() must expose the installed version for the detail header"
    )
    assert "$this->template->notFound" in body, (
        "renderService() must keep setting notFound"
    )


# ── Template: the recipe cards render the local-sourced keys ──


def test_service_template_renders_recipes_var():
    """service.latte gates its cards on top-level {$recipes} (what renderService
    now spreads) and renders the deep-link anchor + from→to range."""
    src = SERVICE_LATTE.read_text()
    assert re.search(r"\{if empty\(\$recipes\)\}", src), (
        "service.latte must gate the empty-state on {$recipes} (top-level var)"
    )
    assert re.search(r"\{foreach \$recipes as \$r\}", src), (
        "service.latte must iterate the top-level {$recipes} to render the cards"
    )
    assert re.search(r'<article\s+id="recipe-\{\$r\[\'id\'\]\}"', src), (
        "service.latte recipe card must carry the id=\"recipe-<id>\" deep-link anchor"
    )
