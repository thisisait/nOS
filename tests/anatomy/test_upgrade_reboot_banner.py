"""Anatomy gate: the Phase-3 host_reboot-pending banner on Wing /upgrades.

Spec: docs/archive/upgrade-reset-scope-and-session-safety.md §"Execution side"
("reboot_required surfacing") + §"Run mode" (host_reboot = stage, never auto-reboot).

The upgrade-engine writes ~/.nos/reboot-required.json after a successful
host_reboot-class apply (the engine NEVER auto-reboots — manual over auto). Wing
surfaces it as a persistent /upgrades banner until the operator reboots (which
clears the marker). This gate pins the WING side only (presenter + repo + latte):

  1. UpgradeRepository::rebootMarker() reads the ~/.nos/reboot-required.json
     runtime sidecar and returns null on an ABSENT or MALFORMED marker (graceful
     — never crash the page, never spuriously nag).
  2. UpgradesPresenter::renderDefault() reads the marker and passes it to the
     template ($rebootPending).
  3. default.latte renders the banner ONLY when $rebootPending (a present marker),
     showing the service + recipe + a note that the host must be rebooted.

Regex/source-only (no PHP execution) — consistent with
test_upgrades_detail_local_recipes.py / test_plan_choice_ui.py, so the gate runs
on the pytest+pyyaml stack without composer.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
REPOSITORY = WING / "app" / "Model" / "UpgradeRepository.php"
PRESENTER = WING / "app" / "Presenters" / "UpgradesPresenter.php"
DEFAULT_LATTE = WING / "app" / "Templates" / "Upgrades" / "default.latte"


def _reboot_marker_body(src: str) -> str:
    """Extract the body of UpgradeRepository::rebootMarker()."""
    start = src.find("public function rebootMarker(")
    assert start != -1, "UpgradeRepository::rebootMarker() not found"
    # rebootMarker() is followed by the next method (coexistenceTracksByService /
    # decodeReset / etc.); bound it at the next 'function ' after the opening.
    end = src.find("function ", start + len("public function rebootMarker("))
    assert end != -1, "could not bound rebootMarker() body"
    return src[start:end]


# ── Repository: read the runtime sidecar, null on absent/malformed ──


def test_reboot_marker_reads_sidecar_json():
    """rebootMarker() MUST read ~/.nos/reboot-required.json from the runtime
    sidecar (the same ~/.nos/ convention installedVersionsFromState uses)."""
    body = _reboot_marker_body(REPOSITORY.read_text())
    assert "/.nos/reboot-required.json" in body, (
        "rebootMarker() must read the ~/.nos/reboot-required.json marker the "
        "upgrade-engine writes on a host_reboot-class apply"
    )
    assert "getenv('HOME')" in body, (
        "rebootMarker() must resolve HOME via getenv('HOME') (Wing runs as launchd "
        "— same convention as installedVersionsFromState())"
    )
    assert "json_decode" in body, "rebootMarker() must JSON-decode the marker"


def test_reboot_marker_null_when_absent():
    """An ABSENT marker → no banner: rebootMarker() returns null when the file is
    not present (is_file guard)."""
    body = _reboot_marker_body(REPOSITORY.read_text())
    assert "is_file(" in body, (
        "rebootMarker() must guard on is_file() so an absent marker returns null"
    )
    assert "return null;" in body, (
        "rebootMarker() must return null when there is no usable marker"
    )


def test_reboot_marker_null_when_malformed():
    """A MALFORMED marker → no banner: a JSON error (or a non-object payload) must
    be caught and yield null, never an exception bubbling to the page."""
    body = _reboot_marker_body(REPOSITORY.read_text())
    assert "JsonException" in body, (
        "rebootMarker() must catch a JsonException (malformed JSON → null, not a "
        "fatal that crashes /upgrades)"
    )
    # The decoded payload must be validated as an object before it is trusted —
    # a bare array / scalar is malformed and must yield null.
    assert "is_array(" in body, (
        "rebootMarker() must validate the decoded marker is an object before "
        "returning it (malformed non-object → null)"
    )


def test_reboot_marker_is_public():
    """The presenter consumes rebootMarker() — it must be a public method."""
    src = REPOSITORY.read_text()
    assert "public function rebootMarker(" in src, (
        "rebootMarker() must be public so UpgradesPresenter can call it"
    )


# ── Presenter: read the marker, pass it to the template ──


def test_presenter_passes_reboot_pending():
    """renderDefault() must read the marker via rebootMarker() and expose it on
    the template as $rebootPending (the banner's gate var)."""
    src = PRESENTER.read_text()
    start = src.find("public function renderDefault(")
    assert start != -1, "UpgradesPresenter::renderDefault() not found"
    # renderDefault is followed by actionQueueUpgrade; scope to that boundary.
    end = src.find("public function actionQueueUpgrade(", start)
    assert end != -1, "could not bound renderDefault() body"
    body = src[start:end]
    assert re.search(
        r"\$this->template->rebootPending\s*=\s*\$this->upgrades->rebootMarker\(\)",
        body,
    ), (
        "renderDefault() must set $this->template->rebootPending from "
        "$this->upgrades->rebootMarker() (the /upgrades banner var)"
    )


# ── Template: render the banner ONLY when the marker is present ──


def test_template_banner_gated_on_reboot_pending():
    """default.latte must render the banner ONLY inside an {if $rebootPending}
    guard — no marker → no banner."""
    src = DEFAULT_LATTE.read_text()
    assert re.search(r"\{if\s+\$rebootPending\}", src), (
        "default.latte must gate the reboot banner on {if $rebootPending} so an "
        "absent/null marker renders no banner"
    )
    # The banner block + the guard must come as a pair (the {/if} closes it).
    assert "upg-reboot-banner" in src, (
        "default.latte must render the .upg-reboot-banner element when reboot is pending"
    )


def _reboot_guard_block(src: str) -> str:
    """Return the body of the OUTER {if $rebootPending} ... {/if} block, honouring
    nested {if}/{/if} pairs (the banner contains an inner {if} for requested_at)."""
    open_m = re.search(r"\{if\s+\$rebootPending\}", src)
    assert open_m is not None, "{if $rebootPending} ... {/if} block not found"
    i = open_m.end()
    depth = 1
    body_start = i
    token = re.compile(r"\{if\b|\{/if\}")
    while depth > 0:
        m = token.search(src, i)
        assert m is not None, "unbalanced {if}/{/if} around the reboot banner"
        if m.group(0) == "{/if}":
            depth -= 1
            if depth == 0:
                return src[body_start:m.start()]
        else:
            depth += 1
        i = m.end()
    raise AssertionError("unreachable")


def test_template_banner_inside_guard():
    """The .upg-reboot-banner element must live strictly INSIDE the
    {if $rebootPending} ... {/if} block — never rendered unconditionally."""
    src = DEFAULT_LATTE.read_text()
    block = _reboot_guard_block(src)
    assert "upg-reboot-banner" in block, (
        "the .upg-reboot-banner markup must sit INSIDE the {if $rebootPending} "
        "guard (so it never renders without a marker)"
    )
    # No stray .upg-reboot-banner *element* (class="upg-reboot-banner") outside the
    # guard — match the opening div precisely so the banner is rendered once, gated.
    outside = src.replace(block, "")
    assert 'class="upg-reboot-banner"' not in outside, (
        "no .upg-reboot-banner element may render outside the {if $rebootPending} guard"
    )


def test_template_banner_shows_service_and_reboot_note():
    """The banner copy must name the service being completed and tell the operator
    the host must be rebooted to finish (the actionable message)."""
    src = DEFAULT_LATTE.read_text()
    block = _reboot_guard_block(src)
    assert "$rebootPending['service']" in block, (
        "the banner must render the pending service from $rebootPending['service']"
    )
    assert "$rebootPending['recipe_id']" in block, (
        "the banner must surface the recipe id from $rebootPending['recipe_id']"
    )
    assert re.search(r"[Rr]eboot", block), (
        "the banner copy must tell the operator the host must be rebooted to finish"
    )
