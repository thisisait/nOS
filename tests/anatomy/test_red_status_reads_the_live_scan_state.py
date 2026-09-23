"""red-status must ask the scanner's own notebook whether the scan ran.

MEASURED 2026-09-23. red-status reported "security scan stale — last full scan
16 d ago". Both scan-state.json files exist and disagreed by 16 days and 9
cycles:

    ~/.nos/security/scan-state.json    last_full_scan 2026-09-23T02:19  cycle 64
    docs/llm/security/scan-state.json  last_full_scan 2026-09-07T02:05  cycle 55

The scanner had run that morning. What was stale was the git PROMOTION of its
notebook — and scan-runner.sh says which is which in its own header: "Live
notebook is ~/.nos/security. Git copies under docs/llm/security/ are the last
promotion, not this writer's target."

The cost was not academic. That false red sat in the report while a real
CVSS 9.2 went unnoticed, and it taught its reader that "scan stale" is
background noise — the exact way a reader stops being read.

Both facts are kept: a promotion 16 days behind is real (it is what a fresh
checkout believes), it is simply a different red from a scanner that stopped.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

spec = importlib.util.spec_from_file_location("red_status", ROOT / "tools" / "red-status.py")
red = importlib.util.module_from_spec(spec)
spec.loader.exec_module(red)


def test_the_scan_state_read_is_the_writers_target_not_the_git_copy():
    live = str(red.SCAN_STATE)
    assert "docs/llm/security" not in live, (
        f"red-status reads the PROMOTED copy ({live}) — its age answers "
        "'when was the notebook last committed', never 'did the scan run'"
    )
    assert live.endswith("scan-state.json")
    assert ".nos/security" in live or "NOS_SECURITY_DIR" in live


def test_the_promoted_copy_is_still_read_as_its_own_fact():
    """Fixing the source must not silently drop the promotion lag."""
    assert "docs/llm/security" in str(red.SCAN_STATE_PROMOTED)
    src = (ROOT / "tools" / "red-status.py").read_text(encoding="utf-8")
    assert "promotion_behind" in src, (
        "the promotion lag stopped being reported at all — a fresh checkout "
        "reading a 9-cycle-old notebook is a real fact, not noise"
    )


def test_a_behind_promotion_renders_its_own_line():
    line = red.reds({"security_scan": {
        "stale": False, "age": "13 h ago", "cycle": 64, "scan_failed": [],
        "promoted_cycle": 55, "promoted_age": "16 d ago", "promotion_behind": True,
    }})
    assert any("not promoted" in x for x in line), line
    assert not any("scan stale" in x for x in line), (
        "a current scanner with a lagging promotion must NOT read as a stale scan"
    )
