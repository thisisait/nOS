"""A tool must refuse the verb its scope does not name.

Until 2026-08-28 one tool — `mcp-wing` — carried GET and POST behind the single
scope `wing.read`. Every agent that could read the estate could therefore write
to it, and the registry's scope check could not tell the two apart because the
scope roster never mentioned a verb. `wing.read` was, in practice, `wing.*`.

The split is only real if the READ plane actually refuses a POST. That is a
claim about behaviour, so this gate does not grep: it instantiates every tool
class the DI container registers, hands each one a POST **at a path that tool
actually serves**, and asserts the refusal.

That emphasis is this file's own scar. The first version of this gate probed
every tool with `/api/v1/events`, a Wing path. `mcp-keap` — scopes
`['mcp.tool_use','keap.read']`, well inside the read-only roster — answered
"path must start with /agent/v1/", and the gate counted that as a refusal. It
was a TRANSPORT rejection standing in for a VERB rejection: driven at
`/agent/v1/captures`, a path KEAP serves, the same read-only roster got
`isError=false`, HTTP 200, `{"WROTE":true}`. A probe that cannot reach the
code proves nothing, so every probe path below is checked to REACH the tool's
own gate before its refusal is believed (`test_the_probe_reaches_each_tools_own_gate`).

The assertions, each failing independently:

  1. every registered tool has a declared probe path, and every tool that takes
     an HTTP client — an estate plane — has a real one, not a `None`;
  2. that path reaches the tool's own gate rather than a path-shape check;
  3. a POST that is SERVED requires a `*.write` scope (THE gate — this is what
     `wing.read`, and later `keap.read`, did not enforce);
  4. a read-scoped tool refuses at the verb and SAYS so
     (`refused_reason=verb_not_in_scope`), for every tool in the registry;
  5. a write-scoped tool refuses a path outside its grant — for Wing the grant
     is grandfathered from measured use in
     docs/plans/rsi-research/artifacts/wing-write-grants.json;
  6. `ToolRegistry::forAgent()` refuses to hand a write tool to an agent whose
     capability_scopes lack the write scope — admission control, one layer up;
  7. the AGENTS holding the write plane equal the agents that measurement
     granted. Assertions 1-6 all pin WHICH ROUTES; none pinned WHO, so handing
     the plane to an agent with no measured call was invisible to every gate
     in the estate.

NEGATIVE CONTROL: a write tool must ACCEPT its granted route. Without it every
assertion here is satisfied by a tool that refuses everything, which is the
failure mode a security gate is most likely to ship green.

The bridge is the one the suite already uses for PHP-effect gates
(tests/anatomy/test_bound_agent_can_file_its_report.py): write a probe into the
wing tree, run it with the local `php` against the composer autoload, read JSON
off stdout. On CI the vendor tree is DECLARED (NOS_TEST_PROVIDES carries the
autoload path) so its absence aborts the session rather than skipping the half
of this file that actually calls a tool.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
AGENTS = REPO / "files/anatomy/agents"
WING = REPO / "files/anatomy/wing"
TOOLS_DIR = WING / "app/AgentKit/Tools"
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


# A roster that can read everything and write nothing. The `*.write` estate
# scopes are the ones deliberately absent — their absence is what the read
# plane must respect.
READ_ONLY_SCOPES = [
    "bash.read", "mcp.tool_use", "wing.read", "bone.read",
    "keap.read", "events.write", "audit.read", "inbox.ask",
]

# Per-tool probe paths. `served` is a path THAT TOOL ROUTES — without it the
# probe dies at a path-shape check and proves nothing (the mcp-keap hole).
# `unserved` is a path the tool routes the shape of but must refuse to write.
# A tool that takes no HTTP path at all declares `None`, and assertion 1 makes
# that declaration a decision someone has to make rather than an omission.
PROBE_PATHS: dict[str, dict[str, str | None]] = {
    "mcp-wing-read": {"served": "/api/v1/events", "unserved": None},
    "mcp-wing-write": {"served": "/api/v1/events", "unserved": "/api/v1/pentest/findings"},
    "mcp-bone": {"served": "/api/health", "unserved": None},
    "mcp-keap": {"served": "/agent/v1/captures", "unserved": "/agent/v1/taxonomy/approve"},
    "bash-read-only": {"served": None, "unserved": None},
    "migration-file-write": {"served": None, "unserved": None},
    "ask-operator": {"served": None, "unserved": None},
}

_PROBE = r"""
require __DIR__ . '/vendor/autoload.php';

use App\AgentKit\Tools\ToolContext;
use App\AgentKit\Tools\ToolInterface;
use GuzzleHttp\Client;
use GuzzleHttp\Handler\MockHandler;
use GuzzleHttp\HandlerStack;
use GuzzleHttp\Psr7\Response;

[$_, $classesJson, $scopesJson, $pathsJson] = $argv;

// Tokens present, so a missing-credential error can never masquerade as a
// scope refusal. A refusal below is the tool's own gate or nothing.
putenv('KEAP_AGENT_TOKEN_RO=probe-ro');
putenv('KEAP_AGENT_TOKEN_RW=probe-rw');
putenv('NOS_AGENT_WING_TOKEN=probe-wing');

// Every mock request succeeds. A refusal in the output therefore came from the
// tool's own gate, never from a transport failure standing in for one.
function client(): Client {
    $responses = array_fill(0, 20, new Response(200, [], '{"WROTE":true}'));
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

function call(ToolInterface $tool, string $method, string $path, ToolContext $ctx): array {
    $input = ['method' => $method, 'path' => $path];
    if ($method === 'POST') {
        $input['body'] = ['ts' => '2026-08-28T00:00:00Z', 'type' => 'gate_probe'];
    }
    $r = $tool->execute($input, $ctx);
    return [
        'is_error' => $r->isError,
        'reason' => $r->metadata['refused_reason'] ?? null,
        'content' => substr($r->content, 0, 200),
    ];
}

$ctx = new ToolContext('s-1', 'th-1', 'tr-1', 'sp-1', 'agent:probe', 'tu-1');
$scopes = json_decode($scopesJson, true);
$paths = json_decode($pathsJson, true);
$out = [];

foreach (json_decode($classesJson, true) as $class) {
    $row = ['class' => $class];
    try {
        $tool = build($class);
        $row['id'] = $id = $tool->id();
        $row['scopes'] = $tool->requiredScopes();
        $row['within_read_only_roster'] = array_diff($tool->requiredScopes(), $scopes) === [];
        // Taking a Guzzle client means this tool talks to an estate HTTP
        // plane, so it MUST carry a real probe path. Derived from the
        // constructor, not from the table, so a new plane cannot declare
        // itself out of scope. (BASE_URL would miss McpKeapTool, which
        // resolves its base URL into a property at construct time.)
        $ctor = (new ReflectionClass($tool))->getConstructor();
        $row['talks_http'] = false;
        foreach ($ctor?->getParameters() ?? [] as $p) {
            $t = $p->getType() instanceof ReflectionNamedType ? $p->getType()->getName() : null;
            if ($t === Client::class) {
                $row['talks_http'] = true;
            }
        }
        $served = $paths[$id]['served'] ?? null;
        if ($served !== null) {
            $row['get'] = call($tool, 'GET', $served, $ctx);
            $row['post'] = call($tool, 'POST', $served, $ctx);
            // Reach = whichever verb this tool does answer. If BOTH come back
            // without a refused_reason and still error, the path never landed.
            $row['reach'] = $row['get']['reason'] === null && !$row['get']['is_error']
                ? $row['get'] : $row['post'];
            $unserved = $paths[$id]['unserved'] ?? null;
            if ($unserved !== null) {
                $row['unserved'] = call($tool, 'POST', $unserved, $ctx);
            }
        }
    } catch (Throwable $e) {
        $row['build_error'] = get_class($e) . ': ' . $e->getMessage();
    }
    $out[] = $row;
}

echo json_encode($out);
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


def _run(src: str, name: str, *args: str) -> dict | list:
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
def driven() -> list[dict]:
    return _run(
        _PROBE, "verb-scope-probe.php",
        json.dumps(registered_tool_classes()),
        json.dumps(READ_ONLY_SCOPES),
        json.dumps(PROBE_PATHS),
    )


def _by_id(driven: list[dict], tool_id: str) -> dict:
    row = next((r for r in driven if r.get("id") == tool_id), None)
    assert row is not None, f"{tool_id} is no longer registered; the probe drove {driven}"
    return row


def _has_write_scope(row: dict) -> bool:
    return any(s.endswith(".write") for s in row["scopes"])


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
def test_every_registered_tool_is_buildable(driven: list[dict]):
    """A tool this harness cannot construct is a tool it cannot drive, and an
    undriven tool is an untested one. Fail rather than silently skip it."""
    unbuilt = {r["class"]: r["build_error"] for r in driven if "build_error" in r}
    assert not unbuilt, f"registered tools could not be instantiated: {unbuilt}"


@needs_php
def test_every_registered_tool_declares_a_probe_path(driven: list[dict]):
    """A tool with no entry here is a tool this file never drives. Declaring
    `None` is allowed, but it is a DECISION — and one the tool itself can
    contradict: anything taking an HTTP client reaches an estate plane and must
    name a path the probe can reach."""
    ids = {r["id"] for r in driven}
    assert ids == set(PROBE_PATHS), (
        f"PROBE_PATHS covers {sorted(PROBE_PATHS)} but the registry builds "
        f"{sorted(ids)}. Every registered tool must state how to make it write."
    )
    undeclared = [r["id"] for r in driven
                  if r["talks_http"] and PROBE_PATHS[r["id"]]["served"] is None]
    assert not undeclared, (
        f"{undeclared} reach an estate HTTP plane (they take a Guzzle client) but "
        "declare no served path, so no POST of theirs is ever driven"
    )


@needs_php
def test_the_probe_reaches_each_tools_own_gate(driven: list[dict]):
    """THE lesson of this file. A refusal is only evidence if the request got
    past the transport checks to the scope check. `mcp-keap` refused
    `/api/v1/events` with "path must start with /agent/v1/" — a path-shape
    complaint, no `refused_reason` — and the gate read that as a scope refusal
    for four days."""
    for row in driven:
        if PROBE_PATHS[row["id"]]["served"] is None:
            continue
        reach = row["reach"]
        assert not (reach["is_error"] and reach["reason"] is None), (
            f"{row['id']}: the probe path {PROBE_PATHS[row['id']]['served']!r} never "
            f"reached the tool's gate — it failed with no refused_reason: {reach}. "
            "Give it a path this tool actually serves."
        )


@needs_php
def test_a_served_post_requires_a_write_scope(driven: list[dict]):
    """THE gate. Any tool that ACCEPTS a POST must ask for a scope that names
    writing. `wing.read` did not, and neither did `keap.read` — both served a
    write to any agent that could read."""
    offenders = [
        (r["id"], r["scopes"], r["post"]["content"])
        for r in driven
        if PROBE_PATHS[r["id"]]["served"] is not None
        and not r["post"]["is_error"] and not _has_write_scope(r)
    ]
    assert not offenders, (
        f"a tool served a POST without asking for a write scope: {offenders}. "
        "A scope that does not name a verb cannot refuse it."
    )


@needs_php
def test_a_read_scoped_tool_refuses_a_post_at_the_verb(driven: list[dict]):
    """Every tool whose required scopes fit inside a read-only roster is handed
    a POST at a path it serves; each must refuse, and the refusal must be its
    OWN — `refused_reason=verb_not_in_scope`, not a transport complaint.

    Generalised over the registry (it was hardcoded to mcp-wing-read): a tool
    added tomorrow is driven without anyone remembering to add it here.
    """
    for row in driven:
        if PROBE_PATHS[row["id"]]["served"] is None or not row["within_read_only_roster"]:
            continue
        assert row["post"]["is_error"], (
            f"{row['id']} is loadable under a read-only roster and accepted a "
            f"POST: {row['post']}"
        )
        assert row["post"]["reason"] == "verb_not_in_scope", (
            f"{row['id']} refused the POST for the wrong reason: {row['post']}. "
            "A transport rejection is not a scope refusal."
        )


@needs_php
def test_a_write_only_tool_refuses_a_get(driven: list[dict]):
    """Symmetry, and not cosmetic: a tool holding `X.write` without `X.read`
    that also reads re-opens the door from the other side — one grant, two
    verbs."""
    for row in driven:
        if PROBE_PATHS[row["id"]]["served"] is None:
            continue
        planes = {s.rsplit(".", 1)[0] for s in row["scopes"] if s.endswith(".write")}
        if not any(f"{p}.read" not in row["scopes"] for p in planes):
            continue
        assert row["get"]["is_error"] and row["get"]["reason"] == "verb_not_in_scope", (
            f"{row['id']} holds a write scope with no matching read scope but "
            f"served a GET: {row['get']}"
        )


@needs_php
def test_a_write_tool_refuses_a_path_it_was_not_granted(driven: list[dict]):
    """/api/v1/pentest/findings is a real Wing route that inspektor's prompt
    asks for and that NO agent was ever measured calling; /agent/v1/taxonomy/approve
    is the KEAP route that would turn a proposal into a decision. Both are
    reachable in shape and both must be refused by name."""
    probed = [r for r in driven if "unserved" in r]
    assert probed, "no tool is driven with an un-granted path — the grant is untested"
    for row in probed:
        u = row["unserved"]
        assert u["is_error"], (
            f"{row['id']} accepted the un-granted path "
            f"{PROBE_PATHS[row['id']]['unserved']}: {u}"
        )
        assert u["reason"] in ("route_not_granted", "path_not_in_post_allowlist"), (
            f"{row['id']} refused the un-granted path for the wrong reason: {u}"
        )


@needs_php
def test_the_write_plane_accepts_the_route_it_was_granted(driven: list[dict]):
    """NEGATIVE CONTROL — without it, a tool that refuses everything passes
    every other assertion in this file."""
    g = _by_id(driven, "mcp-wing-write")["post"]
    assert g["is_error"] is False, (
        f"the write plane refused its own granted route: {g}. Both agents that "
        "hold it file their report through /api/v1/events; refusing it silences them."
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


def wing_write_tool_ids() -> set[str]:
    """Tool ids that ask for `wing.write` — read off requiredScopes(), so a
    second write plane added tomorrow is covered without editing this file."""
    ids = set()
    for php in sorted(TOOLS_DIR.glob("*.php")):
        src = php.read_text(encoding="utf-8")
        scopes = re.search(r"function requiredScopes\(\): array\s*\{(.*?)\n\t?\}", src, re.S)
        ident = re.search(r"function id\(\): string\s*\{\s*return '([^']+)'", src)
        if scopes and ident and "'wing.write'" in scopes.group(1):
            ids.add(ident.group(1))
    return ids


def agents_holding(tool_ids: set[str]) -> set[str]:
    holders = set()
    for manifest in sorted(AGENTS.glob("*/agent.yml")):
        doc = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        declared = {t.get("id") for t in (doc.get("tools") or []) if isinstance(t, dict)}
        if declared & tool_ids:
            holders.add(doc.get("name") or manifest.parent.name)
    return holders


def test_the_agents_holding_the_write_plane_are_the_agents_measured_writing():
    """The grant is per-AGENT, not only per-ROUTE.

    Found by this phase's own verifier: it added `mcp-wing-write` + `wing.write`
    to conductor — an agent with ZERO measured calls, named in the artifact's
    own `no_grant` finding — and the whole corpus stayed green, 4135 passed.
    Every gate pinned WHICH ROUTES the plane reaches and none pinned WHO holds
    it, so the widening the artifact exists to prevent was invisible.

    Equality, so it fails in both directions: an agent handed the write plane
    without a measured call is a widening; an agent that was measured writing
    and no longer holds it is an agent silently muted.
    """
    grants = json.loads(GRANTS.read_text(encoding="utf-8"))
    measured = {a["agent"] for a in grants["grants"]}
    tool_ids = wing_write_tool_ids()
    assert tool_ids, (
        "no tool asks for wing.write — either the split was reverted or "
        "requiredScopes() moved, and this gate is measuring nothing"
    )
    holders = agents_holding(tool_ids)
    assert holders == measured, (
        f"agents holding {sorted(tool_ids)}: {sorted(holders)}; agents the "
        f"measurement granted: {sorted(measured)}. Extra holders "
        f"({sorted(holders - measured)}) were never recorded writing — a prompt "
        "asking for a POST is not a grant. Missing holders "
        f"({sorted(measured - holders)}) were measured writing and can no longer "
        f"file their report. Re-measure {GRANTS.name} before changing either side."
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
