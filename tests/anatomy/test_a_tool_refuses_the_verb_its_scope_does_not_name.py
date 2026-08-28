"""A tool must refuse the verb its scope does not name.

Until 2026-08-28 one tool — `mcp-wing` — carried GET and POST behind the single
scope `wing.read`. Every agent that could read the estate could therefore write
to it, and the registry's scope check could not tell the two apart because the
scope roster never mentioned a verb. `wing.read` was, in practice, `wing.*`.

The split is only real if the READ plane actually refuses a POST. That is a
claim about behaviour, so this gate does not grep: it instantiates every tool
class the DI container registers, hands each one a POST payload under a
read-only scope roster, and asserts `ToolResult::error`. A gate that read the
source could be satisfied by a comment; this one can only be satisfied by a
refusal that happens.

Three separate refusals are pinned, because they fail independently:

  1. the READ tool refuses POST at the verb (`refused_reason=verb_not_in_scope`);
  2. the WRITE tool refuses a route that is not in its grant
     (`refused_reason=route_not_granted`) — the grant is grandfathered from
     measured use in docs/plans/rsi-research/artifacts/wing-write-grants.json;
  3. `ToolRegistry::forAgent()` refuses to hand the write tool to an agent whose
     capability_scopes lack `wing.write` — the admission control that stops an
     agent holding the tool at all.

NEGATIVE CONTROL: the write tool must ACCEPT its granted route. Without that,
every assertion here is satisfiable by a tool that refuses everything, which is
the failure mode a security gate is most likely to ship green.

The bridge is the one the suite already uses for PHP-effect gates
(tests/anatomy/test_bound_agent_can_file_its_report.py): write a probe into the
wing tree, run it with the local `php` against the composer autoload, read JSON
off stdout. It SKIPS, naming what is missing, when php or vendor/ is absent.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
AUTOLOAD = WING / "vendor/autoload.php"
COMMON_NEON = WING / "app/config/common.neon"
GRANTS = REPO / "docs/plans/rsi-research/artifacts/wing-write-grants.json"

needs_php = pytest.mark.skipif(
    shutil.which("php") is None or not AUTOLOAD.is_file(),
    reason="needs the local `php` binary and files/anatomy/wing/vendor (composer install)",
)


def registered_tool_classes() -> list[str]:
    """The tools the container actually builds — read from the DI factory, not
    from a list in this file, so a tool added without a gate is still driven."""
    neon = COMMON_NEON.read_text(encoding="utf-8")
    factory = neon[neon.index("factory: App\\AgentKit\\Tools\\ToolRegistry"):]
    factory = factory[: factory.index("\n\t# Tools")]
    return re.findall(r"register\(@(App\\AgentKit\\Tools\\\w+)\)", factory)


# A roster that can read everything and write nothing. `wing.write` is the one
# scope deliberately absent — its absence is what the read plane must respect.
READ_ONLY_SCOPES = [
    "bash.read", "mcp.tool_use", "wing.read", "bone.read",
    "keap.read", "events.write", "audit.read", "inbox.ask",
]

_PROBE = r"""
require __DIR__ . '/vendor/autoload.php';

use App\AgentKit\Tools\ToolContext;
use App\AgentKit\Tools\ToolInterface;
use GuzzleHttp\Client;
use GuzzleHttp\Handler\MockHandler;
use GuzzleHttp\HandlerStack;
use GuzzleHttp\Psr7\Response;

[$_, $classesJson, $scopesJson] = $argv;

// Every mock request succeeds. A refusal in the output therefore came from the
// tool's own gate, never from a transport failure standing in for one.
function client(): Client {
    $responses = array_fill(0, 20, new Response(200, [], '{"ok":true}'));
    return new Client(['handler' => HandlerStack::create(new MockHandler($responses))]);
}

/** Build any registered tool without knowing its constructor. */
function build(string $class): ToolInterface {
    $ctor = (new ReflectionClass($class))->getConstructor();
    if ($ctor === null) {
        return new $class();
    }
    $args = [];
    foreach ($ctor->getParameters() as $p) {
        $type = $p->getType() instanceof ReflectionNamedType ? $p->getType()->getName() : null;
        if ($type === Client::class) {
            $args[] = client();
        } elseif ($p->isDefaultValueAvailable()) {
            $args[] = $p->getDefaultValue();
        } elseif ($p->allowsNull()) {
            $args[] = null;
        } elseif ($type === 'string') {
            $args[] = sys_get_temp_dir();
        } elseif ($type !== null && class_exists($type)) {
            // Repositories etc. — never touched on the refusal path.
            $args[] = (new ReflectionClass($type))->newInstanceWithoutConstructor();
        } else {
            throw new RuntimeException("cannot build $class: parameter {$p->getName()}");
        }
    }
    return new $class(...$args);
}

$ctx = new ToolContext('s-1', 'th-1', 'tr-1', 'sp-1', 'agent:probe', 'tu-1');
$scopes = json_decode($scopesJson, true);
$out = [];

foreach (json_decode($classesJson, true) as $class) {
    $row = ['class' => $class];
    try {
        $tool = build($class);
        $row['id'] = $tool->id();
        $row['scopes'] = $tool->requiredScopes();
        $row['within_read_only_roster'] = array_diff($tool->requiredScopes(), $scopes) === [];
        $r = $tool->execute(
            ['method' => 'POST', 'path' => '/api/v1/events', 'body' => ['ts' => 'x']],
            $ctx,
        );
        $row['post_is_error'] = $r->isError;
        $row['post_content'] = substr($r->content, 0, 200);
        $row['post_refused_reason'] = $r->metadata['refused_reason'] ?? null;
    } catch (Throwable $e) {
        $row['build_error'] = get_class($e) . ': ' . $e->getMessage();
    }
    $out[] = $row;
}

// The write plane, driven directly: an un-granted route, then a granted one.
$write = build(App\AgentKit\Tools\McpWingWriteTool::class);
$ungranted = $write->execute(
    ['method' => 'POST', 'path' => '/api/v1/pentest/findings', 'body' => []], $ctx);
$granted = $write->execute(
    ['method' => 'POST', 'path' => '/api/v1/events', 'body' => ['ts' => 'x']], $ctx);
$readVerb = $write->execute(['method' => 'GET', 'path' => '/api/v1/events'], $ctx);
$out2 = [
    'ungranted' => ['is_error' => $ungranted->isError,
                    'reason' => $ungranted->metadata['refused_reason'] ?? null,
                    'content' => substr($ungranted->content, 0, 200)],
    'granted'   => ['is_error' => $granted->isError, 'content' => substr($granted->content, 0, 80)],
    'read_verb' => ['is_error' => $readVerb->isError,
                    'reason' => $readVerb->metadata['refused_reason'] ?? null],
];

echo json_encode(['tools' => $out, 'write_plane' => $out2]);
"""

_REGISTRY_PROBE = r"""
require __DIR__ . '/vendor/autoload.php';

use App\AgentKit\Agent;
use App\AgentKit\ToolSpec;
use App\AgentKit\Tools\McpWingReadTool;
use App\AgentKit\Tools\McpWingWriteTool;
use App\AgentKit\Tools\ToolRegistry;
use GuzzleHttp\Client;

$registry = new ToolRegistry();
$registry->register(new McpWingReadTool(new Client()));
$registry->register(new McpWingWriteTool(new Client()));

$agent = function (array $tools, array $scopes): Agent {
    $a = (new ReflectionClass(Agent::class))->newInstanceWithoutConstructor();
    $r = new ReflectionObject($a);
    foreach ([
        'name' => 'probe', 'tools' => array_map(fn ($t) => new ToolSpec($t), $tools),
        'capabilityScopes' => $scopes,
    ] as $prop => $value) {
        $p = $r->getProperty($prop);
        $p->setValue($a, $value);
    }
    return $a;
};

$try = function (array $tools, array $scopes) use ($registry, $agent) {
    try {
        return ['loaded' => array_map(fn ($t) => $t->id(), $registry->forAgent($agent($tools, $scopes)))];
    } catch (Throwable $e) {
        return ['refused' => $e->getMessage()];
    }
};

echo json_encode([
    'read_roster_gets_write_tool' => $try(['mcp-wing-write'], ['mcp.tool_use', 'wing.read']),
    'read_roster_gets_read_tool'  => $try(['mcp-wing-read'],  ['mcp.tool_use', 'wing.read']),
    'write_roster_gets_write_tool' => $try(['mcp-wing-write'], ['mcp.tool_use', 'wing.write']),
]);
"""


def _run(src: str, name: str, *args: str) -> dict:
    probe = WING / name
    probe.write_text("<?php\n" + src, encoding="utf-8")
    try:
        out = subprocess.run(
            ["php", probe.name, *args], cwd=WING,
            capture_output=True, text=True, timeout=120,
        )
    finally:
        probe.unlink(missing_ok=True)
    assert out.returncode == 0, f"probe failed: {out.stderr}\n{out.stdout}"
    return json.loads(out.stdout)


@pytest.fixture(scope="module")
def driven() -> dict:
    classes = registered_tool_classes()
    return _run(
        _PROBE, "verb-scope-probe.php",
        json.dumps(classes), json.dumps(READ_ONLY_SCOPES),
    )


def test_the_registry_still_registers_the_two_planes():
    """Positive control. If the split were reverted, or a tool renamed, every
    behavioural assertion below would drive an empty or stale roster and pass
    for the wrong reason."""
    classes = registered_tool_classes()
    assert classes, "no tools parsed out of the ToolRegistry factory in common.neon"
    short = {c.rsplit("\\", 1)[1] for c in classes}
    assert {"McpWingReadTool", "McpWingWriteTool"} <= short, (
        f"the two Wing planes are not both registered: {sorted(short)}"
    )
    assert "McpWingTool" not in short, (
        "the un-split McpWingTool is registered again — it carried GET and POST "
        "behind one read scope, which is the defect this gate exists for"
    )


@needs_php
def test_every_registered_tool_is_buildable(driven: dict):
    """A tool this harness cannot construct is a tool it cannot drive, and an
    undriven tool is an untested one. Fail rather than silently skip it."""
    unbuilt = {r["class"]: r["build_error"] for r in driven["tools"] if "build_error" in r}
    assert not unbuilt, f"registered tools could not be instantiated: {unbuilt}"


@needs_php
def test_a_read_scoped_tool_refuses_a_post(driven: dict):
    """THE gate. Every tool whose required scopes fit inside a read-only roster
    is handed a POST; each must return ToolResult::error.

    This is what `wing.read` meant before the split and did not enforce.
    """
    offenders = []
    for row in driven["tools"]:
        if not row.get("within_read_only_roster"):
            continue
        if not row["post_is_error"]:
            offenders.append((row["id"], row["scopes"], row["post_content"]))
    assert not offenders, (
        "a tool loadable under a read-only scope roster accepted a POST: "
        f"{offenders}. A scope that does not name a verb cannot refuse it."
    )


@needs_php
def test_the_read_plane_refuses_at_the_verb_not_at_the_transport(driven: dict):
    """The refusal must be the tool's own, and say so. A POST that fails
    because a mock ran out of responses, or because the path was malformed,
    would satisfy the assertion above while proving nothing."""
    read = next(r for r in driven["tools"] if r.get("id") == "mcp-wing-read")
    assert read["post_refused_reason"] == "verb_not_in_scope", (
        f"mcp-wing-read refused for the wrong reason: {read!r}"
    )


@needs_php
def test_the_write_plane_refuses_a_route_it_was_not_granted(driven: dict):
    """/api/v1/pentest/findings is a real Wing route that inspektor's prompt
    asks for and that NO agent was ever measured calling. The allowlist is
    grandfathered from measurement, so it must refuse."""
    w = driven["write_plane"]["ungranted"]
    assert w["is_error"] is True, f"the write plane accepted an un-granted route: {w}"
    assert w["reason"] == "route_not_granted", f"refused for the wrong reason: {w}"


@needs_php
def test_the_write_plane_accepts_the_route_it_was_granted(driven: dict):
    """NEGATIVE CONTROL — without it, a tool that refuses everything passes
    every other assertion in this file."""
    g = driven["write_plane"]["granted"]
    assert g["is_error"] is False, (
        f"the write plane refused its own granted route: {g}. Both agents that "
        "hold it file their report through /api/v1/events; refusing it silences them."
    )


@needs_php
def test_the_write_plane_refuses_a_get(driven: dict):
    """Symmetry, and not cosmetic: a write tool that also reads re-opens the
    door from the other side — one grant, two verbs."""
    r = driven["write_plane"]["read_verb"]
    assert r["is_error"] is True and r["reason"] == "verb_not_in_scope", (
        f"the write plane served a GET: {r}"
    )


@needs_php
def test_the_registry_refuses_the_write_tool_without_the_write_scope():
    """Admission control, one layer up: the refusals above happen at call time,
    this one stops the tool reaching the agent's roster at all."""
    got = _run(_REGISTRY_PROBE, "verb-scope-registry-probe.php")
    assert "refused" in got["read_roster_gets_write_tool"], (
        "ToolRegistry handed mcp-wing-write to an agent without wing.write: "
        f"{got['read_roster_gets_write_tool']}"
    )
    assert "wing.write" in got["read_roster_gets_write_tool"]["refused"], (
        "the refusal does not name the missing scope, so an operator reading it "
        f"cannot tell what to grant: {got['read_roster_gets_write_tool']}"
    )
    assert got["read_roster_gets_read_tool"] == {"loaded": ["mcp-wing-read"]}, (
        "the read plane is no longer loadable under a read-only roster — the "
        f"split broke reading: {got['read_roster_gets_read_tool']}"
    )
    assert got["write_roster_gets_write_tool"] == {"loaded": ["mcp-wing-write"]}, (
        f"wing.write does not load the write plane: {got['write_roster_gets_write_tool']}"
    )


def test_every_granted_route_is_a_measured_one():
    """The allowlist in the code must equal the measurement in the artifact.

    Q14=b in one assertion: a route enters GRANTED_ROUTES because an agent was
    recorded calling it, never because a system prompt asks for it. If someone
    widens the allowlist to satisfy a prompt, this fails until the artifact is
    re-measured — which is the point.
    """
    assert GRANTS.is_file(), (
        "the measurement the grant rests on is missing; a grant with no "
        "traceable extent is a guess"
    )
    grants = json.loads(GRANTS.read_text(encoding="utf-8"))
    measured = {r["path"] for a in grants["grants"] for r in a["routes"]}

    src = (WING / "app/AgentKit/Tools/McpWingWriteTool.php").read_text(encoding="utf-8")
    block = src[src.index("GRANTED_ROUTES = ["):]
    in_code = set(re.findall(r"'(/api/[^']+)'", block[: block.index("]")]))

    assert in_code == measured, (
        f"GRANTED_ROUTES {sorted(in_code)} does not match the measured routes "
        f"{sorted(measured)} in {GRANTS.name}"
    )
    span = grants["span"]
    for key in ("agent_tool_use_first_ts", "agent_tool_use_last_ts", "mcp_wing_post_rows"):
        assert span.get(key), f"the artifact does not state its extent ({key} missing)"
