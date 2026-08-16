"""`create(...$params)` spreads array keys as NAMED arguments. They must match.

MEASURED 2026-08-16, on the first real AgentKit session this estate has ever
run. `AnthropicAdapter` builds a string-keyed array and spreads it:

    $this->client->messages->create(...$params);

so every key is a PHP named parameter. The SDK signature is camelCase —
`create($maxTokens, $messages, $model, …)` — and the array said `max_tokens`:

    Anthropic SDK unexpected error: Unknown named parameter $max_tokens

WHAT MAKES IT WORTH A GATE rather than a one-line fix. The failure was
classified TRANSIENT (the classifier matches Anthropic's throttle phrasings and
defaults everything else to a retry-or-fallback path), so a permanent code
defect was retried three times and then fell back to the local model, which
answered 404. The session's visible outcome was "OpenClaw permanent error
(HTTP 404)" — a gateway that had done nothing wrong. It was only legible
because `agent_model_fallback` carries the unmatched message verbatim; that
event is four days old and this is what it was for.

A vendored SDK bump renaming a parameter would reproduce it exactly, and the
symptom would again point somewhere else. So this asks the SDK, by reflection,
what it is actually called.

SCOPE: the spread call sites in AgentKit, checked against the real vendored
class. Skips honestly when php/vendor are absent (CI without a composer
install) rather than passing on an assumption.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
ADAPTER = WING / "app/AgentKit/LLMClient/AnthropicAdapter.php"

pytestmark = pytest.mark.skipif(
    shutil.which("php") is None or not (WING / "vendor/autoload.php").is_file(),
    reason="php or the vendored SDK is not installed here",
)


def _params_array_keys() -> set[str]:
    """The keys AnthropicAdapter puts into the array it spreads."""
    src = ADAPTER.read_text(encoding="utf-8")
    start = src.index("$params = [")
    end = src.index("];", start)
    block = src[start:end]
    keys = set(re.findall(r"'([A-Za-z_][A-Za-z0-9_]*)'\s*=>", block))
    # Conditional additions further down, same array.
    tail = src[end: end + 800]
    keys |= set(re.findall(r"\$params\['([A-Za-z_][A-Za-z0-9_]*)'\]", tail))
    return keys


def _sdk_parameter_names() -> set[str]:
    code = (
        'require "vendor/autoload.php";'
        '$c = new Anthropic\\Client(apiKey: "x");'
        '$r = new ReflectionMethod($c->messages, "create");'
        '$out = [];'
        'foreach ($r->getParameters() as $p) { $out[] = $p->getName(); }'
        'echo json_encode($out);'
    )
    res = subprocess.run(
        ["php", "-r", code], capture_output=True, text=True, cwd=str(WING)
    )
    assert res.returncode == 0, f"could not reflect the SDK: {res.stderr[:300]}"
    return set(json.loads(res.stdout))


def test_the_extractor_found_the_spread_array():
    """Positive control — an empty key set would make the check below vacuous."""
    keys = _params_array_keys()
    assert len(keys) >= 3, (
        f"only {len(keys)} key(s) extracted from the $params array; the shape "
        "of AnthropicAdapter has changed and this gate is reading nothing."
    )
    assert "model" in keys, "the extractor no longer sees the array it guards"


def test_every_spread_key_is_a_real_sdk_parameter():
    sdk = _sdk_parameter_names()
    assert sdk, "the SDK reflected zero parameters"
    unknown = sorted(_params_array_keys() - sdk)
    assert not unknown, (
        "AnthropicAdapter spreads key(s) the SDK has no named parameter for: "
        f"{unknown}. Known SDK parameters: {sorted(sdk)}.\n"
        "PHP raises `Unknown named parameter $x` at CALL time, the adapter "
        "wraps it as a TRANSIENT error, and the run retries and then falls "
        "back — so the visible failure is the fallback backend, not this."
    )
