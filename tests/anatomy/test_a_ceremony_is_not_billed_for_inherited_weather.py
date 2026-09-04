"""A ceremony does not re-buy a gate failure that predates it.

MEASURED 2026-09-04. Three ceremonies — proposer (146k in), librarian (101k),
surveyor (99k) — all ended `needs_revision` on the same night, every one on the
same feedback: `gate set 'live' returned fail on tree … cortex-corpus-diff:
agrees is false`. The `live` set is nos-smoke + cortex-corpus-diff, and BOTH
judges are ambient — nos-smoke probes the running estate, cortex-corpus-diff
compares two live services; neither reads the tree, so no proposal or brief
moves them. The corpus disagreement was transient embed lag (it self-healed the
next night, agrees: {}), but while it was present it turned every ceremony
sharing the set into a ~150k-token no-op, each spending a pointless revision
iteration on a condition it could not touch. Fee 59.

The oracle now runs the gate ONCE at session start (baseline). A gate FAIL
whose failing judges were ALL already failing at baseline is inherited weather,
not this run's regression: satisfaction is restored (subject to the deliverable
check, which is the ceremony's own work). A judge that PASSED at baseline and
fails now — a real regression the ceremony caused — still fails, and the detail
names it. An indeterminate baseline leaves attribution off (conservative).

Executed against the real class, spawn injected. Retro: with the baseline call
removed, `inherited_only` is not satisfied — the old billing stands.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
AUTOLOAD = WING / "vendor/autoload.php"

pytestmark = pytest.mark.skipif(
    not AUTOLOAD.is_file(),
    reason="php binary or wing vendor/autoload.php missing — run `composer "
           "install` in files/anatomy/wing",
)

# A gate verdict carrying per-judge `runs`, the shape nos-loop actually emits.
PROBE = r"""
require __DIR__ . '/vendor/autoload.php';

use App\AgentKit\Outcome\GateOracle;

function verdict(string $result, array $runs, string $uuid = 'gr'): array {
    $exit = ['pass' => 0, 'fail' => 1, 'indeterminate' => 2][$result];
    return [
        'exit' => $exit,
        'stdout' => json_encode(['verdict' => [
            'result' => $result, 'uuid' => $uuid, 'runs' => $runs,
        ]]),
        'stderr' => '',
    ];
}

$smokeOk   = ['judge' => 'nos-smoke', 'result' => 'pass'];
$smokeFail = ['judge' => 'nos-smoke', 'result' => 'fail'];
$corpusOk  = ['judge' => 'cortex-corpus-diff', 'result' => 'pass'];
$corpusBad = ['judge' => 'cortex-corpus-diff', 'result' => 'fail'];

// Each scenario is (baseline verdict, iteration verdict). A stateful spawn
// hands back the baseline first, then the iteration.
function run_scenario(array $baseline, array $iteration): array {
    $calls = 0;
    $spawn = function (array $argv) use (&$calls, $baseline, $iteration): array {
        return $calls++ === 0 ? $baseline : $iteration;
    };
    $oracle = new GateOracle('/tmp', $spawn, null);   // no deliverable declared
    $oracle->baseline('live');
    $v = $oracle->judge(0, 'live', '');
    return ['satisfied' => $v['satisfied'], 'detail' => $v['detail'], 'score' => $v['score']];
}

$out = [];

// Baseline already failing on corpus-diff; iteration fails on the SAME judge.
// Inherited weather → satisfied, and the detail says so.
$out['inherited_only'] = run_scenario(
    verdict('fail', [$smokeOk, $corpusBad], 'base'),
    verdict('fail', [$smokeOk, $corpusBad], 'iter'));

// Baseline clean; iteration fails on nos-smoke. A real regression → NOT
// satisfied.
$out['new_regression'] = run_scenario(
    verdict('pass', [$smokeOk, $corpusOk], 'base'),
    verdict('fail', [$smokeFail, $corpusOk], 'iter'));

// Baseline failing on corpus-diff; iteration fails on corpus-diff AND nos-smoke.
// The NEW judge (nos-smoke) makes the whole verdict attributable again.
$out['inherited_plus_new'] = run_scenario(
    verdict('fail', [$smokeOk, $corpusBad], 'base'),
    verdict('fail', [$smokeFail, $corpusBad], 'iter'));

// Indeterminate baseline (cortex unreachable at session start) → attribution
// OFF; a later fail is billed normally.
$out['indeterminate_baseline'] = run_scenario(
    verdict('indeterminate', [['judge' => 'cortex-corpus-diff', 'result' => 'indeterminate']], 'base'),
    verdict('fail', [$smokeOk, $corpusBad], 'iter'));

// A clean pass is still a clean pass, baseline or no baseline.
$out['clean_pass'] = run_scenario(
    verdict('fail', [$smokeOk, $corpusBad], 'base'),
    verdict('pass', [$smokeOk, $corpusOk], 'iter'));

// RETRO / SAFETY: attribution is OFF until baseline() is called. The same
// inherited-only fail, judged WITHOUT establishing a baseline, is billed
// exactly as before — proving the baseline call is load-bearing and the
// mechanism dormant by default.
$spawnFail = static fn (array $argv): array => verdict('fail', [$smokeOk, $corpusBad], 'i');
$noBase = new GateOracle('/tmp', $spawnFail, null);   // baseline() NOT called
$nb = $noBase->judge(0, 'live', '');
$out['no_baseline'] = ['satisfied' => $nb['satisfied']];

echo json_encode($out);
"""


def _probe() -> dict:
    p = WING / "baseline-attr-probe.php"
    p.write_text("<?php\n" + PROBE, encoding="utf-8")
    try:
        out = subprocess.run(["php", p.name], cwd=WING, capture_output=True,
                             text=True, timeout=60)
    finally:
        p.unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_an_inherited_only_failure_is_not_billed_to_the_ceremony() -> None:
    got = _probe()["inherited_only"]
    assert got["satisfied"] is True, (
        "a gate failure present at baseline and unchanged at judge-time is "
        "still needs_revisioning the ceremony — fee 59 stands")
    assert "predates this run" in got["detail"] and "cortex-corpus-diff" in got["detail"], (
        "the detail does not name the inherited condition, so a reader cannot "
        "tell weather from the ceremony's own failure")


def test_a_new_regression_still_fails() -> None:
    got = _probe()["new_regression"]
    assert got["satisfied"] is False, (
        "a judge that passed at baseline and fails now is a regression the "
        "ceremony caused; excusing it would blind the gate to real breakage")


def test_an_inherited_failure_plus_a_new_one_is_attributable() -> None:
    got = _probe()["inherited_plus_new"]
    assert got["satisfied"] is False, (
        "one inherited judge does not launder a NEW failing judge alongside it")


def test_an_indeterminate_baseline_disables_attribution() -> None:
    got = _probe()["indeterminate_baseline"]
    assert got["satisfied"] is False, (
        "a baseline that never reached a verdict must not excuse anything — "
        "we cannot claim a failure is inherited if we never measured it")


def test_a_clean_pass_is_unaffected() -> None:
    got = _probe()["clean_pass"]
    assert got["satisfied"] is True


def test_attribution_is_off_until_a_baseline_is_established() -> None:
    """Dormant by default — the same inherited-only fail judged without a
    baseline is billed as before. The mechanism only ever EXCUSES on evidence
    it measured, never on its absence."""
    assert _probe()["no_baseline"]["satisfied"] is False


def test_the_runner_establishes_the_baseline_before_iterating() -> None:
    """The mechanism is worthless if the Runner never calls it: the baseline
    must run BEFORE the iteration loop, or every failure looks like a fresh
    one."""
    src = (WING / "app/AgentKit/Runner.php").read_text(encoding="utf-8")
    before = src.split("for ($iteration = 0;")[0]
    assert "$oracle->baseline(" in before, (
        "Runner never calls $oracle->baseline() before the loop, so the "
        "oracle has no pre-existing set to compare against")
