"""A fixture's dependencies are not the estate's exposure — but they are not
invisible either.

MEASURED 2026-09-23: 39 open Dependabot alerts, of which 33 pointed at
state/fixtures/repos-fixture/ — a fake repo the importer READS, never installs,
never builds, never ships. All four HIGH were in it, and one of them read
"@sveltejs/adapter-node has a BODY_SIZE_LIMIT bypass" while the shell ran a
version past every patched one listed. red-status therefore reported
"critical/high in @sveltejs/kit, vite" about code that does not run here.

Two failure modes, and this pins both: counting a fixture as exposure (the bug),
and silently dropping it so 39 becomes 6 with no explanation (the fix-shaped
version of the same bug).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import importlib.util

spec = importlib.util.spec_from_file_location("red_status", ROOT / "tools" / "red-status.py")
red = importlib.util.module_from_spec(spec)
spec.loader.exec_module(red)

ALERTS = [
    {"sev": "high", "pkg": "@sveltejs/kit",
     "manifest": "state/fixtures/repos-fixture/mesto-portal/package.json"},
    {"sev": "high", "pkg": "vite",
     "manifest": "state/fixtures/repos-fixture/mesto-portal/package.json"},
    {"sev": "medium", "pkg": "devalue", "manifest": "files/anatomy/face/package-lock.json"},
]


def _dependabot(monkeypatched):
    """Run dependabot() against a canned alert list."""
    red._gh = lambda *a, **k: monkeypatched  # noqa: SLF001 — the one network seam
    return red.dependabot()


def test_a_fixture_alert_is_not_counted_as_our_exposure():
    out = _dependabot(ALERTS)
    assert out["counts"] == {"medium": 1}, (
        f"fixture alerts leaked into the estate's tally: {out['counts']}"
    )
    assert out["serious_packages"] == [], (
        "a HIGH in a fixture was reported as critical/high in a shipped package — "
        "that is the line that sent a reader to harden code we do not run"
    )


def test_the_set_aside_ones_are_still_reported():
    out = _dependabot(ALERTS)
    assert out["fixture_alerts"] == 2, (
        "the fixture alerts vanished instead of being counted apart; a number "
        "that quietly shrank is the same defect as one that was quietly wrong"
    )
    line = red.reds({"dependabot": out})[-1]
    assert "state/fixtures/" in line, f"the rendered red line hides the split: {line!r}"


def test_a_real_alert_still_reaches_the_tally():
    """The separation must not be a way to report nothing."""
    out = _dependabot([{"sev": "critical", "pkg": "openssl",
                        "manifest": "files/anatomy/bone/requirements.txt"}])
    assert out["counts"] == {"critical": 1}
    assert out["serious_packages"] == ["openssl"]
