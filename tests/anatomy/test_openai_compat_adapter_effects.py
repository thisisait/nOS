"""The OpenAI-compatible adapter, measured at the bytes it sends and reads.

WHY BYTES AND NOT NAMES. Finding 3 of 2026-08-16: `AnthropicAdapter` died on
`create(...$params)` spreading `max_tokens` into an SDK whose named parameter
is `$maxTokens` — a name that merely LOOKED right, failing at call time, being
classified transient, retried three times, and blaming the openclaw fallback
that had done nothing wrong. This adapter's call convention is the wire
protocol itself, so the gate pins the WIRE: Guzzle's MockHandler plus history
middleware capture the exact request; the assertions read the JSON body, the
URL, and the auth header — no network, no vendor, no name that is not also
the contract.

WHAT IS PINNED, each a verified trip wire (2026-08-16, docs.mistral.ai):
  * `tool_call_id` is EXACTLY 9 alphanumerics on the wire — Anthropic-style
    ids (`toolu_…`) arrive via cross-backend fallback transcripts and must be
    sanitised DETERMINISTICALLY, so the assistant's tool_call and the tool
    message answering it agree without adapter state
  * neither `seed` nor `random_seed` is sent — the naming SPLITS by vendor,
    so whoever first sends determinism meets it consciously, not by default
  * `max_tokens` is the body key (not `max_completion_tokens`, which most
    compatibles do not implement)
  * an empty tool schema still carries `parameters` with `"properties":{}`
    as a JSON OBJECT — PHP's empty array would encode `[]` and Mistral 400s
  * 4xx-not-429 → permanent, 5xx → transient — the classification whose
    misfire made finding 3 expensive
  * the UNBOUND `openai-*` build refuses: openai names a protocol, and this
    estate has no default OpenAI endpoint for it to mean

SKIP HONESTY: needs php + wing vendor autoload, same contract as
test_binding_resolver_effects.py; the data-side gates run everywhere.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
AUTOLOAD = REPO / "files/anatomy/wing/vendor/autoload.php"

_HARNESS = r"""<?php
declare(strict_types=1);
require $argv[1];

use App\AgentKit\LLMClient\Binding;
use App\AgentKit\LLMClient\Factory;
use App\AgentKit\LLMClient\LLMPermanentError;
use App\AgentKit\LLMClient\LLMTransientError;
use App\AgentKit\LLMClient\Message;
use App\AgentKit\LLMClient\OpenAiCompatAdapter;
use App\AgentKit\LLMClient\ToolSchema;
use App\AgentKit\Vault\CredentialResolver;
use GuzzleHttp\Client as HttpClient;
use GuzzleHttp\Handler\MockHandler;
use GuzzleHttp\HandlerStack;
use GuzzleHttp\Middleware;
use GuzzleHttp\Psr7\Response;

$binding = new Binding(
    name: 'mistral-eu',
    baseUrl: 'https://api.eu.mistral.example/v1',
    authToken: 'fake-bearer-for-the-harness',
    modelId: 'FAKE-mistral-large',
);

function clientWith(array $responses, array &$history): HttpClient {
    $mock = new MockHandler($responses);
    $stack = HandlerStack::create($mock);
    $stack->push(Middleware::history($history));
    return new HttpClient(['handler' => $stack, 'http_errors' => true]);
}

$out = [];
$try = function (string $label, callable $fn) use (&$out) {
    try {
        $out[$label] = $fn();
    } catch (LLMPermanentError $e) {
        $out[$label] = ['permanent' => $e->getMessage()];
    } catch (LLMTransientError $e) {
        $out[$label] = ['transient' => $e->getMessage()];
    } catch (Throwable $e) {
        $out[$label] = ['error' => get_class($e) . ': ' . $e->getMessage()];
    }
};

$toolCallsResponse = new Response(200, [], json_encode([
    'choices' => [[
        'message' => [
            'content' => 'checking',
            'tool_calls' => [[
                'id' => 'abc123XYZ',
                'type' => 'function',
                'function' => ['name' => 'mcp_wing', 'arguments' => '{"path":"/api/v1/events"}'],
            ]],
        ],
        'finish_reason' => 'tool_calls',
    ]],
    'usage' => ['prompt_tokens' => 120, 'completion_tokens' => 45],
]));

$try('request_wire', function () use ($binding, $toolCallsResponse) {
    $history = [];
    $http = clientWith([$toolCallsResponse], $history);
    $adapter = new OpenAiCompatAdapter($http, 'openai-mistral-large', $binding);
    $foreignId = 'toolu_01ABCDEFGHIJKLMNOPQRSTUV';
    $resp = $adapter->send(
        'you are a probe',
        [
            Message::userText('start'),
            new Message('assistant', [
                ['type' => 'text', 'text' => 'let me check'],
                ['type' => 'tool_use', 'id' => $foreignId, 'name' => 'mcp_wing',
                 'input' => ['path' => '/api/health']],
            ]),
            Message::userToolResults([
                ['tool_use_id' => $foreignId, 'content' => '{"ok":true}', 'is_error' => false],
            ]),
        ],
        [
            new ToolSchema('mcp_wing', 'wing reader', ['type' => 'object',
                'properties' => ['path' => ['type' => 'string']], 'required' => ['path']]),
            new ToolSchema('noop', 'schema-less tool', []),
        ],
        512,
    );
    $req = $history[0]['request'];
    $rawBody = (string) $req->getBody();
    $body = json_decode($rawBody, true);
    $assistant = null;
    $toolMsg = null;
    foreach ($body['messages'] as $m) {
        if (($m['role'] ?? '') === 'assistant') { $assistant = $m; }
        if (($m['role'] ?? '') === 'tool') { $toolMsg = $m; }
    }
    return [
        'url' => (string) $req->getUri(),
        'auth' => $req->getHeaderLine('Authorization'),
        'model' => $body['model'],
        'max_tokens' => $body['max_tokens'],
        'first_role' => $body['messages'][0]['role'],
        'tool_type' => $body['tools'][0]['type'],
        'empty_params_raw' => str_contains($rawBody, '"properties":{}'),
        'call_id' => $assistant['tool_calls'][0]['id'] ?? null,
        'result_id' => $toolMsg['tool_call_id'] ?? null,
        'seedless' => !str_contains($rawBody, 'seed'),
        // response translation, same round trip
        'stop' => $resp->stopReason,
        'blocks' => $resp->contentBlocks,
        'tokens' => [$resp->tokensInput, $resp->tokensOutput],
    ];
});

$try('length_maps_to_max_tokens', function () use ($binding) {
    $history = [];
    $http = clientWith([new Response(200, [], json_encode([
        'choices' => [['message' => ['content' => 'truncat'], 'finish_reason' => 'length']],
        'usage' => ['prompt_tokens' => 5, 'completion_tokens' => 512],
    ]))], $history);
    $a = new OpenAiCompatAdapter($http, 'openai-x', $binding);
    return ['stop' => $a->send('', [Message::userText('hi')])->stopReason];
});

$try('http_401_is_permanent', function () use ($binding) {
    $history = [];
    $http = clientWith([new Response(401, [], '{"error":"bad key"}')], $history);
    (new OpenAiCompatAdapter($http, 'openai-x', $binding))->send('', [Message::userText('hi')]);
    return ['no_throw' => true];
});

$try('http_500_is_transient', function () use ($binding) {
    $history = [];
    $http = clientWith([new Response(500, [], 'oops')], $history);
    (new OpenAiCompatAdapter($http, 'openai-x', $binding))->send('', [Message::userText('hi')]);
    return ['no_throw' => true];
});

$try('unbound_openai_refuses', function () {
    $credentials = (new ReflectionClass(CredentialResolver::class))->newInstanceWithoutConstructor();
    try {
        (new Factory($credentials))->fromUri('openai-mistral-large');
        return ['built' => true];
    } catch (RuntimeException $e) {
        return ['refused' => $e->getMessage()];
    }
});

echo json_encode($out);
"""


@pytest.fixture(scope="module")
def verdicts(tmp_path_factory):
    php = shutil.which("php")
    if php is None or not AUTOLOAD.is_file():
        pytest.skip(
            "php binary or wing vendor/autoload.php missing — run `composer "
            "install` in files/anatomy/wing"
        )
    tmp = tmp_path_factory.mktemp("openai-compat")
    harness = tmp / "harness.php"
    harness.write_text(_HARNESS)
    out = subprocess.run(
        [php, str(harness), str(AUTOLOAD)],
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, f"harness died: {out.stderr[-800:]}"
    return json.loads(out.stdout)


def test_the_request_carries_the_verified_wire_shape(verdicts):
    v = verdicts["request_wire"]
    assert v["url"] == "https://api.eu.mistral.example/v1/chat/completions"
    assert v["auth"] == "Bearer fake-bearer-for-the-harness"
    assert v["model"] == "FAKE-mistral-large", (
        "the body's model is not the binding's tier-resolved id — the URI's "
        "declared intent leaked onto the wire"
    )
    assert v["max_tokens"] == 512, "the body key must be max_tokens, with the value passed"
    assert v["first_role"] == "system"
    assert v["tool_type"] == "function"
    assert v["empty_params_raw"] is True, (
        'a schema-less tool must still send parameters with "properties":{} '
        "as a JSON OBJECT — PHP's empty array encodes [] and Mistral 400s"
    )
    assert v["seedless"] is True, (
        "a seed key appeared — the naming splits by vendor (seed vs "
        "random_seed); sending one by default meets the split by accident"
    )


def test_the_foreign_tool_id_is_sanitised_consistently(verdicts):
    v = verdicts["request_wire"]
    call_id, result_id = v["call_id"], v["result_id"]
    assert call_id and len(call_id) == 9 and call_id.isalnum(), (
        f"assistant tool_call id {call_id!r} is not 9 alphanumerics — the "
        "Anthropic-style id from a cross-backend fallback transcript reached "
        "Mistral's wire, which 400s on it"
    )
    assert call_id == result_id, (
        f"the tool message answers {result_id!r} but the call was "
        f"{call_id!r} — sanitisation was not deterministic and the model "
        "sees an answer to a question nobody asked"
    )


def test_the_response_translates_to_the_vendor_neutral_shape(verdicts):
    v = verdicts["request_wire"]
    assert v["stop"] == "tool_use"
    assert v["tokens"] == [120, 45]
    types = [b["type"] for b in v["blocks"]]
    assert types == ["text", "tool_use"], f"blocks drifted: {types}"
    tool = v["blocks"][1]
    assert tool["name"] == "mcp_wing" and tool["input"] == {"path": "/api/v1/events"}, (
        "tool_calls arguments were not parsed into the input dict the Runner "
        "executes tools from"
    )
    assert verdicts["length_maps_to_max_tokens"]["stop"] == "max_tokens"


def test_errors_classify_like_the_night_needs(verdicts):
    assert "permanent" in verdicts["http_401_is_permanent"], (
        "a 401 was not permanent — it would be retried three times and then "
        "blamed on the fallback, finding 3's exact failure shape"
    )
    assert "transient" in verdicts["http_500_is_transient"]


def test_unbound_openai_refuses_with_a_pointer(verdicts):
    v = verdicts["unbound_openai_refuses"]
    assert "refused" in v and "protocol" in v["refused"], (
        f"an unbound openai-* build did not refuse: {v!r} — openai names a "
        "protocol, and without a registry row there is no place requests go"
    )
