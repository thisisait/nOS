"""A bound agent's POST must carry the same HMAC the shell path carries.

The bound AgentKit loop ran, MiniMax served it, and every ceremony still failed
the rubric: `McpWingTool` sent a bearer token only, so `POST /api/v1/events`
returned 401 (`EventsPresenter::checkHmac`) and no run could file its report.

This test does not grep for a header name — it runs the tool against a Guzzle
mock handler, captures the real request, and verifies the signature the way the
presenter does: `hash_hmac('sha256', "<ts>.<raw body>", secret)` over the bytes
actually sent, not over a re-encoding of them.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"

PROBE = r"""
require __DIR__ . '/vendor/autoload.php';

use App\AgentKit\Tools\McpWingTool;
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
$tool = new McpWingTool(new Client(['handler' => $stack]), 'probe-token');

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
