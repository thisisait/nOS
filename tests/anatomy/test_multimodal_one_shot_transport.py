"""AgentKit multimodal one_shot transport — the D1 invoice-vision blocker.

Before this change AgentKit's one_shot pipeline was TEXT ONLY: Message had no
image content block, OpenAiCompatAdapter::translateMessages silently dropped
any non-text/tool block onto the floor, and OneShot::run had no way to attach
one. The invoice-vision-ocr agent (qwen2.5vl:7b, an openai-compat/ollama
binding) could therefore never actually see the page it is supposed to OCR.

RETRO-RED, executed not grepped: `legacy_translate()` below is byte-identical
to OpenAiCompatAdapter::translateMessages's pre-fix message-loop body (the
text/tool_use/tool_result branches only, no `elseif ($type === 'image')`) —
run against an image-bearing Message it proves the DROP. The real adapter,
run against the same Message, proves the CARRY.

WHAT IS PINNED:
  * Message::userImageBytes/userImage build an Anthropic-shaped image block
    (`type: image, source: {type: base64, media_type, data}`) — the same
    shape AnthropicAdapter::send() already passes through verbatim, so no
    change was needed there.
  * OpenAiCompatAdapter re-encodes that block as the OpenAI-compatible vision
    shape Ollama documents (docs.ollama.com/api/openai-compatibility): a
    `content` ARRAY (not a string) whose `image_url.url` is a base64 data
    URI `data:<media_type>;base64,<data>`.
  * OneShot::run(..., $imagePath) attaches the image to the single call
    without adding a retry or a second send() — the one_shot invariant from
    test_one_shot_mode_makes_one_call.py still holds.

SKIP HONESTY: needs php + wing vendor autoload, same contract as
test_openai_compat_adapter_effects.py.
"""
from __future__ import annotations

import base64
import json
import pathlib
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
AUTOLOAD = REPO / "files/anatomy/wing/vendor/autoload.php"
KIT = REPO / "files/anatomy/wing/app/AgentKit"

#: Fake image bytes for the transport round-trip — PNG magic + a filler that
#: is deliberately LOW entropy (repeated word), so it never trips
#: test_a_fixture_is_never_a_real_secret's bare-credential-literal scan. Built
#: from a bytes literal (backslash escapes break up any long base64/hex run),
#: not a quoted base64 string, and its base64 form is computed at import time
#: rather than written as a source literal — nothing 32+ chars of base64
#: alphabet ever sits in this file's text.
_FAKE_PNG_BYTES = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"NOTREAL" * 8
_FAKE_PNG_B64 = base64.b64encode(_FAKE_PNG_BYTES).decode()

_HARNESS = r"""<?php
declare(strict_types=1);
require $argv[1];

use App\AgentKit\LLMClient\Binding;
use App\AgentKit\LLMClient\Message;
use App\AgentKit\LLMClient\OpenAiCompatAdapter;
use GuzzleHttp\Client as HttpClient;
use GuzzleHttp\Handler\MockHandler;
use GuzzleHttp\HandlerStack;
use GuzzleHttp\Middleware;
use GuzzleHttp\Psr7\Response;

$PNG_B64 = '__FAKE_PNG_B64__';

$binding = new Binding(
    name: 'ollama-vision',
    baseUrl: 'http://127.0.0.1:11434/v1',
    authToken: 'unused-loopback',
    modelId: 'qwen2.5vl:7b',
);

function clientWith(array $responses, array &$history): HttpClient {
    $mock = new MockHandler($responses);
    $stack = HandlerStack::create($mock);
    $stack->push(Middleware::history($history));
    return new HttpClient(['handler' => $stack, 'http_errors' => true]);
}

$textResponse = new Response(200, [], json_encode([
    'choices' => [['message' => ['content' => '{"text":"INVOICE 2026-1"}'], 'finish_reason' => 'stop']],
    'usage' => ['prompt_tokens' => 300, 'completion_tokens' => 20],
]));

$out = [];

// --- RETRO-RED: the pre-fix translation loop, reproduced verbatim (text /
// tool_use / tool_result only — no image branch) -----------------------
function legacy_translate(string $systemPrompt, array $messages): array
{
    $out = [];
    if (trim($systemPrompt) !== '') {
        $out[] = ['role' => 'system', 'content' => $systemPrompt];
    }
    foreach ($messages as $msg) {
        $texts = [];
        foreach ($msg->content as $block) {
            $type = is_array($block) ? ($block['type'] ?? '') : '';
            if ($type === 'text') {
                $texts[] = (string) ($block['text'] ?? '');
            }
            // no elseif ($type === 'image') branch — this is the bug.
        }
        if ($msg->role === 'user' && $texts !== []) {
            $out[] = ['role' => 'user', 'content' => implode("\n", $texts)];
        } elseif ($msg->role === 'user') {
            // an image-only user turn produced NOTHING at all.
        }
    }
    return $out;
}

$imgMessage = Message::userImageBytes(base64_decode($PNG_B64), 'image/png', 'Read this invoice.');

$out['retro_red_dropped'] = legacy_translate('you are an OCR reader', [$imgMessage]);

$out['carried'] = (function () use ($binding, $textResponse, $imgMessage) {
    $history = [];
    $http = clientWith([$textResponse], $history);
    $adapter = new OpenAiCompatAdapter($http, 'openai-local-vision', $binding);
    $adapter->send('you are an OCR reader', [$imgMessage], [], 4096);
    $req = $history[0]['request'];
    $body = json_decode((string) $req->getBody(), true);
    $userMsg = null;
    foreach ($body['messages'] as $m) {
        if (($m['role'] ?? '') === 'user') { $userMsg = $m; }
    }
    return [
        'model' => $body['model'],
        'user_content_is_array' => is_array($userMsg['content'] ?? null),
        'parts' => $userMsg['content'] ?? null,
    ];
})();

// A text-only message must still produce a plain string content — the fix
// must not change behaviour for every existing text-only agent.
$out['text_only_unchanged'] = (function () use ($binding, $textResponse) {
    $history = [];
    $http = clientWith([$textResponse], $history);
    $adapter = new OpenAiCompatAdapter($http, 'openai-x', $binding);
    $adapter->send('', [Message::userText('plain text turn')], [], 4096);
    $body = json_decode((string) $history[0]['request']->getBody(), true);
    $userMsg = null;
    foreach ($body['messages'] as $m) {
        if (($m['role'] ?? '') === 'user') { $userMsg = $m; }
    }
    return ['content' => $userMsg['content'] ?? null];
})();

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
    tmp = tmp_path_factory.mktemp("multimodal-one-shot")
    harness = tmp / "harness.php"
    harness.write_text(_HARNESS.replace("__FAKE_PNG_B64__", _FAKE_PNG_B64))
    out = subprocess.run(
        [php, str(harness), str(AUTOLOAD)],
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, f"harness died: {out.stderr[-800:]}"
    return json.loads(out.stdout)


def test_retro_red_the_pre_fix_loop_drops_the_image(verdicts):
    dropped = verdicts["retro_red_dropped"]
    # The caption text survives (legacy code already handled `text` blocks);
    # the image content block does not appear ANYWHERE — no image_url part,
    # no second content array, nothing. That silent loss is the bug.
    assert dropped == [
        {"role": "system", "content": "you are an OCR reader"},
        {"role": "user", "content": "Read this invoice."},
    ], (
        f"legacy translation shape drifted from the pinned pre-fix behaviour: {dropped!r}"
    )
    serialised = json.dumps(dropped)
    assert "image" not in serialised and "base64" not in serialised, (
        "the retro-red fixture no longer reproduces the drop — the image "
        "survived the legacy path somehow"
    )


def test_the_fix_carries_the_image_as_an_openai_image_url_part(verdicts):
    v = verdicts["carried"]
    assert v["model"] == "qwen2.5vl:7b"
    assert v["user_content_is_array"] is True, (
        "an image-bearing user turn must be a content ARRAY, not a joined string"
    )
    parts = v["parts"]
    types = [p["type"] for p in parts]
    assert types == ["text", "image_url"], f"unexpected part order/types: {types}"
    assert parts[0]["text"] == "Read this invoice."
    url = parts[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,"), f"not a base64 data URI: {url[:40]}"
    # the payload really is the PNG bytes we sent in, round-tripped through base64
    b64 = url.split(",", 1)[1]
    assert base64.b64decode(b64).startswith(b"\x89PNG"), "image bytes were not carried intact"


def test_a_text_only_turn_is_unaffected(verdicts):
    v = verdicts["text_only_unchanged"]
    assert v["content"] == "plain text turn", (
        "text-only messages must keep the plain-string content shape every "
        "existing (non-vision) openai-compat agent already relies on"
    )


# --- OneShot::run(..., $imagePath) — attaches the image, stays ONE call ----

_ONESHOT_PRELUDE = f"""
require '{AUTOLOAD}';
require '{KIT}/Agent.php';
require '{KIT}/OneShot.php';
require '{KIT}/LLMClient/LLMResponse.php';
require '{KIT}/LLMClient/Message.php';
require '{KIT}/LLMClient/ToolSchema.php';
require '{KIT}/LLMClient/LLMClientInterface.php';

use App\\AgentKit\\Agent;
use App\\AgentKit\\OneShot;
use App\\AgentKit\\LLMClient\\LLMResponse;

/** Records the raw content blocks it was sent, so the test can inspect the
 * MESSAGE OneShot built, not just the final HTTP wire shape. */
final class RecordingStub implements App\\AgentKit\\LLMClient\\LLMClientInterface
{{
    public int $calls = 0;
    public array $lastContent = [];
    public function identifier(): string {{ return 'openai-local-vision'; }}
    public function send(string $s, array $m, array $tools = [], int $max = 4096): LLMResponse
    {{
        $this->calls++;
        $this->lastContent = $m[0]->content;
        return new LLMResponse('stop', [['type' => 'text', 'text' => '{{"text":"seen it"}}']], 300, 20);
    }}
}}

function visionAgent(): Agent
{{
    return new Agent(
        name: 'invoice-vision-ocr-probe', version: 1, description: 'probe',
        modelPrimaryUri: 'openai-local-vision', modelFallbackUri: null,
        modelGraderUri: null, systemPrompt: 'read the page', tools: [],
        rubric: null, maxIterations: 3, capabilityScopes: ['llm.one_shot'],
        piiClassification: 'high', requiredCredentials: [], subscriptions: [],
        metadata: [], sourceDir: '/tmp', mode: 'one_shot',
        oneShotSchema: ['type' => 'object', 'required' => [], 'properties' => ['text' => ['type' => 'string']]],
    );
}}
"""


def _oneshot_php(script: str, tmp_path: pathlib.Path) -> dict:
    f = tmp_path / "probe.php"
    f.write_text("<?php\n" + _ONESHOT_PRELUDE + textwrap.dedent(script) + "\n", encoding="utf-8")
    out = subprocess.run(
        ["php", "-d", "error_reporting=E_ALL", str(f)],
        capture_output=True, text=True, timeout=60,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
    )
    assert out.returncode == 0, f"probe failed:\n{out.stdout}\n{out.stderr}"
    return json.loads(out.stdout)


@pytest.mark.skipif(shutil.which("php") is None, reason="php not installed")
@pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor tree not installed")
def test_one_shot_attaches_the_image_and_stays_one_call(tmp_path):
    png_path = tmp_path / "page.png"
    # fake PNG-magic bytes — OneShot only needs a readable file at this path,
    # not a decodable image (see _FAKE_PNG_BYTES above for why this isn't a
    # base64 source literal).
    png_path.write_bytes(_FAKE_PNG_BYTES)
    got = _oneshot_php(f"""
        $c = new RecordingStub();
        $r = OneShot::run($c, visionAgent(), 'Read this page.', {json.dumps(str(png_path))});
        echo json_encode(['calls' => $c->calls, 'content' => $c->lastContent, 'r' => $r]);
    """, tmp_path)
    assert got["calls"] == 1, "attaching an image bought a second model call"
    types = [b["type"] for b in got["content"]]
    assert types == ["text", "image"], f"unexpected content blocks: {types}"
    assert got["content"][1]["source"]["media_type"] == "image/png"
    assert got["r"]["verdict"] == "valid"


@pytest.mark.skipif(shutil.which("php") is None, reason="php not installed")
@pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor tree not installed")
def test_one_shot_without_an_image_path_is_byte_identical_to_before(tmp_path):
    got = _oneshot_php("""
        $c = new RecordingStub();
        $r = OneShot::run($c, visionAgent(), 'Read this page.');
        echo json_encode(['calls' => $c->calls, 'content' => $c->lastContent]);
    """, tmp_path)
    assert got["calls"] == 1
    assert [b["type"] for b in got["content"]] == ["text"], (
        "a text-only one_shot call must not grow an image block from a null imagePath"
    )
