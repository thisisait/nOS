"""An agent-filed event carries attribution whether or not the model wrote it.

Event 377830 (2026-08-29): a bound ceremony's conductor_report landed with
source, actor_id and actor_action_id ALL empty — the model's tool-call body
simply omitted them, and the tool sent whatever it was given. The architecture
promises one `SELECT WHERE actor_action_id=?` reconstructs a run; that promise
must not depend on a language model remembering three fields.

Runs the real McpWingWriteTool against a Guzzle mock, reads the RAW body it
actually sent (the same bytes the HMAC signs), and asserts the tool defaulted
attribution from its ToolContext — and never overwrote an explicit value.
"""

from __future__ import annotations

import hashlib
import hmac
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
use App\\AgentKit\\Tools\\McpWingWriteTool;
use App\\AgentKit\\Tools\\ToolContext;
use GuzzleHttp\\Client;
use GuzzleHttp\\Handler\\MockHandler;
use GuzzleHttp\\HandlerStack;
use GuzzleHttp\\Middleware;
use GuzzleHttp\\Psr7\\Response;

putenv('WING_EVENTS_HMAC_SECRET=probe-secret');

function post(array $body): array {
    $sent = [];
    $stack = HandlerStack::create(new MockHandler([new Response(201, [], '{"ok":true}')]));
    $stack->push(Middleware::history($sent));
    $tool = new McpWingWriteTool(new Client(['handler' => $stack]), 'probe-token');
    $ctx = new ToolContext('sess-uuid-1', 'th-1', 't-1', 'sp-1', 'agent:nos-conductor', 'tu-1');
    $tool->execute(['method' => 'POST', 'path' => '/api/v1/events', 'body' => $body], $ctx);
    $req = $sent[0]['request'];
    return ['raw' => (string) $req->getBody(),
            'ts' => $req->getHeaderLine('X-Wing-Timestamp'),
            'sig' => $req->getHeaderLine('X-Wing-Signature')];
}

echo json_encode([
    'bare'     => post(['type' => 'conductor_report', 'run_id' => 'r-1']),
    'explicit' => post(['type' => 'conductor_report', 'run_id' => 'r-1',
                        'source' => 'surveyor', 'actor_id' => 'agent:nos-surveyor',
                        'actor_action_id' => 'other-uuid']),
]);
"""


def _drive(tmp_path):
    probe = tmp_path / "probe.php"
    probe.write_text(PROBE % {"autoload": str(AUTOLOAD)})
    r = subprocess.run(["php", str(probe)], capture_output=True, text=True)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    return json.loads(r.stdout)


def test_omitted_attribution_is_defaulted_from_the_tool_context(tmp_path):
    got = _drive(tmp_path)
    body = json.loads(got["bare"]["raw"])
    assert body["actor_action_id"] == "sess-uuid-1", "the run is unreconstructable"
    assert body["actor_id"] == "agent:nos-conductor"
    assert body["source"] == "conductor", "agent:nos-conductor should file as 'conductor'"
    # The HMAC must cover the body as SENT, defaults included.
    expect = hmac.new(b"probe-secret",
                      (got["bare"]["ts"] + "." + got["bare"]["raw"]).encode(),
                      hashlib.sha256).hexdigest()
    assert got["bare"]["sig"] == expect, "attribution was stamped after signing"


def test_explicit_attribution_is_never_overwritten(tmp_path):
    got = _drive(tmp_path)
    body = json.loads(got["explicit"]["raw"])
    assert body["source"] == "surveyor"
    assert body["actor_id"] == "agent:nos-surveyor"
    assert body["actor_action_id"] == "other-uuid"
