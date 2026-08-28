"""Anatomy gate — the outcome loop reports its PEAK, and stops near it.

Claims about GateOracle, driven through the real class with the SUBPROCESS
replaced and nothing else. The stub hands back an exit code and the stdout
`nos-loop judge --wait --json` hands back; the class still computes the verdict
from that, so nothing here can supply a result.

  1. BEST, not last. A run that passes at iteration 1 reports iteration 1;
     a run that peaks and then does not beat itself reports the peak.
  2. ONE iteration past an unbeaten peak, then stop (arXiv:2607.25886 —
     78.26% of self-continued searches end below their own peak).
  3. Three things must agree for satisfaction — exit 0, verdict `pass`, and a
     verdict uuid. INDETERMINATE is not a pass, and a verdict nobody can name
     cannot be replayed, which is why agent_iterations refuses to store it.

The oracle reaches the engine through `nos-loop`, never by importing `judges`
— DECISION 6, pinned by test_loop_determinism_across_harnesses.py. That the
argv is the CLI's is asserted here too, because a second in-process judge
runner is the failure this arrangement exists to prevent.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
AUTOLOAD = WING / "vendor" / "autoload.php"

pytestmark = [
    pytest.mark.skipif(shutil.which("php") is None, reason="php not on PATH"),
    pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor tree not installed"),
]

PRELUDE = """
/** @param array<int,array{0:int,1:string}> $script exit + verdict result per iteration */
function oracle(array $script, &$argvSeen = null): GateOracle {
    $i = 0;
    return new GateOracle('/nonexistent-repo', function (array $argv) use ($script, &$i, &$argvSeen) {
        $argvSeen = $argv;
        [$exit, $result] = $script[$i++];
        $job = ['state' => 'done', 'verdict' => [
            'uuid' => 'v-' . $i, 'result' => $result, 'gate_set' => 'fast',
            'tree_sha' => str_repeat('a', 40),
            'evidence' => ['reason' => "judge said {$result}"],
        ]];
        return ['exit' => $exit, 'stdout' => json_encode($job), 'stderr' => ''];
    });
}
"""


def _drive(tmp_path: pathlib.Path, script: str) -> dict:
    probe = tmp_path / "probe.php"
    probe.write_text(
        "<?php\n"
        f"require {str(AUTOLOAD)!r};\n"
        "use App\\AgentKit\\Outcome\\GateOracle;\n"
        + PRELUDE
        + script,
        encoding="utf-8",
    )
    r = subprocess.run(["php", str(probe)], capture_output=True, text=True)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    return json.loads(r.stdout)


def test_the_passing_iteration_is_the_one_reported(tmp_path):
    """pass -> fail -> fail. Iteration 1 is what the session reports, and the
    loop never pays for the two that follow."""
    got = _drive(tmp_path, """
$o = oracle([[0, 'pass'], [1, 'fail'], [1, 'fail']]);
$seen = [];
for ($i = 0; $i < 3; $i++) {
    $v = $o->judge($i, 'fast', "attempt {$i}");
    $seen[] = $v['satisfied'];
    if ($v['satisfied']) { break; }
}
$best = $o->best();
echo json_encode([
    'runs' => count($seen), 'first' => $seen[0],
    'best_iteration' => $best['iteration'] + 1, 'best_text' => $best['final_text'],
    'gate_run_id' => $best['gate_run_id'],
]);
""")
    assert got["first"] is True
    assert got["runs"] == 1, "the loop kept judging after the gate set had passed"
    assert got["best_iteration"] == 1
    assert got["best_text"] == "attempt 0"
    assert got["gate_run_id"] == "v-1", "the reported iteration carries no verdict identity"


def test_an_unbeaten_peak_gets_one_more_iteration_then_stops(tmp_path):
    """fail -> fail. The first is the peak; the second does not beat it, and
    the loop is told to stop rather than pay for a third."""
    got = _drive(tmp_path, """
$o = oracle([[1, 'fail'], [1, 'fail'], [1, 'fail']]);
$continued = [];
for ($i = 0; $i < 3; $i++) {
    $o->judge($i, 'fast', "attempt {$i}");
    $continued[] = $o->shouldContinue();
}
$best = $o->best();
echo json_encode([
    'continued' => $continued,
    'best_iteration' => $best['iteration'] + 1,
    'best_text' => $best['final_text'],
    'best_satisfied' => $best['satisfied'],
]);
""")
    assert got["continued"][0] is True, "the first iteration IS the peak; one more is allowed"
    assert got["continued"][1] is False, (
        "the loop would keep spending past an unbeaten peak — the shape "
        "arXiv:2607.25886 measures ending below peak 78.26% of the time"
    )
    assert got["best_iteration"] == 1
    assert got["best_text"] == "attempt 0"
    assert got["best_satisfied"] is False, "a peak is not a pass"


def test_an_improving_run_is_not_cut_off(tmp_path):
    """The control for the rule above: indeterminate -> fail IS an improvement,
    so the budget is not spent stopping a run that is getting better."""
    got = _drive(tmp_path, """
$o = oracle([[2, 'indeterminate'], [1, 'fail'], [1, 'fail']]);
$continued = [];
for ($i = 0; $i < 3; $i++) { $o->judge($i, 'fast', "attempt {$i}"); $continued[] = $o->shouldContinue(); }
$best = $o->best();
echo json_encode(['continued' => $continued, 'best_iteration' => $best['iteration'] + 1]);
""")
    assert got["continued"][0] is True
    assert got["continued"][1] is True, "an improving iteration was treated as a plateau"
    assert got["best_iteration"] == 2, "the better iteration is not the one reported"


def test_indeterminate_is_not_satisfaction(tmp_path):
    """Absence of a measurement never launders into success."""
    got = _drive(tmp_path, """
$o = oracle([[2, 'indeterminate']]);
$v = $o->judge(0, 'fast', 'x');
echo json_encode(['satisfied' => $v['satisfied'], 'score' => $v['score'], 'detail' => $v['detail']]);
""")
    assert got["satisfied"] is False
    assert got["score"] == 0
    assert "indeterminate" in got["detail"]


def test_a_pass_without_a_verdict_uuid_is_not_satisfaction(tmp_path):
    """A gate run nobody can name is a gate run nobody can replay."""
    got = _drive(tmp_path, """
$o = new GateOracle('/nonexistent-repo', fn (array $argv) => [
    'exit' => 0, 'stdout' => '{"state":"done","verdict":{"result":"pass"}}', 'stderr' => '',
]);
$v = $o->judge(0, 'fast', 'x');
echo json_encode(['satisfied' => $v['satisfied'], 'id' => $v['gate_run_id']]);
""")
    assert got["id"] is None
    assert got["satisfied"] is False


def test_unreadable_client_output_is_not_satisfaction(tmp_path):
    """A crashed client that somehow exits 0 yields no verdict, so it is not a
    pass — and the failure text reaches the revision feedback."""
    got = _drive(tmp_path, """
$o = new GateOracle('/nonexistent-repo', fn (array $argv) => [
    'exit' => 0, 'stdout' => 'Traceback (most recent call last):', 'stderr' => 'boom',
]);
$v = $o->judge(0, 'fast', 'x');
echo json_encode(['satisfied' => $v['satisfied'], 'detail' => $v['detail']]);
""")
    assert got["satisfied"] is False
    assert "boom" in got["detail"], "the failure is not carried into the revision feedback"


def test_the_oracle_asks_the_engine_through_its_client(tmp_path):
    """DECISION 6, at the one place this class could break it: the argv is the
    CLI's, with the gate set as the only input that selects work."""
    got = _drive(tmp_path, """
$argv = null;
$o = oracle([[0, 'pass']], $argv);
$o->judge(0, 'live', 'x');
echo json_encode(['argv' => $argv]);
""")
    argv = got["argv"]
    assert argv[0].endswith("nos-loop"), f"the oracle spawns {argv[0]!r}, not the loop client"
    assert argv[1] == "judge"
    assert "--gate-set" in argv and argv[argv.index("--gate-set") + 1] == "live"
    assert "--wait" in argv and "--json" in argv
    assert "--proposal" not in argv, (
        "the oracle attaches its verdict to a proposal — an agent run is a "
        "baseline judgment, and attaching it would seal a verdict against "
        "someone else's change"
    )
