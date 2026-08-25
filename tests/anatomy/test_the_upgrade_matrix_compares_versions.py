"""The upgrades page must not offer a downgrade, and must not compare with `===`.

WHAT THE OPERATOR SAW, 2026-08-25: "different versions" on Wing's /upgrades
page. Measured against the running estate, 22 of the 29 catalog targets sat AT
OR BELOW the running version and the matrix presented them as the next step.

Two defects, both failing towards "an upgrade is available":

  1. `$atTarget` was `$inst === $stable`. `16.15-alpine` never equals `16` and
     `v0.162.19` never equals `0.160.4`, so postgresql and infisical read as
     upgradable for ever.
  2. When a recipe's `from_pattern` matched but its target was BELOW installed,
     that target became the next step. GitLab's `^18\\.([0-9]|[1-9][0-9])\\.`
     matches an installed 18.11.9 and targets 18.10.3 — a DOWNGRADE displayed
     as the upgrade, on the one service then carrying an unauthenticated
     CVSS 9.4 (CVE-2026-19478) whose floor is 19.2.4.

That is the estate's recurring shape in a third place. `docs/hidden_fees` and
REM-178 record it for the security queue: **a recorded target below what the
estate runs re-opens the gap if anyone acts on it.** A page is a consumer like
any other.

WHAT IS PINNED. The comparison is numeric; it REFUSES rather than guessing on
anything that is not a version; a target at or below installed is filtered out
of the applicable set; and when nothing survives the row says the CATALOG is
behind — which is a different fact from "up to date" and must not read as one.

WHAT IT CANNOT SEE. Whether the recipes are current (they are not — that is the
upgrade-architect agent's work), or whether the page renders these fields.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
REPOSITORY = REPO / "files/anatomy/wing/app/Model/UpgradeRepository.php"

#: (installed, target, expected) — every one measured on this estate on
#: 2026-08-25 except the two synthetic refusals at the end.
#:   "ahead"   installed is past the target: NOT an upgrade
#:   "upgrade" target is genuinely above installed
#:   "equal"   the same version, differently spelled
#:   None      not a version on one side — the comparison must refuse
CASES = [
    ("16.15-alpine", "16", "ahead"),          # postgresql: read as upgradable for ever
    ("v0.162.19", "0.160.4", "ahead"),        # infisical: leading v + a real gap
    ("18.11.9-ce.0", "18.10.3-ce.0", "ahead"),   # gitlab: the downgrade it offered
    ("18.11.9-ce.0", "19.2.4-ce.0", "upgrade"),  # gitlab: the CVE floor it did not
    ("1.27.2", "1.27.0", "ahead"),            # gitea: REM-178's own shape
    ("12.4.4", "12.4.9", "upgrade"),          # grafana: REM-226, live today
    ("2.2.5", "2.2.5", "equal"),
    ("sha-b9a80dc", "sha-c1f2e3d", None),     # paperclip is pinned by build id
    ("latest", "1.2.3", None),
]


def _php() -> str | None:
    return shutil.which("php")


@pytest.mark.skipif(_php() is None, reason="php absent — the comparison cannot run")
@pytest.mark.parametrize("installed,target,expected", CASES,
                         ids=[f"{a}_vs_{b}" for a, b, _ in CASES])
def test_versions_compare_the_way_the_estate_needs(installed, target, expected):
    script = (
        f'require "{REPOSITORY}";'
        f'$r = App\\Model\\UpgradeRepository::compareVersions({installed!r}, {target!r});'
        'echo $r === null ? "null" : ($r > 0 ? "ahead" : ($r < 0 ? "upgrade" : "equal"));'
    ).replace("'", '"', 0)
    out = subprocess.run(["php", "-r", script], capture_output=True, text=True, timeout=60)
    got = out.stdout.strip()
    want = "null" if expected is None else expected
    assert got == want, (
        f"compareVersions({installed!r}, {target!r}) said {got!r}, expected {want!r}\n"
        f"{out.stderr[-300:]}")


def test_a_target_at_or_below_installed_is_not_an_upgrade():
    """The filter, read structurally. `from_pattern` matching is not enough —
    it is what let GitLab offer 18.10.3 to a box running 18.11.9."""
    src = REPOSITORY.read_text(encoding="utf-8")
    body = src[src.index("public function matrix()"):]
    assert "array_filter($applicable" in body, (
        "the applicable set is no longer filtered against the installed "
        "version; a recipe whose from_pattern matches can target a downgrade")
    assert "compareVersions" in body, "the filter is not comparing versions"


def test_at_target_is_decided_numerically_not_by_string_equality():
    """The defect that made postgresql and infisical read as upgradable for
    ever. Added after a mutation proved the first cut of this file could not
    see it: reverting `$atTarget` to `$inst === $stable` left every assertion
    here green."""
    src = REPOSITORY.read_text(encoding="utf-8")
    body = src[src.index("$atTarget ="):]
    body = body[:body.index(";") + 1]
    assert "compareVersions" in body or "$cmpStable" in body, (
        "at-target is decided by string equality again. `16.15-alpine` never "
        f"equals `16`, so the row claims an upgrade for ever:\n  {body}")
    assert ">= 0" in body, (
        "at-target must be installed AT OR PAST the target, not merely equal — "
        "an estate ahead of its catalog is not mid-upgrade")


def test_the_row_distinguishes_up_to_date_from_catalog_behind():
    """Two different facts. 'nothing above you exists in the catalog' is a
    statement about the RECIPES; an operator reading it as 'you are current'
    would have read GitLab as safe while it sat inside an unauthenticated 9.4."""
    src = REPOSITORY.read_text(encoding="utf-8")
    assert "'ahead_of_catalog'" in src, (
        "the matrix no longer reports when the catalog is behind the estate — "
        "the row then reads as up-to-date, which is a different claim")


def test_an_unreadable_comparison_never_hides_a_recipe():
    """`null` must not remove a recipe from the applicable set. Refusing to
    compare is not the same as knowing it is unnecessary, and the safe
    direction for a page that offers upgrades is to keep showing it."""
    src = REPOSITORY.read_text(encoding="utf-8")
    body = src[src.index("array_filter($applicable"):]
    body = body[:body.index("}));") + 4]
    assert "$cmp === null || $cmp > 0" in body, (
        "an uncomparable target is being filtered out; a refusal to compare "
        f"would then silently hide an available upgrade:\n{body}")
