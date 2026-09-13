"""A live AgentKit turn must send state/cortex-lang.gbnf, or this stays red.

WHY THIS GATE EXISTS. Constrained decoding is what makes a small local model
unable to emit a syntax error. The GBNF lives at state/cortex-lang.gbnf and
is loaded today by tools/local-model-bench.py --grammar (llama-server), not
by the production path:

    files/anatomy/ears/caddy.py
      -> tools/run-agent.sh
      -> bin/run-agent.php / AgentKit
      -> OpenAiCompatAdapter
      -> POST {ollama}/v1/chat/completions

MEASURED 2026-09-13 (ollama 0.33.3, hermes3:8b): native /api/generate,
/api/chat, and the OpenAI surface all DROP a grammar key and answer
byte-identically. A second adapter aimed at /api/generate would not constrain
decoding. See docs/plans/ollama-gbnf-openai-compat.md.

This file therefore asserts the wire a real send() emits, not a comment.
Until OpenAiCompatAdapter (or a successor that actually honours GBNF) puts
the file contents on the request, the test fails — that is the pin, not an
oversight. Do not xfail it. Do not satisfy it by mentioning the filename
in a comment.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GRAMMAR = REPO / "state/cortex-lang.gbnf"
ADAPTER = REPO / "files/anatomy/wing/app/AgentKit/LLMClient/OpenAiCompatAdapter.php"
BENCH = REPO / "tools/local-model-bench.py"
CADDY = REPO / "files/anatomy/ears/caddy.py"
RUNNER = REPO / "tools/run-agent.sh"
AUTOLOAD = REPO / "files/anatomy/wing/vendor/autoload.php"
NOTE = REPO / "docs/plans/ollama-gbnf-openai-compat.md"

_COMMENT = re.compile(r"/\*.*?\*/|//.*?$", re.S | re.M)

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

$gbnf = file_get_contents($argv[2]);
$binding = new Binding(
    name: 'ollama',
    baseUrl: 'http://127.0.0.1:11434/v1',
    authToken: 'ollama',
    modelId: 'hermes3:8b',
);
$history = [];
$mock = new MockHandler([new Response(200, [], json_encode([
    'choices' => [['message' => ['content' => 'Hello!'], 'finish_reason' => 'stop']],
    'usage' => ['prompt_tokens' => 1, 'completion_tokens' => 1],
]))]);
$stack = HandlerStack::create($mock);
$stack->push(Middleware::history($history));
$http = new HttpClient(['handler' => $stack, 'http_errors' => true]);
$adapter = new OpenAiCompatAdapter($http, 'openai-sonnet', $binding);
$adapter->send('system', [Message::userText('Say hello.')], [], 64);
$body = json_decode((string) $history[0]['request']->getBody(), true);
$grammar = $body['grammar'] ?? null;
echo json_encode([
    'url' => (string) $history[0]['request']->getUri(),
    'has_grammar' => is_string($grammar) && $grammar !== '',
    'grammar_matches_file' => $grammar === $gbnf,
    'body_keys' => array_keys($body),
]);
"""


def _php_code(path: Path) -> str:
    return _COMMENT.sub("", path.read_text(encoding="utf-8"))


def test_the_gbnf_and_the_measurement_note_exist():
    assert GRAMMAR.is_file(), "state/cortex-lang.gbnf is the grammar a turn must send"
    assert NOTE.is_file(), (
        "the OpenAI-compat limitation has no measurement note at "
        f"{NOTE.relative_to(REPO)}"
    )


def test_the_bench_still_loads_the_gbnf():
    """The one consumer that has been shown to constrain decoding."""
    bench = BENCH.read_text(encoding="utf-8")
    assert "cortex-lang.gbnf" in bench and "GRAMMAR" in bench


def test_the_production_path_is_compat_chat_completions():
    """caddy -> run-agent.sh -> OpenAiCompatAdapter -> /chat/completions."""
    assert CADDY.is_file() and "run-agent.sh" in CADDY.read_text(encoding="utf-8")
    assert RUNNER.is_file() and "run-agent.php" in RUNNER.read_text(encoding="utf-8")
    src = _php_code(ADAPTER)
    assert "/chat/completions" in src


def test_adapter_send_code_loads_the_gbnf():
    """Fails until send() actually names the file (comments stripped). No PHP needed."""
    src = _php_code(ADAPTER)
    assert "cortex-lang.gbnf" in src, (
        "OpenAiCompatAdapter::send() still does not load state/cortex-lang.gbnf. "
        "caddy -> run-agent.sh -> AgentKit therefore emits unconstrained cortex-lang. "
        "Measured 2026-09-13: ollama 0.33.3 drops grammar on /api/generate and on "
        "/v1/chat/completions — a second adapter would not help, and stuffing the "
        "filename into a comment must not turn this green. See "
        "docs/plans/ollama-gbnf-openai-compat.md."
    )


@pytest.fixture(scope="module")
def ollama_turn(tmp_path_factory):
    php = shutil.which("php")
    if php is None or not AUTOLOAD.is_file():
        pytest.skip(
            "php binary or wing vendor/autoload.php missing — run `composer "
            "install` in files/anatomy/wing"
        )
    tmp = tmp_path_factory.mktemp("cortex-grammar-wire")
    harness = tmp / "harness.php"
    harness.write_text(_HARNESS)
    out = subprocess.run(
        [php, str(harness), str(AUTOLOAD), str(GRAMMAR)],
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, f"harness died: {out.stderr[-800:]}"
    return json.loads(out.stdout)


def test_an_ollama_send_puts_the_gbnf_on_the_wire(ollama_turn):
    v = ollama_turn
    assert v["url"].endswith("/chat/completions"), v
    assert v["has_grammar"] is True and v["grammar_matches_file"] is True, (
        "a real OpenAiCompatAdapter send() on the ollama binding still has no "
        f"GBNF on the body (keys={v.get('body_keys')}). Production therefore "
        "cannot constrain cortex-lang. Measured 2026-09-13: ollama 0.33.3 "
        "drops grammar on /api/generate and on /v1/chat/completions, so do not "
        "add a second adapter or a dropped key to turn this green. Wire a "
        "backend that honours GBNF (llama-server --grammar-file is the one "
        "already measured), then this send() must carry state/cortex-lang.gbnf. "
        "See docs/plans/ollama-gbnf-openai-compat.md."
    )
