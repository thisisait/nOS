"""A bound agent's POST must carry the same HMAC the shell path carries.

The bound AgentKit loop ran, MiniMax served it, and every ceremony still failed
the rubric: the Wing MCP tool sent a bearer token only, so `POST /api/v1/events`
returned 401 (`EventsPresenter::checkHmac`) and no run could file its report.

This test does not grep for a header name — it runs the tool against a Guzzle
mock handler, captures the real request, and verifies the signature the way the
presenter does: `hash_hmac('sha256', "<ts>.<raw body>", secret)` over the bytes
actually sent, not over a re-encoding of them.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"

# Honest only outside a declaring environment: CI declares php + the vendor
# path via NOS_TEST_PROVIDES, so there the contract aborts the session instead.
pytestmark = pytest.mark.skipif(
    shutil.which("php") is None or not (WING / "vendor/autoload.php").is_file(),
    reason="php binary or wing vendor/autoload.php missing — run `composer "
           "install` in files/anatomy/wing",
)

PROBE_404 = r"""
require __DIR__ . '/vendor/autoload.php';

use App\AgentKit\Tools\McpWingReadTool;
use App\AgentKit\Tools\ToolContext;
use GuzzleHttp\Client;
use GuzzleHttp\Handler\MockHandler;
use GuzzleHttp\HandlerStack;
use GuzzleHttp\Psr7\Response;

$stack = HandlerStack::create(new MockHandler([new Response(404, [], '<html>not found</html>')]));
$tool = new McpWingReadTool(new Client(['handler' => $stack]), 'probe-token');
$ctx = new ToolContext('s-1', 'th-1', 't-1', 'sp-1', 'probe', 'tu-1');
$r = $tool->execute(['method' => 'GET', 'path' => '/api/v1/systems'], $ctx);
echo json_encode(['content' => $r->content]);
"""

PROBE = r"""
require __DIR__ . '/vendor/autoload.php';

use App\AgentKit\Tools\McpWingWriteTool;
use App\AgentKit\Tools\ToolContext;
use GuzzleHttp\Client;
use GuzzleHttp\Handler\MockHandler;
use GuzzleHttp\HandlerStack;
use GuzzleHttp\Middleware;
use GuzzleHttp\Psr7\Response;

putenv('WING_EVENTS_HMAC_SECRET=probe-secret');

$sent = [];
$stack = HandlerStack::create(new MockHandler([new Response(201, [], '{"ok":true}')]));
$stack->push(Middleware::history($sent));
$tool = new McpWingWriteTool(new Client(['handler' => $stack]), 'probe-token');

$ctx = new ToolContext('s-1', 'th-1', 't-1', 'sp-1', 'probe', 'tu-1');
$tool->execute([
    'method' => 'POST',
    'path' => '/api/v1/events',
    'body' => ['ts' => '2026-08-28T00:00:00Z', 'type' => 'agent_message', 'run_id' => 'r-1'],
], $ctx);

$req = $sent[0]['request'];
echo json_encode([
    'raw' => (string) $req->getBody(),
    'ts' => $req->getHeaderLine('X-Wing-Timestamp'),
    'sig' => $req->getHeaderLine('X-Wing-Signature'),
]);
"""


def test_post_is_hmac_signed_over_the_bytes_sent() -> None:
    probe = WING / "hmac-probe.php"
    probe.write_text("<?php\n" + PROBE, encoding="utf-8")
    try:
        out = subprocess.run(
            ["php", probe.name], cwd=WING, capture_output=True, text=True, timeout=60
        )
    finally:
        probe.unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)

    import hashlib
    import hmac

    assert got["ts"].isdigit(), "no HMAC timestamp on the request"
    expected = hmac.new(
        b"probe-secret", f"{got['ts']}.{got['raw']}".encode(), hashlib.sha256
    ).hexdigest()
    assert got["sig"] == expected, "signature does not verify over the raw body sent"


def _run(src: str, name: str) -> dict:
    probe = WING / name
    probe.write_text("<?php\n" + src, encoding="utf-8")
    try:
        out = subprocess.run(["php", probe.name], cwd=WING,
                             capture_output=True, text=True, timeout=60)
    finally:
        probe.unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_a_404_answers_with_the_routes_that_exist() -> None:
    """The surveyor invented /api/v1/systems and /api/v1/health out of this
    tool's prose description, got two 404s and gave up (2026-08-28, session
    505e0f11). A 404 now answers with the live route table — read from the
    router the request just missed, so the hint cannot drift from it.
    """
    content = _run(PROBE_404, "hmac-probe-404.php")["content"]
    assert "not routed" in content, "a 404 no longer tells the model what exists"
    for route in ("/api/v1/events", "/api/v1/pulse_jobs", "/api/v1/hub/health"):
        assert route in content, f"the route hint omits {route}"
    assert "unreadable" not in content, "the tool could not find the router"
    assert "/api/v1/systems\n" not in content
