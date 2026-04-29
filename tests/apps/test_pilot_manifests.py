"""
tests/apps/test_pilot_manifests.py — parse-time gate for the Tier-2
pilot manifests in `apps/`. Catches schema-vs-pilot drift in CI before
it reaches the playbook (where the same parser would reject — but only
during a blank, which costs operator-time).

Each pilot manifest is parametrized so the CI failure message names the
specific pilot that broke, not just "tests/apps fail".

Excluded: apps/_template.yml (template, not deployable), apps/*.draft
(intentionally excluded — operator hasn't promoted them).
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
APPS_DIR = REPO / "apps"


def _live_pilots() -> list[Path]:
    """Discover live pilots — every apps/*.yml that isn't _template
    and doesn't have .draft anywhere in the suffix chain."""
    out: list[Path] = []
    for p in sorted(APPS_DIR.glob("*.yml")):
        if p.name.startswith("_"):
            continue
        if ".draft" in p.suffixes or p.suffix == ".draft":
            continue
        out.append(p)
    return out


PILOTS = _live_pilots()


@pytest.mark.parametrize("manifest", PILOTS, ids=lambda p: p.name)
def test_pilot_manifest_parses_cleanly(manifest: Path):
    """Every live pilot must pass parse_app_file without raising."""
    # Late import so the module is loaded once per test session
    import sys
    sys.path.insert(0, str(REPO))
    try:
        from module_utils.nos_app_parser import parse_app_file
    finally:
        sys.path.pop(0)

    record = parse_app_file(str(manifest))

    # Sanity: the slug from filename matches meta.name (the schema
    # already enforces this at parse time, but assert explicitly so
    # the failure message is direct.)
    expected_name = manifest.stem
    assert record["meta"]["name"] == expected_name, (
        "filename slug '{}' != meta.name '{}'".format(
            expected_name, record["meta"]["name"]
        )
    )

    # GDPR block must have all mandatory keys (parser already enforces;
    # asserting here gives a clear test failure message if the schema
    # ever drifts and an old pilot manifest no longer satisfies it).
    gdpr = record.get("gdpr") or {}
    for key in ("purpose", "legal_basis", "data_categories",
                "data_subjects", "retention_days", "processors",
                "transfers_outside_eu"):
        assert key in gdpr, (
            "{} missing required gdpr.{}".format(manifest.name, key)
        )


def test_at_least_one_pilot_present():
    """Sanity that the discovery picked up the three Phase-1 pilots —
    catches the case where someone accidentally renamed all to .draft
    or deleted them."""
    names = sorted(p.stem for p in PILOTS)
    # We expect at minimum twofauth + roundcube + documenso. Plane is
    # explicitly .draft until further notice.
    expected_subset = {"twofauth", "roundcube", "documenso"}
    assert expected_subset.issubset(set(names)), (
        "expected at least {} live in apps/, found {}".format(
            sorted(expected_subset), names
        )
    )
