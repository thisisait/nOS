"""The binding resolver's six gates, exercised — and ruling 3 at the argv line.

WHY EFFECTS AND NOT SHAPE. The companion gate
(test_a_binding_reads_the_register.py) holds the DECLARED DATA to the rules;
this one runs the actual PHP — `BindingResolver::resolve()` against the real
state/llm-backends.yml, and `ClaudeCliAdapter::send()` against a fake `claude`
binary that records what it was given. The distinction matters because the
resolver is exactly the kind of machinery that can be visible in source and
absent from behaviour (the MapHandler defect, twice corrected in this
codebase): a rule asserted by regex can be dead code; a rule that throws in a
subprocess is alive.

RULING 3, MEASURED AT THE ARGV: `--model` outranks ANTHROPIC_MODEL, so an
adapter that passed both would silently undo the binding's remap — the exact
gotcha docs/minimax-groundwork.md records. The fake binary dumps its argv and
env; the assertion is that under a binding there is NO --model and the three
ANTHROPIC_* envs are present, and without a binding --model is passed and the
envs are absent. Both directions, so neither can rot into the other.

SKIP HONESTY: the harness needs the local `php` binary and the wing vendor
autoload (composer install). Absent either, this SKIPS with a pointer — the
data-side gate still runs everywhere, and a skip that names its missing tool
is the journeys-conftest contract, not a hidden switch-off.

No real secret appears: the harness HOME is a tmp dir whose secrets.yml holds
a placeholder-marked fake value.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
AUTOLOAD = WING / "vendor/autoload.php"

_HARNESS = r"""<?php
declare(strict_types=1);
require $argv[1]; // vendor/autoload.php

use App\AgentKit\Agent;
use App\AgentKit\LLMClient\Binding;
use App\AgentKit\LLMClient\BindingRefused;
use App\AgentKit\LLMClient\BindingResolver;
use App\AgentKit\LLMClient\ClaudeCliAdapter;
use App\AgentKit\LLMClient\Message;
use App\AgentKit\Vault\CredentialResolver;

[$_, $autoload, $registryPath, $fakeClaude, $probeDir] = $argv;

function agent(array $over = []): Agent {
    $gdpr = $over['gdpr'] ?? ['processors' => [
        ['name' => 'Anthropic, PBC'],
        ['name' => 'MiniMax (international API)'],
    ]];
    return new Agent(
        name: $over['name'] ?? 'probe-agent',
        version: 1,
        description: 'harness probe agent for the binding resolver',
        modelPrimaryUri: $over['primary'] ?? 'claude-sonnet',
        modelFallbackUri: null,
        modelGraderUri: null,
        systemPrompt: null,
        tools: [],
        multiagentType: 'solo',
        roster: [],
        maxConcurrentThreads: 1,
        rubric: null,
        maxIterations: 1,
        capabilityScopes: [],
        piiClassification: 'none',
        requiredCredentials: [],
        subscriptions: [],
        metadata: $over['metadata'] ?? [],
        sourceDir: '/nonexistent',
        backendName: $over['backend'] ?? null,
        gdpr: $gdpr,
    );
}

// CredentialResolver's ctor wants a DB-backed vault repository the `nos:`
// scheme never touches; instantiate without the ctor so the harness stays
// DB-free. Documented here because it is a liberty: if dereference() ever
// grows a vault dependency on the nos: path, this harness fails loudly.
$credentials = (new ReflectionClass(CredentialResolver::class))->newInstanceWithoutConstructor();
$resolver = new BindingResolver($credentials, $registryPath);

$out = [];
$try = function (string $label, callable $fn) use (&$out) {
    try {
        $out[$label] = $fn();
    } catch (BindingRefused $e) {
        $out[$label] = ['refused' => $e->getMessage()];
    } catch (Throwable $e) {
        $out[$label] = ['error' => get_class($e) . ': ' . $e->getMessage()];
    }
};

$try('no_declaration', fn () => ['backend' => $resolver->resolve(agent())->backendName()]);
$try('disarmed', function () use ($resolver) {
    putenv('NOS_ARMED_BACKENDS');
    $d = $resolver->resolve(agent(['backend' => 'minimax']));
    return ['backend' => $d->backendName(), 'declared_disarmed' => $d->declaredDisarmed];
});
$try('deferred', fn () => $resolver->resolve(agent([
    'backend' => 'minimax', 'metadata' => ['runner_status' => 'deferred'],
])));
$try('register_disagrees', fn () => $resolver->resolve(agent([
    'backend' => 'minimax',
    'gdpr' => ['processors' => [['name' => 'Anthropic, PBC']]],
])));
$try('opus_refused', fn () => $resolver->resolve(agent([
    'backend' => 'minimax', 'primary' => 'claude-opus',
])));
$try('armed_no_model', function () use ($resolver) {
    putenv('NOS_ARMED_BACKENDS=minimax');
    putenv('NOS_MINIMAX_MODEL');
    return $resolver->resolve(agent(['backend' => 'minimax']));
});
$try('armed_bound', function () use ($resolver) {
    putenv('NOS_ARMED_BACKENDS=minimax');
    putenv('NOS_MINIMAX_MODEL=FAKE-MiniMax-M2');
    $d = $resolver->resolve(agent(['backend' => 'minimax']));
    $b = $d->binding;
    return [
        'backend' => $d->backendName(),
        'base_url' => $b?->baseUrl,
        'model_id' => $b?->modelId,
        'token_present' => $b !== null && $b->authToken !== '',
    ];
});

// ── The API path (spine redirect 2026-08-15) ────────────────────────────────
// The operator's direction: primarily the classic API, because AnthropicAdapter
// speaks the tool protocol and AgentKit's Runner drives the loop — the tools
// refusal dissolves instead of being worked around. These cases prove the
// bound construction WITHOUT a network call: what can be verified offline is
// which endpoint, which credential, which model the client was BUILT with;
// the request itself is the armed night's job.
use App\AgentKit\LLMClient\Factory;

$factory = new Factory($credentials);

$try('api_bound_builds_the_bound_client', function () use ($resolver, $factory) {
    putenv('NOS_ARMED_BACKENDS=minimax');
    putenv('NOS_MINIMAX_MODEL=FAKE-MiniMax-M2');
    $d = $resolver->resolve(agent([
        'backend' => 'minimax', 'primary' => 'anthropic-claude-sonnet-4-5',
    ]));
    $adapter = $factory->fromUri('anthropic-claude-sonnet-4-5', $d->binding);

    // Reflection over the built client: baseUrl, bearer-vs-apiKey, model id.
    $ref = new ReflectionObject($adapter);
    $clientProp = $ref->getProperty('client');
    $client = $clientProp->getValue($adapter);
    $modelProp = $ref->getProperty('modelId');

    $props = [];
    for ($c = new ReflectionObject($client); $c !== false; $c = $c->getParentClass()) {
        foreach ($c->getProperties() as $p) {
            if (!array_key_exists($p->getName(), $props) && $p->isInitialized($client)) {
                $props[$p->getName()] = $p->getValue($client);
            }
        }
    }
    // The base URL may be stored as a string or a PSR-7 UriInterface —
    // stringify whatever can be stringified before searching.
    $strings = [];
    foreach ($props as $v) {
        if (is_string($v)) { $strings[] = $v; }
        elseif (is_object($v) && method_exists($v, '__toString')) { $strings[] = (string) $v; }
    }
    return [
        'backend' => $adapter->backendName(),
        'model_id' => $modelProp->getValue($adapter),
        'base_url_bound' => (bool) array_filter($strings, fn ($v) => str_contains($v, 'api.minimax.io')),
        'bearer_set' => ($props['authToken'] ?? '') !== '',
        'api_key_empty' => ($props['apiKey'] ?? 'MISSING') === '',
    ];
});

$try('api_opus_tier_refused', function () use ($resolver) {
    putenv('NOS_ARMED_BACKENDS=minimax');
    return $resolver->resolve(agent([
        'backend' => 'minimax', 'primary' => 'anthropic-claude-opus-4-7',
    ]));
});

$try('factory_refuses_openclaw_binding', function () use ($resolver, $factory) {
    putenv('NOS_ARMED_BACKENDS=minimax');
    putenv('NOS_MINIMAX_MODEL=FAKE-MiniMax-M2');
    $d = $resolver->resolve(agent(['backend' => 'minimax']));
    try {
        $factory->fromUri('openclaw-qwen2.5-coder:32b', $d->binding);
        return ['accepted' => true];
    } catch (InvalidArgumentException $e) {
        return ['refused' => $e->getMessage()];
    }
});

$try('api_unbound_still_requires_the_key', function () use ($factory) {
    putenv('ANTHROPIC_API_KEY');
    try {
        $factory->fromUri('anthropic-claude-sonnet-4-5');
        return ['built' => true];
    } catch (RuntimeException $e) {
        return ['refused' => $e->getMessage()];
    }
});

// Ruling 3 at the argv line, both directions.
$send = function (?Binding $binding) use ($fakeClaude, $probeDir) {
    @unlink("$probeDir/claude-args");
    @unlink("$probeDir/claude-env");
    $adapter = new ClaudeCliAdapter('claude-sonnet', 'sonnet', $fakeClaude, 30, $binding);
    $adapter->send('', [Message::userText('probe')], [], 64);
    return [
        'args' => file_get_contents("$probeDir/claude-args") ?: '',
        'env' => file_get_contents("$probeDir/claude-env") ?: '',
    ];
};
$try('adapter_unbound', fn () => $send(null));
$try('adapter_bound', fn () => $send(new Binding(
    name: 'minimax',
    baseUrl: 'https://api.minimax.example/anthropic',
    authToken: 'fake-token-for-the-harness',
    modelId: 'FAKE-MiniMax-M2',
)));

echo json_encode($out);
"""

_FAKE_CLAUDE = """#!/usr/bin/env bash
printf '%s\\n' "$@" > "$NOS_PROBE_DIR/claude-args"
env > "$NOS_PROBE_DIR/claude-env"
printf '%s' '{"result":"ok","usage":{"input_tokens":1,"output_tokens":1}}'
"""


@pytest.fixture(scope="module")
def verdicts(tmp_path_factory):
    if shutil.which("php") is None or not AUTOLOAD.is_file():
        pytest.skip(
            "php binary or wing vendor/autoload.php missing — run `composer "
            "install` in files/anatomy/wing; the data-side gate "
            "(test_a_binding_reads_the_register.py) still covers the rules"
        )
    tmp = tmp_path_factory.mktemp("binding")
    probe = tmp / "probe"
    probe.mkdir()
    fake = tmp / "claude"
    fake.write_text(_FAKE_CLAUDE)
    fake.chmod(0o755)
    home = tmp / "home"
    (home / ".nos").mkdir(parents=True)
    (home / ".nos/secrets.yml").write_text('minimax_api_key: "fake-key-value-for-harness"\n')
    harness = tmp / "harness.php"
    harness.write_text(_HARNESS)
    php = shutil.which("php")
    out = subprocess.run(
        [php, str(harness), str(AUTOLOAD),
         str(REPO / "state/llm-backends.yml"), str(fake), str(probe)],
        capture_output=True, text=True, timeout=120,
        # Minimal env ON PURPOSE: no NOS_ARMED_BACKENDS inherited from the
        # operator's shell, so the harness's own putenv() calls are the only
        # arming that exists. PATH keeps php's own dir for any sub-spawns.
        env={"HOME": str(home),
             "PATH": f"{Path(php).parent}:/usr/bin:/bin",
             "NOS_PROBE_DIR": str(probe)},
    )
    assert out.returncode == 0, f"harness died: {out.stderr[-800:]}"
    return json.loads(out.stdout)


def test_the_default_and_the_disarmed_path(verdicts):
    assert verdicts["no_declaration"] == {"backend": "anthropic"}
    assert verdicts["disarmed"] == {
        "backend": "anthropic", "declared_disarmed": "minimax",
    }, (
        "declared-but-disarmed must serve on the default backend AND say which "
        "backend was asked for — silent degradation is indistinguishable from "
        "never having asked"
    )


def test_every_refusal_refuses_for_its_own_reason(verdicts):
    for label, needle in (
        ("deferred", "deferred"),
        ("register_disagrees", "never names"),
        ("opus_refused", "no model mapping"),
        ("armed_no_model", "empty"),
    ):
        v = verdicts[label]
        assert isinstance(v, dict) and "refused" in v, (
            f"{label}: expected a BindingRefused, got {v!r} — a gate that "
            "stopped throwing is a routing the register no longer guards"
        )
        assert needle in v["refused"], (
            f"{label}: refusal message {v['refused']!r} lost its reason "
            f"({needle!r}) — the operator debugging a refused session reads "
            "this message and nothing else"
        )


def test_an_armed_binding_resolves_from_registry_and_secrets(verdicts):
    assert verdicts["armed_bound"] == {
        "backend": "minimax",
        "base_url": "https://api.minimax.io/anthropic",
        "model_id": "FAKE-MiniMax-M2",
        "token_present": True,
    }, (
        f"got {verdicts['armed_bound']!r} — the armed path must read base_url "
        "from state/llm-backends.yml, the model id from the tier env, and the "
        "token from ~/.nos/secrets.yml via nos:minimax_api_key"
    )


def test_the_api_path_builds_the_bound_client(verdicts):
    """The spine redirect's core claim, measured at construction.

    A MiniMax-served run is the ANTHROPIC adapter (the SDK speaks the wire
    protocol; the genome's provider enum stays untouched) built with the
    binding's endpoint and BEARER — never ANTHROPIC_API_KEY, which belongs to
    a different party — and the binding's tier-resolved model id. What this
    deliberately cannot prove: that a request round-trips. That is the armed
    night's job, and pretending otherwise here would be a success marker
    written by the attempting code.
    """
    v = verdicts["api_bound_builds_the_bound_client"]
    assert v == {
        "backend": "minimax",
        "model_id": "FAKE-MiniMax-M2",
        "base_url_bound": True,
        "bearer_set": True,
        "api_key_empty": True,
    }, f"bound client construction drifted: {v!r}"


def test_the_tier_carveout_follows_the_tier_not_the_provider(verdicts):
    v = verdicts["api_opus_tier_refused"]
    assert isinstance(v, dict) and "refused" in v and "opus" in v["refused"], (
        f"an opus-TIER agent routed through the API path was not refused: {v!r} "
        "— ruling 1's carve-out is about what the ceremony authors, and it "
        "must hold for every adapter, or switching provider becomes the "
        "bypass"
    )


def test_the_factory_still_refuses_what_cannot_bind(verdicts):
    v = verdicts["factory_refuses_openclaw_binding"]
    assert "refused" in v, (
        "the factory accepted a binding for openclaw, which speaks neither "
        "mechanism — the binding would be silently dropped (the MapHandler "
        "defect, again)"
    )
    unbound = verdicts["api_unbound_still_requires_the_key"]
    assert "refused" in unbound and "ANTHROPIC_API_KEY" in unbound["refused"], (
        "the UNBOUND anthropic path no longer demands its key — the bound "
        "branch weakened the ordinary one"
    )


def test_ruling_3_at_the_argv_line(verdicts):
    unbound = verdicts["adapter_unbound"]
    assert "--model" in unbound["args"], (
        "the unbound adapter no longer pins --model — bulk ceremonies inherit "
        "the operator's most expensive tier"
    )
    assert "ANTHROPIC_BASE_URL" not in unbound["env"]

    bound = verdicts["adapter_bound"]
    assert "--model" not in bound["args"], (
        "the bound adapter still passes --model, which OUTRANKS "
        "ANTHROPIC_MODEL — the binding's remap is silently undone and the "
        "Anthropic tier alias goes to a backend that does not know it "
        "(the arming gotcha docs/minimax-groundwork.md records)"
    )
    for needle in (
        "ANTHROPIC_BASE_URL=https://api.minimax.example/anthropic",
        "ANTHROPIC_AUTH_TOKEN=fake-token-for-the-harness",
        "ANTHROPIC_MODEL=FAKE-MiniMax-M2",
    ):
        assert needle in bound["env"], f"child env lost {needle.split('=')[0]}"
