"""Gate: an empty_ok backup store is not an alarm until data it HAD is gone.

2026-10-01: four upload stores declared empty_ok (nothing uploaded yet) fired
NosWarningBackupSourceEmpty on a fresh install — backup.sh knew, the metric did
not carry it. promtool (when present) proves fresh-empty is quiet, lost data
and a non-empty_ok zero both fire.
"""
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
RULES = REPO / "files/anatomy/plugins/prometheus-base/provisioning/rules/05-backup.yml"
spec = importlib.util.spec_from_file_location("exp", REPO / "files/observability/scripts/backup_status_exporter.py")
exp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exp)


def test_the_metric_carries_empty_ok():
    out = exp._render({"last_run": 1, "sources": [
        {"name": "dir-outline", "size_bytes": 0, "success": True, "empty_ok": True},
        {"name": "mariadb", "size_bytes": 9, "success": True}]}, 2.0)
    assert 'nos_backup_source_size_bytes{source="dir-outline",empty_ok="true"} 0' in out
    assert 'nos_backup_source_size_bytes{source="mariadb",empty_ok="false"} 9' in out


def test_backup_sh_records_the_declaration():
    sh = (REPO / "roles/pazny.backup/files/backup.sh").read_text()
    assert 'status_append "dir-${name}" 0 0 1 1' in sh and '"empty_ok": bool(int("${empty_ok}"' in sh


@pytest.mark.skipif(not shutil.which("promtool"), reason="promtool evaluates the rule (CI image / brew prometheus)")
def test_promtool_fresh_is_quiet_lost_and_undeclared_fire(tmp_path):
    shutil.copy(RULES, tmp_path / "rules.yml")
    alert = lambda s, e: {"exp_labels": {"severity": "warning", "nos_domain": "backup", "source": s, "empty_ok": e},
                          "exp_annotations": {
                              "summary": f"Backup source {s} is empty (0 bytes)",
                              "description": f"Source `{s}` produced a 0-byte archive. Even an\n\"empty\" database usually "
                                             "dumps to at least a few KB of schema.\nInspect the source logs before trusting this snapshot.\n",
                              "runbook_url": "https://github.com/thisisait/nOS/blob/master/docs/runbooks/NosWarningBackupSourceEmpty.md"}}
    (tmp_path / "t.yml").write_text(yaml.safe_dump({"rule_files": ["rules.yml"], "evaluation_interval": "1m", "tests": [{
        "interval": "1m", "input_series": [
            {"series": 'nos_backup_source_size_bytes{source="dir-fresh",empty_ok="true"}', "values": "0x400"},
            {"series": 'nos_backup_source_size_bytes{source="dir-lost",empty_ok="true"}', "values": "500x60 0x340"},
            {"series": 'nos_backup_source_size_bytes{source="dir-stalwart",empty_ok="false"}', "values": "0x400"}],
        "alert_rule_test": [{"eval_time": "6h", "alertname": "NosWarningBackupSourceEmpty",
                             "exp_alerts": [alert("dir-lost", "true"), alert("dir-stalwart", "false")]}]}]}))
    r = subprocess.run(["promtool", "test", "rules", "t.yml"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-500:]
