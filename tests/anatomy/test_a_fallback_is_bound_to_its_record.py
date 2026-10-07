"""A fallback is BOUND, to a registry row its own Article-30 record names.

MEASURED 2026-10-01: surveyor:surface-survey failed. MiniMax (the bound
primary) threw a transient "Connection Error", the run fell back to
`openclaw-qwen2.5-coder:32b`, and OpenClaw 2026.7.1 answered 404 — its
gateway never served the /v1/messages shape the old adapter spoke. All seven
fallback-declaring agents named that same dead URI, so every transient
primary error was a hard failure.

The fix keeps the 2026-08-16 residency property (a MiniMax-bound session must
not fall back to a party its record does not name) by making the fallback a
binding: `model.fallback_backend` goes through the same BindingResolver gates
as `model.backend`, never degrades to the default, and the loader refuses a
fallback backend the agent's gdpr.processors does not cover.

Executed, not grepped: the PHP below runs the real loader, resolver, factory
and Runner::fallbackClient. No network — nothing calls send().
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402
WING = REPO / "files/anatomy/wing"
AUTOLOAD = WING / "vendor/autoload.php"
AGENTS = REPO / "files/anatomy/agents"
REGISTRY = REPO / "state/habitat/llm-backends.yml"

_HARNESS = r"""<?php
declare(strict_types=1);
require $argv[1];
class_exists(App\AgentKit\Agent::class);

use App\AgentKit\Agent;
use App\AgentKit\AgentLoader;
use App\AgentKit\Runner;
use App\AgentKit\LLMClient\Binding;
use App\AgentKit\LLMClient\BindingResolver;
use App\AgentKit\LLMClient\Factory;
use App\AgentKit\Vault\CredentialResolver;

[$_, $_a, $tmpAgents, $realAgents] = $argv;
$creds = (new ReflectionClass(CredentialResolver::class))->newInstanceWithoutConstructor();
$resolver = new BindingResolver($creds);
$factory = new Factory($creds);

const MINIMAX_AND_LOCAL = ['processors' => [
    ['name' => 'MiniMax'], ['name' => "on-device (operator's own hardware)"],
], 'transfers_outside_eu' => true];

function agent(array $o = []): Agent {
    return new Agent(
        name: 'probe', version: 1, description: 'fallback probe',
        modelPrimaryUri: 'anthropic-claude-sonnet-4-5',
        modelFallbackUri: $o['fallback'] ?? 'openai-local-haiku',
        modelGraderUri: null, systemPrompt: null, tools: [], rubric: null,
        maxIterations: 1, capabilityScopes: [], piiClassification: 'none',
        requiredCredentials: [], subscriptions: [], metadata: [], sourceDir: '/x',
        backendName: 'minimax', gdpr: $o['gdpr'] ?? MINIMAX_AND_LOCAL,
        fallbackBackendName: array_key_exists('fb', $o) ? $o['fb'] : 'ollama',
    );
}

/** A Runner mid-session, bound to minimax — only what fallbackClient reads. */
function runner(Factory $f, BindingResolver $r): Runner {
    $ref = new ReflectionClass(Runner::class);
    $run = $ref->newInstanceWithoutConstructor();
    $ref->getProperty('llmFactory')->setValue($run, $f);
    $ref->getProperty('bindingResolver')->setValue($run, $r);
    $ref->getProperty('activeBinding')->setValue($run,
        new Binding('minimax', 'https://api.minimax.io/anthropic', 'fake', 'FAKE-M2'));
    return $run;
}

$out = [];
$try = function (string $label, callable $fn) use (&$out) {
    try { $out[$label] = $fn(); }
    catch (Throwable $e) { $out[$label] = ['refused' => get_class($e) . ': ' . $e->getMessage()]; }
};
$serve = function (Agent $a) use ($factory, $resolver) {
    $m = new ReflectionMethod(Runner::class, 'fallbackClient');
    $c = $m->invoke(runner($factory, $resolver), $a);
    $b = (new ReflectionObject($c))->getProperty('binding')->getValue($c);
    return ['class' => (new ReflectionClass($c))->getShortName(),
            'backend' => $b->name, 'base_url' => $b->baseUrl, 'model' => $b->modelId];
};

putenv('NOS_ARMED_BACKENDS=minimax ollama openclaw');
putenv('NOS_LOCAL_SMALL_MODEL=FAKE-small');
putenv('NOS_OPENCLAW_AGENT=openclaw/default');

$try('bound_session_bound_fallback', fn () => $serve(agent()));
$try('fallback_disarmed', function () use ($serve) {
    putenv('NOS_ARMED_BACKENDS=minimax');
    try { return $serve(agent()); } finally { putenv('NOS_ARMED_BACKENDS=minimax ollama openclaw'); }
});
$try('bound_session_unbound_bindable_fallback', fn () => $serve(agent(['fb' => null])));
$try('record_does_not_name_it_at_session', fn () => $serve(agent([
    'gdpr' => ['processors' => [['name' => 'MiniMax']], 'transfers_outside_eu' => true],
])));
$try('openclaw_bound', fn () => $serve(agent([
    'fallback' => 'openclaw-sonnet', 'fb' => 'openclaw',
    'gdpr' => ['processors' => [['name' => 'MiniMax'], ['name' => 'OpenClaw gateway (this host)']]],
])));

// ── The loader: refused at LOAD, before any session exists ──────────────────
$load = fn (string $name) => (function () use ($tmpAgents, $name) {
    $a = (new AgentLoader($tmpAgents))->load($name);
    return ['fallback_backend' => $a->fallbackBackendName];
})();
foreach (['ok-bound', 'no-local-processor', 'unbound', 'default-row', 'unknown-row', 'eu-record-us-row'] as $n) {
    $try("load_$n", fn () => $load($n));
}

// ── Every committed agent: its fallback resolves to a live registry row ─────
$real = new AgentLoader($realAgents);
foreach ($real->listAvailable() as $n) {
    $try("real_$n", function () use ($real, $resolver, $n) {
        $a = $real->load($n);
        if ($a->modelFallbackUri === null) { return ['fallback' => null]; }
        $b = $resolver->resolveFallback($a);
        return ['fallback' => $a->modelFallbackUri, 'backend' => $b->name, 'model' => $b->modelId];
    });
}
echo json_encode($out);
"""

_BASE = {
    "version": 1,
    "description": "fallback loader probe",
    "audit": {"capability_scopes": ["llm.call"], "pii_classification": "none"},
}
_LOCAL = {"name": "on-device (operator's own hardware)", "role": "x", "country": "CZ"}
_MINIMAX = {"name": "MiniMax", "role": "x", "country": "unverified"}
_VARIANTS = {
    "ok-bound": ({"fallback": "openai-local-haiku", "fallback_backend": "ollama"},
           {"processors": [_MINIMAX, _LOCAL], "transfers_outside_eu": True}),
    "no-local-processor": ({"fallback": "openai-local-haiku", "fallback_backend": "ollama"},
                           {"processors": [_MINIMAX], "transfers_outside_eu": True}),
    "unbound": ({"fallback": "openai-local-haiku"},
                {"processors": [_MINIMAX, _LOCAL], "transfers_outside_eu": True}),
    "default-row": ({"fallback": "claude-sonnet", "fallback_backend": "anthropic"},
                    {"processors": [_MINIMAX, {"name": "Anthropic, PBC"}]}),
    "unknown-row": ({"fallback": "openai-local-haiku", "fallback_backend": "nosuch"},
                    {"processors": [_MINIMAX, _LOCAL]}),
    "eu-record-us-row": ({"fallback": "anthropic-claude-haiku-4-5", "fallback_backend": "minimax"},
                         {"processors": [_LOCAL, _MINIMAX], "transfers_outside_eu": False}),
}


@pytest.fixture(scope="module")
def verdicts(tmp_path_factory):
    if shutil.which("php") is None or not AUTOLOAD.is_file():
        pytest.skip("php or files/anatomy/wing/vendor/autoload.php missing — composer install")
    tmp = tmp_path_factory.mktemp("fallback")
    agents = tmp / "agents"
    for name, (model_extra, gdpr) in _VARIANTS.items():
        d = agents / name
        d.mkdir(parents=True)
        doc = dict(_BASE, name=name,
                   model={"primary": "anthropic-claude-sonnet-4-5", **model_extra},
                   gdpr=gdpr)
        (d / "agent.yml").write_text(yaml.safe_dump(doc))
    home = tmp / "home"
    (home / ".nos").mkdir(parents=True)
    (home / ".nos/secrets.yml").write_text('openclaw_gateway_token: "fake-gateway-token-for-harness"\n')
    harness = tmp / "harness.php"
    harness.write_text(_HARNESS)
    php = shutil.which("php")
    out = subprocess.run(
        [php, str(harness), str(AUTOLOAD), str(agents), str(AGENTS)],
        capture_output=True, text=True, timeout=120,
        env={"HOME": str(home), "NOS_REPO_ROOT": str(REPO),
             "PATH": f"{Path(php).parent}:/usr/bin:/bin"},
    )
    assert out.returncode == 0, f"harness died: {out.stdout[-400:]}{out.stderr[-800:]}"
    return json.loads(out.stdout)


def _refused(v, needle):
    return isinstance(v, dict) and "refused" in v and needle in v["refused"]


def test_a_bound_fallback_is_served_bound_to_its_declared_backend(verdicts):
    assert verdicts["bound_session_bound_fallback"] == {
        "class": "OpenAiCompatAdapter", "backend": "ollama",
        "base_url": "http://127.0.0.1:11434/v1", "model": "FAKE-small",
    }, f"the fallback was not built on the ollama binding: {verdicts['bound_session_bound_fallback']!r}"


def test_a_fallback_never_degrades_to_the_default(verdicts):
    v = verdicts["fallback_disarmed"]
    assert _refused(v, "not armed"), (
        f"a disarmed fallback backend did not refuse: {v!r} — it would have "
        "answered unbound, from the default backend the record may not name"
    )
    v = verdicts["bound_session_unbound_bindable_fallback"]
    assert _refused(v, "UNBOUND"), f"a bound session served an unbound bindable fallback: {v!r}"
    v = verdicts["record_does_not_name_it_at_session"]
    assert _refused(v, "never names 'on-device'"), (
        f"a fallback backend the record does not name was served at session time: {v!r}"
    )


def test_a_fallback_backend_outside_the_record_is_refused_at_load(verdicts):
    assert verdicts["load_ok-bound"] == {"fallback_backend": "ollama"}, verdicts["load_ok-bound"]
    for label, needle in (
        ("load_no-local-processor", "never names 'on-device'"),
        ("load_unbound", "come together"),
        ("load_default-row", "default backend"),
        ("load_unknown-row", "not a row"),
        ("load_eu-record-us-row", "not EU-resident"),
    ):
        assert _refused(verdicts[label], needle), (
            f"{label}: expected an AgentLoadException naming {needle!r}, got {verdicts[label]!r}"
        )


def test_every_declared_fallback_resolves_to_a_known_backend(verdicts):
    """No dead URIs: each committed fallback binds, with every row armed."""
    reals = {k[5:]: v for k, v in verdicts.items() if k.startswith("real_")}
    assert len(reals) >= 7, f"only {len(reals)} agents loaded — the sweep is vacuous"
    bad = {n: v for n, v in reals.items() if "refused" in v}
    assert not bad, f"agent(s) whose fallback does not resolve: {bad}"
    bound = {n: v for n, v in reals.items() if v.get("fallback")}
    assert len(bound) >= 6, f"expected the six hosted-primary agents to carry a fallback, got {bound}"
    registry = yaml.safe_load(REGISTRY.read_text())["backends"]
    assert all(v["backend"] in registry for v in bound.values())


def test_the_local_fallback_model_is_pinned_and_small():
    """The haiku tier an ollama fallback reads must be set, and must not be the
    14B that starves KEAP (memory: local-model-budget-on-this-host)."""
    cfg = ni.default_config()
    model = cfg.get("ollama_small_model") or ""
    sizes = (yaml.safe_load(REGISTRY.read_text())["backends"]["ollama"].get("sizes_b") or {})
    assert model, "ollama_small_model is empty — every ollama fallback refuses 'armed without a model id'"
    assert model == sizes.get(8), f"ollama_small_model {model!r} is not the registry's 8B rung {sizes.get(8)!r}"


def test_the_openclaw_row_binds_through_the_openai_surface(verdicts):
    assert verdicts["openclaw_bound"] == {
        "class": "OpenAiCompatAdapter", "backend": "openclaw",
        "base_url": "http://127.0.0.1:18789/v1", "model": "openclaw/default",
    }, f"openclaw-* did not bind to the gateway's OpenAI surface: {verdicts['openclaw_bound']!r}"
