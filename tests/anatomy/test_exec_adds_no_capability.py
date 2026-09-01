"""`exec` is one argument wide, one route deep, and adds nothing.

The claim the whole design rests on: an agent can cause EXACTLY what it could
already cause with POST /api/v1/cortex/execute and its own token. That claim
survives only while the tool re-implements none of the three checks — KEAP
validate, CortexBindingGate, and the dispatch loop's separate `mutating` check.
A tool that grew a second opinion about any of them would be a fourth gate
nobody reviewed, which is how a capability arrives by accident.

So this gate does not read the docblock. It builds the real ExecTool over a
mock transport and looks at what it PUTS ON THE WIRE:

  1. one route, one method, and a body of exactly {source, commit:false} —
     no `commit:true` (a capability arriving as data), no `ast_binding`
     (freshness it does not hold), no `tenant` (someone else's).
  2. `confirm:true` is refused and NO request leaves at all — checked, never
     trusted. The refusal names no alternative.
  3. two different wrong operands produce byte-identical output apart from the
     validator's own echo: no operand-keyed branching, no repair path, no
     candidate list bolted on top of KEAP's namespace-constant refusal.
  4. a 404 does not print the route table — the sibling tool's behaviour, and
     the exact enumeration this surface refuses. This is why ExecTool does not
     inherit McpWingTool::execute().
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
TOOL = WING / "app/AgentKit/Tools/ExecTool.php"
AUTOLOAD = WING / "vendor/autoload.php"

PROBE = r"""
require __DIR__ . '/vendor/autoload.php';

// vendor/ gives us Guzzle; App\ must come from THIS checkout's app/, not from
// whatever tree composer's baked absolute paths point at. The repo is not the
// running system, and a gate that silently tested the deployed classes would
// pass while this one's edits were never loaded.
spl_autoload_register(static function (string $class): void {
    if (str_starts_with($class, 'App\\')) {
        $f = __DIR__ . '/app/' . str_replace('\\', '/', substr($class, 4)) . '.php';
        if (is_file($f)) {
            require $f;
        }
    }
}, true, true);

use App\AgentKit\Tools\ExecTool;
use App\AgentKit\Tools\ToolContext;
use GuzzleHttp\Client;
use GuzzleHttp\Handler\MockHandler;
use GuzzleHttp\HandlerStack;
use GuzzleHttp\Middleware;
use GuzzleHttp\Psr7\Response;

$ctx = new ToolContext('sess-1', 'th', 'tr', 'sp', 'agent:jeff', 'tu');

/** Build a tool whose transport answers with $responses and records requests. */
$sent = [];
$make = function (array $responses) use (&$sent): ExecTool {
    $stack = HandlerStack::create(new MockHandler($responses));
    $stack->push(Middleware::history($sent));
    return new ExecTool(new Client(['handler' => $stack]), 'test-bearer');
};

$out = ['id' => null, 'scopes' => null];

// --- a validate refusal, twice, with two different bad operands -------------
$refusal = fn(string $op) => new Response(200, ['Content-Type' => 'application/json'],
    json_encode(['valid' => false, 'ast' => null, 'dispatched' => false,
        'errors' => [['code' => 'unknown_operand', 'detail' => 'docs', 'operand' => $op]]]));

// The last two are spares: a confirm:true that escapes to the wire must be
// caught by the `requests_made` assertion, not by the mock queue running dry —
// an exhausted queue is a red gate for the wrong reason, and a reader chasing
// it learns nothing about the widening it was supposed to catch.
$tool = $make([
    $refusal('tax:zzz'), $refusal('tax:qqqqqqq'), new Response(404, [], 'not found'),
    new Response(200, [], '{}'), new Response(200, [], '{}'),
]);
$out['id'] = $tool->id();
$out['scopes'] = $tool->requiredScopes();

$a = $tool->execute(['chain' => 'get tax:zzz'], $ctx);
$b = $tool->execute(['chain' => 'get tax:qqqqqqq'], $ctx);
$out['refusal_a'] = ['content' => $a->content, 'error' => $a->isError, 'sent' => $refusal('tax:zzz')->getBody()->__toString()];
$out['refusal_b'] = ['content' => $b->content, 'error' => $b->isError, 'sent' => $refusal('tax:qqqqqqq')->getBody()->__toString()];

$nf = $tool->execute(['chain' => 'get tax:x'], $ctx);
$out['not_found'] = ['content' => $nf->content, 'error' => $nf->isError];

// --- confirm:true, with a transport that would BLOW UP if reached ----------
$before = count($sent);
$confirmed = $tool->execute(['chain' => 'get tax:x', 'confirm' => true], $ctx);
$out['confirm'] = [
    'content' => $confirmed->content,
    'error' => $confirmed->isError,
    'requests_made' => count($sent) - $before,
];

$empty = $tool->execute(['chain' => '   '], $ctx);
$out['empty'] = ['content' => $empty->content, 'error' => $empty->isError, 'requests' => count($sent) - $before];

$out['wire'] = array_map(static function (array $tx): array {
    $r = $tx['request'];
    return [
        'method' => $r->getMethod(),
        'path' => $r->getUri()->getPath(),
        'host' => $r->getUri()->getHost(),
        'body' => (string) $r->getBody(),
    ];
}, $sent);

echo json_encode($out);
"""


@pytest.fixture(scope="module")
def probe() -> dict:
    if not AUTOLOAD.is_file():
        pytest.skip("wing vendor/autoload.php missing — run `composer install` in files/anatomy/wing")
    p = WING / "exec-tool-probe.php"
    p.write_text("<?php\n" + PROBE, encoding="utf-8")
    try:
        out = subprocess.run(
            ["php", p.name], cwd=WING, capture_output=True, text=True, timeout=120,
            env={**os.environ, "NOS_AGENT_WING_TOKEN": "test-bearer"},
        )
    finally:
        p.unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_it_sends_one_route_and_a_two_key_body(probe: dict) -> None:
    assert probe["id"] == "exec"
    assert probe["wire"], "the tool made no request at all"
    for tx in probe["wire"]:
        assert tx["method"] == "POST"
        assert tx["path"] == "/api/v1/cortex/execute", (
            f"exec reached {tx['path']}. It has exactly one route; a second one is "
            "a second set of gates nobody reviewed."
        )
        assert tx["host"] == "127.0.0.1"
        body = json.loads(tx["body"])
        assert set(body) == {"source", "commit"}, (
            f"exec sent {sorted(body)}. `ast_binding` is freshness it does not hold, "
            "`tenant` is someone else's, and anything else is surface the presenter "
            "did not ask for."
        )
        assert body["commit"] is False, (
            "exec sent commit:true. A mutating grant arriving in the tool's own "
            "request body is a capability added by data."
        )


def test_confirm_is_checked_and_never_reaches_the_wire(probe: dict) -> None:
    c = probe["confirm"]
    assert c["error"] is True
    assert c["requests_made"] == 0, (
        "confirm:true produced an HTTP call. It is an assertion of intent, not a "
        "grant; asserting it must end with strictly less reach, never more."
    )
    assert "/api/" not in c["content"] and "cortex/execute" not in c["content"]
    assert probe["empty"]["error"] is True and probe["empty"]["requests"] == 0


def test_the_refusal_is_forwarded_verbatim(probe: dict) -> None:
    """The strong form of "does not enumerate": nothing is appended AT ALL.

    A first cut compared the two refusals modulo a `tax:\\w+` normaliser and a
    planted `"Did you mean: " . $chain` walked straight through it — the
    normaliser erased the very echo the test existed to catch. Comparing the
    tool's output against the validator's own bytes has no such blind spot:
    a repair path, a candidate list, or a hint of any shape changes the string.
    """
    for key in ("refusal_a", "refusal_b"):
        r = probe[key]
        assert r["content"] == "HTTP 200\n" + r["sent"], (
            "exec added something to the validator's answer. KEAP already refuses "
            "unknown_operand namespace-constant (261/261 identical); anything this "
            "tool appends rebuilds the oracle one layer up, at the tool boundary "
            "instead of the language boundary."
        )
    assert "unknown_operand" in probe["refusal_a"]["content"]

    # And the residue after removing each operand must still match, so a hint
    # keyed on WHICH operand failed cannot hide inside a verbatim-looking body.
    a = probe["refusal_a"]["content"].replace("tax:zzz", "OP")
    b = probe["refusal_b"]["content"].replace("tax:qqqqqqq", "OP")
    assert a == b


def test_a_404_does_not_print_the_route_table(probe: dict) -> None:
    content = probe["not_found"]["content"]
    assert probe["not_found"]["error"] is True
    assert "/api/v1/" not in content, (
        "exec appended routes to a 404 — McpWingTool::execute()'s behaviour, "
        "inherited by accident. An error may not list what would have worked."
    )


def test_it_is_registered_where_tools_are_registered(probe: dict) -> None:
    assert probe["scopes"] == ["mcp.tool_use", "cortex.exec"], (
        f"exec grants {probe['scopes']} — the cortex axis is the token's own, "
        "not a new one invented at the tool boundary."
    )
    neon = (WING / "app/config/common.neon").read_text(encoding="utf-8")
    assert "register(@App\\AgentKit\\Tools\\ExecTool)" in neon, (
        "a tool the registry never registers throws at session start for every "
        "agent that declares it"
    )
    schema = (REPO / "state/schema/agent.schema.yaml").read_text(encoding="utf-8")
    assert re.search(r"^\s+- exec\s*$", schema, re.M), (
        "no agent.yml can declare an id the schema rejects"
    )


def test_it_does_not_inherit_the_enumerating_execute() -> None:
    """The 404 probe above proves today's behaviour; this proves the structure.

    A first cut had ExecTool EXTEND McpWingTool for the transport, which forced
    that base's `$bearerToken` from private to protected — a class opened up for
    one caller — and left the enumerating `execute()` one missing override away
    from being inherited. Standing alone costs fifteen lines of constructor and
    removes the question.
    """
    src = TOOL.read_text(encoding="utf-8")
    assert re.search(r"final class ExecTool implements ToolInterface", src), (
        "ExecTool extends something again. McpWingTool::execute() appends the "
        "live route table on 404, which is the enumeration this surface refuses."
    )
    assert re.search(r"public function execute\(", src)
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", src, flags=re.S)
    assert "parent::execute" not in code
    base = (WING / "app/AgentKit/Tools/McpWingTool.php").read_text(encoding="utf-8")
    assert "private string $bearerToken;" in base, (
        "McpWingTool's bearer was widened to protected — the widening only ever "
        "existed to let ExecTool borrow it, and ExecTool no longer does."
    )
