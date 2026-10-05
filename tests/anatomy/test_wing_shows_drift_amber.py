"""Wing shows drift amber, with the meaning nos-atlas paints it (operator 2026-10-04).

Drift is a job whose latest run exited with a DECLARED findings code: tofu-drift
rc=1, discovery-scan's contradictions. It is a known disagreement — not broken
(it is not in "Estate red"), and not green either. Until this gate the hub
dropped those runs on the floor: `failingJobs()` skipped them and nothing else
counted them, so a drifting estate read as clean.

The repository is EXECUTED here (php + a sqlite-backed stub Explorer), so the
split is judged by what it returns, not by how the PHP reads.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing/app"

STUB = r"""<?php
declare(strict_types=1);
namespace Nette\Database;
final class Explorer {
    public function __construct(private \PDO $pdo) {}
    public function query(string $sql): array {
        return array_map(fn($r) => (object) $r, $this->pdo->query($sql)->fetchAll(\PDO::FETCH_ASSOC));
    }
    public function table(string $t): object {
        $pdo = $this->pdo;
        return new class($pdo, $t) {
            public function __construct(private \PDO $pdo, private string $t) {}
            public function get(string $id): ?object {
                $s = $this->pdo->prepare("SELECT * FROM {$this->t} WHERE id = ?"); $s->execute([$id]);
                $r = $s->fetch(\PDO::FETCH_ASSOC); return $r ? (object) $r : null;
            }
        };
    }
}
namespace Probe;
require '%s';
$pdo = new \PDO('sqlite::memory:');
$pdo->exec("CREATE TABLE pulse_jobs (id TEXT PRIMARY KEY, findings_exit_codes TEXT, removed_at TEXT)");
$pdo->exec("CREATE TABLE pulse_runs (run_id TEXT, job_id TEXT, fired_at TEXT, exit_code INT)");
foreach ([['tofu:drift', '[1]'], ['loop:review', null], ['ok:job', '[1]']] as [$id, $codes]) {
    $pdo->prepare("INSERT INTO pulse_jobs (id, findings_exit_codes) VALUES (?, ?)")->execute([$id, $codes]);
}
foreach ([['1', 'tofu:drift', '2026-10-04T05:30:00Z', 1], ['2', 'loop:review', '2026-10-04T06:00:00Z', 2],
          ['3', 'ok:job', '2026-10-04T06:00:00Z', 0]] as $r) {
    $pdo->prepare("INSERT INTO pulse_runs VALUES (?, ?, ?, ?)")->execute($r);
}
$v = (new \App\Model\PulseRepository(new \Nette\Database\Explorer($pdo)))->latestVerdicts();
echo json_encode(array_map(fn($rows) => array_column($rows, 'job_id'), $v));
"""


@pytest.mark.skipif(shutil.which("php") is None, reason="php not installed on this runner")
def test_a_findings_code_is_drift_not_red_and_not_dropped(tmp_path):
    probe = tmp_path / "probe.php"
    probe.write_text(STUB % (WING / "Model/PulseRepository.php"), encoding="utf-8")
    r = subprocess.run(["php", "-d", "error_reporting=E_ALL", str(probe)],
                       capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout) == {"failing": ["loop:review"], "findings": ["tofu:drift"]}


def test_the_hub_renders_drift_in_amber():
    presenter = (WING / "Presenters/HubPresenter.php").read_text(encoding="utf-8")
    assert re.search(r"estateDrift\s*=\s*\$verdicts\['findings'\]", presenter), (
        "HubPresenter does not hand the findings bucket to the template")
    tpl = (WING / "Templates/Hub/default.latte").read_text(encoding="utf-8")
    tile = re.search(r'<div class="stat"[^\n]*\n\s*<div class="label">Estate drift</div>.*?(?=<div class="stat")', tpl, re.S)
    assert tile, "no Estate drift tile on /hub"
    assert "var(--orange)" in tile.group(0) and "var(--red)" not in tile.group(0) \
        and "var(--green)" not in tile.group(0), "drift must be amber: not red, not green"
    assert "$estateDrift" in tile.group(0)
