"""W6.2 gate (2026-06-10) — dashboard tells the truth about data freshness.

Two dishonesty classes the serial review caught:
  1. The "Scan cycle" KPI echoed scan_config.schedule ("hourly") although
     scans are operator-fired on-demand (agent pulse jobs paused by the
     manual-over-auto doctrine) — the operator read a live cadence that
     did not exist.
  2. Every advisory card hardcoded `recency-fresh` — an April advisory
     glowed green in June.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]

PRESENTER = REPO / "files/anatomy/wing/app/Presenters/DashboardPresenter.php"
TEMPLATE = REPO / "files/anatomy/wing/app/Templates/Dashboard/default.latte"
SCAN_REPO = REPO / "files/anatomy/wing/app/Model/ScanStateRepository.php"


def test_template_does_not_echo_config_schedule():
    src = TEMPLATE.read_text()
    assert "$state['config']['schedule']" not in src, (
        "the Scan-cycle KPI must not echo scan_config.schedule — that field "
        "says 'hourly' while scans are on-demand; show last-scan age instead"
    )
    assert "scanAgeDays" in src and "scanStale" in src


def test_stale_threshold_mirrors_drift_hook():
    src = PRESENTER.read_text()
    assert "> 14" in src, (
        "scanStale must use the same 14-day threshold as the CVE drift hook "
        "(hooks/playbook-end.d/20-cve-drift-check.sh) — one stale definition"
    )


def test_advisory_recency_is_computed_not_hardcoded():
    tpl = TEMPLATE.read_text()
    assert '<span class="recency recency-fresh"></span>' not in tpl, (
        "advisory recency dot is hardcoded fresh again"
    )
    assert "$adv['recency']" in tpl
    src = PRESENTER.read_text()
    # All four buckets reachable.
    for cls in ("recency-fresh", "recency-recent", "recency-stale", "recency-old"):
        assert cls in src, f"recencyClass lost the {cls} bucket"


def test_scan_state_exposes_latest_cycle_timestamp():
    src = SCAN_REPO.read_text()
    assert "latest_cycle_at" in src, (
        "getState must expose latest_cycle_at — the dashboard recency truth "
        "reads it"
    )
