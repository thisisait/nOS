"""The oracle's feedback must survive the sealed verdict's actual shape.

`ledger.seal_verdict` stores `evidence` as a canonical-JSON STRING; GateOracle
accepted only an array, so every real failing ceremony's feedback ended at the
colon — "gate set `live` returned fail on tree a4cb13a5477e (exit 1):" — and
the agent revised twice, blind (session ea044f04, 2026-08-29). The earlier
oracle gate stubbed evidence as an array, which is why it stayed green over a
broken production path: the fixture did not match the artifact it stood for.

Driven through the real class with only the subprocess replaced. The stub
hands back evidence in BOTH shapes; both must reach the detail.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
AUTOLOAD = REPO / "files" / "anatomy" / "wing" / "vendor" / "autoload.php"

pytestmark = [
    pytest.mark.skipif(shutil.which("php") is None, reason="php not on PATH"),
    pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor tree not installed"),
]

REASON = ("nos-smoke: exit 1 in fail_exit; "
          "cortex-corpus-diff: requirement(s) absent: keap_token_ro — not run")

PROBE = """<?php
require %(autoload)r;
use App\\AgentKit\\Outcome\\GateOracle;

function verdict($evidence) {
    return new GateOracle('/nonexistent', function (array $argv) use ($evidence) {
        return ['exit' => 1, 'stdout' => json_encode(['state' => 'done', 'verdict' => [
            'uuid' => 'v-1', 'result' => 'fail', 'gate_set' => 'live',
            'tree_sha' => str_repeat('a', 40), 'evidence' => $evidence,
        ]]), 'stderr' => ''];
    });
}
$reason = %(reason)r;
echo json_encode([
    'sealed_string' => verdict(json_encode(['reason' => $reason]))->judge(0, 'live')['detail'],
    'array'         => verdict(['reason' => $reason])->judge(0, 'live')['detail'],
    'garbage'       => verdict('{not json')->judge(0, 'live')['detail'],
]);
"""


def test_feedback_carries_the_judges_reasons_in_both_evidence_shapes(tmp_path):
    probe = tmp_path / "probe.php"
    probe.write_text(PROBE % {"autoload": str(AUTOLOAD), "reason": REASON})
    r = subprocess.run(["php", str(probe)], capture_output=True, text=True)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    got = json.loads(r.stdout)
    assert REASON in got["sealed_string"], (
        "the sealed (string) evidence shape lost the reason — the agent "
        "revises blind again"
    )
    assert REASON in got["array"]
    # Undecodable evidence degrades to the old fallback, never crashes.
    assert got["garbage"].startswith("gate set `live` returned fail")
