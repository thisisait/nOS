"""A judge that cannot run must not be reported as work that failed.

Estate doctrine: absence is UNKNOWN, never a verdict. When no gate set ever
reaches a real verdict (requirement absent → every judge skipped → set
INDETERMINATE), the session's outcome must be distinguishable from a genuine
red — `indeterminate`, not `needs_revision`. The first bound ceremony
(ea044f04, 2026-08-29) ended `outcome_needs_revision` on an environment
defect, and the agent was told its WORK had failed.

The mapping lives in GateOracle::outcome and is executed here through the real
class; the one-line wiring assert pins that Runner consumes it rather than
recomputing its own word.
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

PROBE = """<?php
require %(autoload)r;
use App\\AgentKit\\Outcome\\GateOracle;

function oracle(array $script): GateOracle {
    $i = 0;
    return new GateOracle('/nonexistent', function (array $argv) use ($script, &$i) {
        [$exit, $result] = $script[$i++];
        return ['exit' => $exit, 'stdout' => json_encode(['state' => 'done', 'verdict' => [
            'uuid' => 'v-' . $i, 'result' => $result, 'gate_set' => 'live',
            'tree_sha' => str_repeat('a', 40), 'evidence' => '{}',
        ]]), 'stderr' => ''];
    });
}

// Environment cannot judge: every verdict INDETERMINATE (score 0).
$env = oracle([[1, 'indeterminate'], [1, 'indeterminate']]);
$env->judge(0, 'live');
$env->judge(1, 'live');

// Real red: the work genuinely failed its gates.
$red = oracle([[1, 'fail'], [1, 'fail']]);
$red->judge(0, 'live');
$red->judge(1, 'live');

// Nothing judged at all (loop threw before the first verdict).
$blank = oracle([]);

echo json_encode([
    'env_peak'      => ['stopped' => $env->outcome(true), 'budget' => $env->outcome(false)],
    'red_peak'      => $red->outcome(true),
    'red_budget'    => $red->outcome(false),
    'blank'         => $blank->outcome(false),
]);
"""


def test_indeterminate_environment_is_not_needs_revision(tmp_path):
    probe = tmp_path / "probe.php"
    probe.write_text(PROBE % {"autoload": str(AUTOLOAD)})
    r = subprocess.run(["php", str(probe)], capture_output=True, text=True)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    got = json.loads(r.stdout)
    assert got["env_peak"] == {"stopped": "indeterminate", "budget": "indeterminate"}, (
        "an environment that could not judge was reported as failed work"
    )
    assert got["blank"] == "indeterminate"
    assert got["red_peak"] == "needs_revision"
    assert got["red_budget"] == "max_iterations_reached"


def test_the_runner_consumes_the_oracles_outcome():
    runner = (WING / "app" / "AgentKit" / "Runner.php").read_text()
    assert "$oracle->outcome(" in runner, (
        "Runner recomputes its own outcome word instead of asking the oracle "
        "— the indeterminate/needs_revision distinction is lost at the seam"
    )
