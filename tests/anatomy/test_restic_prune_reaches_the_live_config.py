"""The prune schedule and retention nOS declares reach a Backrest config the daemon already owns.

11-04: the restic repo held 159 GiB, nothing ever removed. prunePolicy was maxFrequencyDays 7,
counted from each daemon start, and the daemon restarted every 0-3 days: 48 prunes scheduled,
0 run. The template is seed-once, so a fixed-clock schedule there never reaches a live daemon;
enable-auth.py reconciles the keys nOS owns. This runs it on a live-shaped config.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "roles/pazny.backrest/files/enable-auth.py"
CRON = {"cron": "0 6 * * 0", "clock": "CLOCK_LOCAL"}


def _live():
    return {"version": 6, "modno": 42, "auth": {"users": [{"name": "admin", "passwordBcrypt": "x"}]},
            "repos": [{"id": "offsite", "uri": "/r", "guid": "abc",
                       "prunePolicy": {"schedule": {"maxFrequencyDays": 7}, "maxUnusedPercent": 10},
                       "checkPolicy": {"schedule": {"maxFrequencyDays": 30}}}],
            "plans": [{"id": "nos-dumps", "repo": "offsite", "paths": ["/s"],
                       "retention": {"policyTimeBucketed": {"daily": 7, "weekly": 4, "monthly": 12}}}]}


def _seed():
    return {"repos": [{"id": "offsite", "uri": "/r", "prunePolicy": {"schedule": CRON, "maxUnusedPercent": 10},
                       "checkPolicy": {"schedule": {"cron": "0 7 1 * *", "clock": "CLOCK_LOCAL"}}}],
            "plans": [{"id": "nos-dumps", "repo": "offsite", "paths": ["/s"],
                       "retention": {"policyTimeBucketed": {"daily": 7, "weekly": 4, "monthly": 3}}}]}


def _run(tmp: Path) -> str:
    return subprocess.run([sys.executable, str(TOOL), "--config", str(tmp / "config.json"),
                           "--user", "admin", "--seed", str(tmp / "seed.json")],
                          input="not-a-real-password\n", capture_output=True, text=True, timeout=30).stdout


def test_the_declared_schedule_and_retention_reach_the_live_config(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(_live()))
    (tmp_path / "seed.json").write_text(json.dumps(_seed()))
    assert "CHANGED" in _run(tmp_path)
    got = json.loads((tmp_path / "config.json").read_text())
    repo, plan = got["repos"][0], got["plans"][0]
    assert repo["prunePolicy"]["schedule"] == CRON, repo
    assert plan["retention"]["policyTimeBucketed"]["monthly"] == 3, plan
    assert repo["guid"] == "abc" and got["modno"] == 42 and repo["uri"] == "/r", "a daemon-owned key moved"


def test_a_reconciled_config_is_left_alone(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps(_live()))
    (tmp_path / "seed.json").write_text(json.dumps(_seed()))
    _run(tmp_path)
    assert "UNCHANGED" in _run(tmp_path), "a second run rewrote an already reconciled config"
