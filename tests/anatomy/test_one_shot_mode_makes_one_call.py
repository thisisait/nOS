"""Anatomy gate — `mode: one_shot` makes ONE model call, and the verdict is a
reader's.

The ops plane (nos-ops) measures small local models against a labelled task
family. Two things have to be true or the measurement measures the harness:

  * exactly one send() per run — no tool round trip, no retry, no outcome
    iteration. A model that answers with a `tool_use` stop reason must NOT
    pull a second call out of the runtime;
  * a chain that does not satisfy the agent's declared schema records
    `failed`. Not `satisfied`, not "no verdict" — the word `satisfied`
    belongs to a gate run (test_satisfaction_is_written_by_a_gate_run.py)
    and must not appear anywhere in a one_shot record.

Executed, not grepped: the stub client counts its own invocations and the
loader loads agent.yml files written to disk here. A source-reading version
of this gate would pass against a runtime that loops.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import textwrap

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files" / "anatomy" / "wing"
KIT = WING / "app" / "AgentKit"
AUTOLOAD = WING / "vendor" / "autoload.php"
RUNNER = KIT / "Runner.php"

pytestmark = [
    pytest.mark.skipif(shutil.which("php") is None, reason="php not installed"),
    pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor tree not installed"),
]

PRELUDE = f"""
require '{AUTOLOAD}';
require '{KIT}/Agent.php';
require '{KIT}/AgentLoader.php';
require '{KIT}/OneShot.php';
require '{KIT}/LLMClient/LLMResponse.php';
require '{KIT}/LLMClient/Message.php';
require '{KIT}/LLMClient/ToolSchema.php';
require '{KIT}/LLMClient/LLMClientInterface.php';

use App\\AgentKit\\Agent;
use App\\AgentKit\\OneShot;
use App\\AgentKit\\LLMClient\\LLMResponse;

/** Counts what it is asked to do. That count is the measurement. */
final class CountingStub implements App\\AgentKit\\LLMClient\\LLMClientInterface
{{
    public int $calls = 0;
    public array $toolsSeen = [];
    public function __construct(
        private string $stopReason,
        private array $blocks,
    ) {{}}
    public function identifier(): string {{ return 'openclaw-stub-1b'; }}
    public function send(string $s, array $m, array $tools = [], int $max = 4096): LLMResponse
    {{
        $this->calls++;
        $this->toolsSeen = $tools;
        return new LLMResponse($this->stopReason, $this->blocks, 11, 7);
    }}
}}

function shotAgent(array $schema): Agent
{{
    return new Agent(
        name: 'ops-probe', version: 1, description: 'one shot probe agent',
        modelPrimaryUri: 'openclaw-stub-1b', modelFallbackUri: null,
        modelGraderUri: null, systemPrompt: 'extract', tools: [],
        rubric: null, maxIterations: 3, capabilityScopes: ['llm.call'],
        piiClassification: 'none', requiredCredentials: [], subscriptions: [],
        metadata: [], sourceDir: '/tmp', mode: 'one_shot', oneShotSchema: $schema,
    );
}}

const SCHEMA = [
    'type' => 'object',
    'required' => ['invoice_no', 'total'],
    'properties' => [
        'invoice_no' => ['type' => 'string'],
        'total' => ['type' => 'number'],
        'currency' => ['type' => 'string', 'enum' => ['EUR', 'CZK']],
    ],
];

function text(string $t): array {{ return [['type' => 'text', 'text' => $t]]; }}
"""


def php(script: str, tmp_path: pathlib.Path) -> dict:
    f = tmp_path / "probe.php"
    f.write_text("<?php\n" + PRELUDE + textwrap.dedent(script) + "\n", encoding="utf-8")
    out = subprocess.run(
        ["php", "-d", "error_reporting=E_ALL", str(f)],
        capture_output=True, text=True, timeout=60,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
             "NOS_REPO_ROOT": str(REPO)},
    )
    assert out.returncode == 0, f"probe failed:\n{out.stdout}\n{out.stderr}"
    return json.loads(out.stdout)


def test_one_shot_makes_exactly_one_call(tmp_path):
    got = php("""
        $c = new CountingStub('end_turn', text('{"invoice_no":"A-1","total":42.5,"currency":"EUR"}'));
        $r = OneShot::run($c, shotAgent(SCHEMA), 'extract this');
        echo json_encode(['calls' => $c->calls, 'tools' => $c->toolsSeen, 'r' => $r]);
    """, tmp_path)
    assert got["calls"] == 1, f"one_shot made {got['calls']} model calls, not one"
    assert got["tools"] == [], "one_shot offered tools — an invitation to a second call"
    assert got["r"]["verdict"] == "valid"
    assert got["r"]["chain"]["invoice_no"] == "A-1"


def test_a_tool_use_stop_reason_does_not_start_a_loop(tmp_path):
    """The loop-shaped answer is the one that would drag a second call out of
    a runtime that still had a loop in it."""
    got = php("""
        $c = new CountingStub('tool_use', [['type' => 'tool_use', 'id' => 't1',
             'name' => 'bash-read-only', 'input' => ['cmd' => 'ls']]]);
        $r = OneShot::run($c, shotAgent(SCHEMA), 'extract this');
        echo json_encode(['calls' => $c->calls, 'r' => $r]);
    """, tmp_path)
    assert got["calls"] == 1, "a tool_use answer bought a second model call"
    assert got["r"]["verdict"] == "failed"


@pytest.mark.parametrize("emitted,why", [
    ('{"invoice_no":"A-1"}', "required key missing"),
    ('{"invoice_no":7,"total":42.5}', "wrong scalar type"),
    ('{"invoice_no":"A-1","total":42.5,"currency":"USD"}', "value outside the enum"),
    ('here is your answer, boss', "not JSON at all"),
    ('[1,2,3]', "a list where an object is declared"),
])
def test_a_schema_invalid_chain_records_failed_never_satisfied(tmp_path, emitted, why):
    got = php(f"""
        $c = new CountingStub('end_turn', text({json.dumps(emitted)}));
        $r = OneShot::run($c, shotAgent(SCHEMA), 'extract this');
        echo json_encode(['calls' => $c->calls, 'r' => $r]);
    """, tmp_path)
    assert got["calls"] == 1
    assert got["r"]["verdict"] == "failed", f"{why} was waved through"
    assert got["r"]["chain"] is None, "a refused chain was still handed on"
    assert got["r"]["error"], "a failure with no reason recorded"
    assert "satisfied" not in json.dumps(got["r"]).lower(), (
        "a one_shot record used the word 'satisfied' — that verdict is a gate "
        "run's to write, not a schema check's"
    )


def test_a_fenced_chain_is_still_read(tmp_path):
    """Small models fence their JSON. Measuring fence discipline is not the
    point — the control that the stripper does not also swallow a bad chain is
    the parametrised failure set above."""
    got = php("""
        $c = new CountingStub('end_turn', text("sure!\\n```json\\n{\\"invoice_no\\":\\"A-2\\",\\"total\\":9}\\n```"));
        $r = OneShot::run($c, shotAgent(SCHEMA), 'x');
        echo json_encode($r);
    """, tmp_path)
    assert got["verdict"] == "valid" and got["chain"]["invoice_no"] == "A-2"


# --- the loader half: a one_shot agent cannot declare a loop's apparatus ----

AGENT_BASE = """
name: ops-probe
version: 1
description: a one_shot probe agent for the ops plane harness
model:
  primary: openclaw-stub-1b
audit:
  capability_scopes: [llm.call]
  pii_classification: none
"""


def _write_agent(root: pathlib.Path, extra: str, schema: str | None = '{"type":"object"}'):
    d = root / "ops-probe"
    d.mkdir(parents=True, exist_ok=True)
    (d / "agent.yml").write_text(AGENT_BASE + extra, encoding="utf-8")
    if schema is not None:
        (d / "chain.schema.json").write_text(schema, encoding="utf-8")
    return root


def _load(root: pathlib.Path, tmp_path: pathlib.Path) -> dict:
    f = tmp_path / "load.php"
    f.write_text("<?php\n" + PRELUDE + textwrap.dedent(f"""
        $l = new App\\AgentKit\\AgentLoader('{root}');
        try {{
            $a = $l->load('ops-probe');
            echo json_encode(['ok' => true, 'mode' => $a->mode, 'schema' => $a->oneShotSchema]);
        }} catch (App\\AgentKit\\AgentLoadException $e) {{
            echo json_encode(['ok' => false, 'error' => $e->getMessage()]);
        }}
    """), encoding="utf-8")
    out = subprocess.run(
        ["php", str(f)], capture_output=True, text=True, timeout=60,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
             "NOS_REPO_ROOT": str(REPO)},
    )
    assert out.returncode == 0, f"{out.stdout}\n{out.stderr}"
    return json.loads(out.stdout)


def test_the_loader_accepts_a_plain_one_shot_agent(tmp_path):
    """Positive control — the refusals below must refuse the contradiction,
    not the mode."""
    root = _write_agent(tmp_path / "agents", "mode: one_shot\none_shot:\n  schema_path: chain.schema.json\n")
    got = _load(root, tmp_path)
    assert got["ok"], got
    assert got["mode"] == "one_shot"
    assert got["schema"] == {"type": "object"}


@pytest.mark.parametrize("extra,schema,needle", [
    ("mode: one_shot\none_shot:\n  schema_path: chain.schema.json\ntools:\n  - id: bash-read-only\n",
     '{"type":"object"}', "tool-use loop"),
    ("mode: one_shot\none_shot:\n  schema_path: chain.schema.json\noutcomes:\n  gateset: fast\n",
     '{"type":"object"}', "outcome loop"),
    ("mode: one_shot\n", '{"type":"object"}', "schema_path"),
    ("mode: one_shot\none_shot:\n  schema_path: chain.schema.json\n", None, "missing"),
    ("mode: one_shot\none_shot:\n  schema_path: chain.schema.json\n", "[]", "non-empty JSON object"),
    ("one_shot:\n  schema_path: chain.schema.json\n", '{"type":"object"}', "without mode"),
    ("mode: two_shot\n", '{"type":"object"}', "must be loop|one_shot"),
])
def test_the_loader_refuses_a_one_shot_agent_that_declares_a_loop(tmp_path, extra, schema, needle):
    root = _write_agent(tmp_path / "agents", extra, schema)
    got = _load(root, tmp_path)
    assert not got["ok"], f"loaded a contradiction: {extra!r}"
    assert needle in got["error"], got["error"]


def test_the_runner_branches_on_one_shot_before_the_loops():
    """Secondary, structural: the mode branch must come FIRST. Behind
    hasOutcome() it would be unreachable for any agent with an outcome — and
    the loader's refusal is what makes that combination impossible to test
    behaviourally here."""
    src = RUNNER.read_text(encoding="utf-8")
    shot = src.find("isOneShot()")
    outcome = src.find("$agent->hasOutcome()", src.find("try {"))
    assert shot != -1, "Runner no longer branches on one_shot mode"
    assert shot < outcome, "the one_shot branch sits behind a loop branch"
