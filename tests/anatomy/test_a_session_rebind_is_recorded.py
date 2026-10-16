"""A session's model changing is its own recorded event: agent_session_rebind.

Ruling 2026-10-16 (roadmap row agent-session-rebind-event). Before it, the Iris
picker logged the change as an agent_tool_result with tool "model", and Wing's
fallback logged only agent_model_fallback, so no reader could ask one question
of both. Payload: {from_model_uri, to_model_uri, by, reason}, by in
person | fallback | posture. Bone/Wing parity with the contract is held by
test_event_types_match_the_contract.py; this file holds the contract to the
type, the other mirrors, and Wing's run-time switch, driven for real: the
real Runner over stub clients, fallback and back, each switch one event and
the first request it answers one line.
"""

from __future__ import annotations

import pathlib
import json
import re
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TYPE = "agent_session_rebind"
PAYLOAD = ("from_model_uri", "to_model_uri", "by", "reason")


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_the_contract_lists_the_type():
    doc = yaml.safe_load(_read("files/anatomy/contracts/event-types.yml"))
    assert TYPE in doc["types"]


def test_the_thalamus_ledger_can_write_it():
    src = _read("files/anatomy/thalamus/thalamus/src/ledger.rs")
    assert re.search(r'Kind::SessionRebind\s*=>\s*"agent_session_rebind"', src)


def test_an_agent_can_subscribe_to_it():
    schema = yaml.safe_load(_read("state/schema/agent.schema.yaml"))
    enum = schema["properties"]["subscribe"]["items"]["properties"]["event_type"]["enum"]
    assert TYPE in enum


HARNESS = r"""<?php
namespace App\Model { final class EventRepository { public array $rows = [];
    public function insert(array $p): int { $this->rows[] = $p; return 1; } } }
namespace App\AgentKit\LLMClient { final class Factory { public function __construct(public array $c) {}
    public function fromUri(string $u, $b = null): LLMClientInterface { return $this->c[$u]; } } }
namespace {
use App\AgentKit\LLMClient\{LLMClientInterface, LLMPermanentError, LLMResponse};
spl_autoload_register(function ($c) { $f = WING . '/app/' . str_replace('\\', '/', substr($c, 4)) . '.php';
    if (str_starts_with($c, 'App\\') && is_file($f)) require $f; });
final class Stub implements LLMClientInterface {
    public array $plan = []; public array $heard = [];
    public function __construct(private string $id) {}
    public function identifier(): string { return $this->id; }
    public function send(string $s, array $m, array $t = [], int $x = 4096): LLMResponse {
        if (array_shift($this->plan) === 'fail') throw new LLMPermanentError('down');
        $this->heard[] = $s; return new LLMResponse('end_turn', [], 1, 1);
    }
}
$a = new Stub('a-primary'); $b = new Stub('b-fallback');
$agent = new App\AgentKit\Agent(name: 'x', version: 1, description: '', modelPrimaryUri: 'a-primary',
    modelFallbackUri: 'b-fallback', modelGraderUri: null, systemPrompt: 'SYS', tools: [], rubric: null,
    maxIterations: 1, capabilityScopes: [], piiClassification: 'none', requiredCredentials: [],
    subscriptions: [], metadata: [], sourceDir: '');
$events = new App\Model\EventRepository();
$out = [];
foreach (json_decode($argv[1], true) as $plan) {
    $a->plan = $plan; $a->heard = []; $b->heard = [];
    $r = (new ReflectionClass(App\AgentKit\Runner::class))->newInstanceWithoutConstructor();
    (function () use ($events, $a, $b) {
        $this->audit = new App\AgentKit\Telemetry\AuditEmitter($events);
        $this->llmFactory = new App\AgentKit\LLMClient\Factory(['b-fallback' => $b]);
        $this->fallbackContext = ['session_uuid' => 's', 'primary' => 'a-primary'];
    })->call($r);
    $heard = [];
    foreach ($plan as $step) {
        $na = count($a->heard); $nb = count($b->heard);
        $step === 'synth'
            ? (function () use ($agent, $a) { $i = $o = 0; $this->synthesiseUnderCeiling($agent, $a, [], 's', 'x', 't', $i, $o); })->call($r)
            : (fn () => $this->callWithRetry($agent, $a, [], []))->call($r);
        $heard[] = count($a->heard) > $na ? end($a->heard) : end($b->heard);
    }
    $out[] = $heard;
}
$rebinds = array_values(array_filter($events->rows, fn ($e) => $e['type'] === 'agent_session_rebind'));
echo json_encode(['heard' => $out, 'rebinds' => array_map(fn ($e) => $e['result'], $rebinds)]);
}
"""


def _line(frm: str, to: str) -> str:
    return f"This session moved from {frm} to {to} (fallback); earlier turns were answered by {frm}."


@pytest.mark.skipif(shutil.which("php") is None, reason="php not installed on this runner")
def test_every_wing_switch_is_one_rebind_and_one_line(tmp_path):
    """A answers, B (fallback) answers twice, A again, then B: four switches.
    A session whose very first call falls back moves once and says no line:
    no earlier turn exists for the line to speak of."""
    script = tmp_path / "h.php"
    script.write_text(HARNESS.replace("WING", repr(str(REPO / "files/anatomy/wing"))))
    plans = [["ok", "fail", "fail", "ok", "fail"], ["fail"]]
    got = json.loads(subprocess.run(["php", str(script), json.dumps(plans)],
                                    capture_output=True, text=True, check=True).stdout)
    ab, ba = _line("a-primary", "b-fallback"), _line("b-fallback", "a-primary")
    assert got["heard"] == [["SYS", f"SYS\n\n{ab}", "SYS", f"SYS\n\n{ba}", f"SYS\n\n{ab}"], ["SYS"]]
    moves = [(e["from_model_uri"], e["to_model_uri"], e["by"]) for e in got["rebinds"]]
    assert moves == [("a-primary", "b-fallback", "fallback"), ("b-fallback", "a-primary", "fallback"),
                     ("a-primary", "b-fallback", "fallback"), ("a-primary", "b-fallback", "fallback")]
    assert all(e["reason"] for e in got["rebinds"])


@pytest.mark.skipif(shutil.which("php") is None, reason="php not installed on this runner")
def test_the_ceiling_wrap_up_is_a_switch_too(tmp_path):
    """The wrap-up at a ceiling goes to the primary client; after a fallback
    answered, that is a move back, recorded and said like any other."""
    script = tmp_path / "h.php"
    script.write_text(HARNESS.replace("WING", repr(str(REPO / "files/anatomy/wing"))))
    got = json.loads(subprocess.run(["php", str(script), json.dumps([["ok", "fail", "synth"]])],
                                    capture_output=True, text=True, check=True).stdout)
    assert got["heard"][0][2] == f"SYS\n\n{_line('b-fallback', 'a-primary')}"
    assert [(e["from_model_uri"], e["to_model_uri"]) for e in got["rebinds"]] == [
        ("a-primary", "b-fallback"), ("b-fallback", "a-primary")]
