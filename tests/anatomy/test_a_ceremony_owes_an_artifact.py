"""A ceremony that filed nothing is not satisfied, whatever the gates say.

MEASURED 2026-08-29, session `53de6409-ffc2-415a-b4e6-d3c3cff7151e`. The
surveyor's gate set passed for real — `nos-smoke` exit 0, `cortex-corpus-diff`
"agrees is true", a genuine `gate_run_id` on the iteration — and the run was
recorded `outcome_satisfied` having posted nothing at all. Zero
`conductor_report` events, five GETs, no POST.

Nothing was broken. The gate set judges the TREE: one judge says the estate is
healthy, the other that the corpus agrees. Neither has an opinion about whether
this agent did its own work. Moving satisfaction from the model's word to a gate
run — which is what the day before had bought — closed the forgery and left the
question open: the oracle now certifies something real, but not the thing the
ceremony was for.

So an agent may declare `outcomes.deliverable: {event: <type>}`, and the absence
of that artifact unmakes satisfaction. The check is a READER: it asks the events
table whether a row of that type exists keyed to THIS session. It never writes,
and it is not consulted at all for a ceremony whose deliverable is the tree.

What this file pins, by EXECUTING the real class rather than reading it:
gates-pass + artifact-present is satisfied; gates-pass + artifact-absent is not,
and says why in a way a revision can act on.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
AGENTS = REPO / "files/anatomy/agents"
AUTOLOAD = WING / "vendor/autoload.php"

PROBE = r"""
require __DIR__ . '/vendor/autoload.php';

use App\AgentKit\Outcome\GateOracle;

// A gate set that PASSES: exit 0, sealed verdict says pass, and it is named.
$pass = static fn (array $argv): array => [
    'exit' => 0,
    'stdout' => json_encode(['verdict' => ['result' => 'pass', 'uuid' => 'gr-1']]),
    'stderr' => '',
];

$out = [];
foreach ([true, false] as $present) {
    $oracle = new GateOracle('/tmp', $pass, static fn (): bool => $present);
    $v = $oracle->judge(0, 'live', 'some prose');
    $out[$present ? 'artifact_present' : 'artifact_absent'] = [
        'satisfied' => $v['satisfied'],
        'gate_run_id' => $v['gate_run_id'],
        'detail' => $v['detail'],
    ];
}

// And the ceremony that declares no deliverable is untouched: no reader, no
// extra condition, the three original things still decide.
$oracle = new GateOracle('/tmp', $pass, null);
$out['no_declaration'] = ['satisfied' => $oracle->judge(0, 'live', '')['satisfied']];

echo json_encode($out);
"""

pytestmark = pytest.mark.skipif(
    not AUTOLOAD.is_file(),
    reason="php binary or wing vendor/autoload.php missing — run `composer "
           "install` in files/anatomy/wing",
)


def _probe() -> dict:
    p = WING / "deliverable-probe.php"
    p.write_text("<?php\n" + PROBE, encoding="utf-8")
    try:
        out = subprocess.run(["php", p.name], cwd=WING, capture_output=True,
                             text=True, timeout=60)
    finally:
        p.unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_a_passing_gate_set_with_the_artifact_is_satisfied() -> None:
    """The control. A check that only ever refuses is not a check."""
    got = _probe()["artifact_present"]
    assert got["satisfied"] is True
    assert got["gate_run_id"] == "gr-1"


def test_a_passing_gate_set_without_the_artifact_is_not() -> None:
    got = _probe()["artifact_absent"]
    assert got["satisfied"] is False, (
        "the gates passed and the ceremony filed nothing, and the run was still "
        "satisfied — this is 53de6409 exactly"
    )
    assert "filed no deliverable" in got["detail"], (
        "the revision is told the run failed without being told what it owes; "
        "an agent cannot act on that and will revise blind"
    )


def test_a_ceremony_that_declares_nothing_is_unchanged() -> None:
    """The reader is not consulted where the deliverable IS the tree."""
    assert _probe()["no_declaration"]["satisfied"] is True


def test_the_prose_ceremonies_declare_their_artifact() -> None:
    """Surveyor, conductor and librarian all report by filing an event. If one
    of them stops declaring it, satisfaction quietly goes back to meaning
    'the tree was fine while this ran'."""
    missing = []
    for d in sorted(AGENTS.iterdir()):
        f = d / "agent.yml"
        if not f.is_file():
            continue
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        outcomes = doc.get("outcomes") or {}
        if not outcomes.get("gateset"):
            continue          # no outcome loop; nothing to certify
        if d.name in {"surveyor", "conductor", "librarian"} and not outcomes.get("deliverable"):
            missing.append(d.name)
    assert not missing, f"prose ceremonies with no declared deliverable: {missing}"


def test_the_loader_refuses_a_malformed_declaration(tmp_path: Path) -> None:
    """A typo must be a load error, not a ceremony that can never be satisfied
    and never says why."""
    probe = WING / "loader-probe.php"
    probe.write_text("<?php\n" + r"""
require __DIR__ . '/vendor/autoload.php';
use App\AgentKit\AgentLoader;
$dir = sys_get_temp_dir() . '/nos-agent-' . bin2hex(random_bytes(4));
mkdir($dir . '/broken', 0700, true);
file_put_contents($dir . '/broken/agent.yml', "name: broken\nversion: 1\ndescription: d\n"
    . "model:\n  primary: anthropic-claude-opus-4-7\n"
    . "audit:\n  capability_scopes: [mcp.tool_use]\n  pii_classification: none\n"
    . "outcomes:\n  gateset: live\n  deliverable: conductor_report\n");
$loader = new AgentLoader($dir);
try { $loader->load('broken'); echo json_encode(['refused' => false]); }
catch (\Throwable $e) { echo json_encode(['refused' => true, 'why' => $e->getMessage()]); }
""", encoding="utf-8")
    try:
        # NOS_REPO_ROOT or the loader refuses one step earlier, on the gate-set
        # membership check, and never reaches the deliverable.
        out = subprocess.run(["php", probe.name], cwd=WING, capture_output=True,
                             text=True, timeout=60,
                             env={**os.environ, "NOS_REPO_ROOT": str(REPO)})
    finally:
        probe.unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["refused"] is True, "a bare string deliverable loaded happily"
    assert "deliverable" in got["why"]
