"""agents_backend: a host binds every AgentKit agent to one row — a choice, never a fallback.

MEASURED 2026-10-16 on a client host (ollama on, minimax off): the converge held five
agent jobs for "minimax backend not armed" although the operator wants them on the
local Ollama (ruling 2026-10-16, mirroring iris_backend). The knob reaches Wing as
NOS_AGENTS_BACKEND; the readiness judge and BindingResolver read the same rule. An
agent whose record forbids the row is refused by name, never silently rebound.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
AUTOLOAD = REPO / "files/anatomy/wing/vendor/autoload.php"
REBOUND = ("librarian:judge-lint-queue", "librarian:brief-taxonomy",
           "librarian:describe-taxonomy", "surveyor:surface-survey", "conductor:self-test-001")


def _judge():
    spec = importlib.util.spec_from_file_location("_job_readiness_ab", REPO / "tools/job_readiness.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_job_readiness_ab"] = mod
    spec.loader.exec_module(mod)
    return mod


# The client host: ollama on with qwen3.5:9b, minimax off, no claude CLI.
CFG = {"ollama_enabled": "true", "ollama_model": "qwen3.5:9b", "ollama_small_model": "qwen3.5:9b",
       "ollama_vision_model": "", "minimax_enabled": "false", "minimax_model": "",
       "install_claude_cli_vendor": "false", "llm_cell_min_params_b": "8", "agents_backend": "ollama"}
HOST = {"claude": None, "ollama_models": {"qwen3.5:9b"}, "anthropic_key": False}


def _needs(job_id, **cfg):
    j = _judge()
    return j.job_needs(j.catalog()[job_id], {**CFG, **cfg}, HOST)


def test_readiness_holds_nothing_when_the_chosen_backend_is_ready():
    for jid in REBOUND:
        assert _needs(jid) == [], f"{jid} held although agents_backend: ollama is ready"


def test_readiness_holds_a_chosen_backend_that_is_not_ready():
    assert _needs("librarian:judge-lint-queue", ollama_enabled="false"), "a choice never degrades"
    got = _needs("librarian:judge-lint-queue", ollama_model="qwen3:4b")
    assert got and "llm_cell_min_params_b" in got[0], got


def test_a_forbidden_agent_is_refused_by_name():
    j = _judge()
    for name in ("proposer", "upgrade-architect"):    # record names no on-device / claude CLI
        got = j.agent_needs(name, CFG, HOST)
        assert len(got) == 1 and f"'{name}'" in got[0] and "agents_backend" in got[0], got


def test_the_default_is_each_agents_declared_backend():
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity
    assert nos_identity.default_config()["agents_backend"] == ""
    got = _needs("librarian:judge-lint-queue", agents_backend="")
    assert len(got) == 1 and got[0].startswith("minimax backend not armed"), got


def test_wing_plist_renders_the_knob():
    plist = (REPO / "roles/pazny.wing/templates/wing.plist.j2").read_text()
    assert re.search(r"<key>NOS_AGENTS_BACKEND</key>\s*<string>\{\{\s*agents_backend\b", plist)


_HARNESS = r"""<?php
declare(strict_types=1);
require $argv[1];
use App\AgentKit\AgentLoader;
use App\AgentKit\LLMClient\BindingRefused;
use App\AgentKit\LLMClient\BindingResolver;
use App\AgentKit\LLMClient\Factory;
use App\AgentKit\Vault\CredentialResolver;

class_exists(App\AgentKit\Agent::class);   // Agent.php also declares ToolSpec (see test_every_agent_manifest_loads)
$cred = (new ReflectionClass(CredentialResolver::class))->newInstanceWithoutConstructor();
$resolver = new BindingResolver($cred, $argv[3] . '/state/habitat/llm-backends.yml');
$loader = new AgentLoader($argv[2]);
$out = [];
$try = function (string $label, string $agent, string $env) use (&$out, $resolver, $loader, $cred) {
    foreach (['NOS_AGENTS_BACKEND', 'NOS_ARMED_BACKENDS'] as $k) { putenv($k); }
    foreach (array_filter(explode(' ', $env)) as $kv) { putenv($kv); }
    try {
        $a = $loader->load($agent);
        $d = $resolver->resolve($a);
        $uri = $d->uri ?? $a->modelPrimaryUri;
        $out[$label] = ['backend' => $d->backendName(), 'disarmed' => $d->declaredDisarmed,
            'model' => $d->binding?->modelId, 'uri' => $uri,
            'adapter' => $d->binding ? (new Factory($cred))->fromUri($uri, $d->binding)->identifier() : null];
    } catch (BindingRefused $e) {
        $out[$label] = ['refused' => $e->getMessage()];
    } catch (Throwable $e) {
        $out[$label] = ['error' => get_class($e) . ': ' . $e->getMessage()];
    }
};
$try('chosen', 'librarian', 'NOS_AGENTS_BACKEND=ollama NOS_ARMED_BACKENDS=ollama NOS_LOCAL_MODEL=qwen3.5:9b');
$try('chosen_disarmed', 'librarian', 'NOS_AGENTS_BACKEND=ollama');
$try('forbidden', 'proposer', 'NOS_AGENTS_BACKEND=ollama NOS_ARMED_BACKENDS=ollama');
$try('claude_cli', 'upgrade-architect', 'NOS_AGENTS_BACKEND=ollama NOS_ARMED_BACKENDS=ollama');
$try('default', 'librarian', 'NOS_ARMED_BACKENDS=ollama');
echo json_encode($out);
"""


@pytest.fixture(scope="module")
def php(tmp_path_factory):
    if shutil.which("php") is None or not AUTOLOAD.is_file():
        pytest.skip("php or wing vendor/autoload.php missing — composer install in files/anatomy/wing")
    harness = tmp_path_factory.mktemp("agents-backend") / "h.php"
    harness.write_text(_HARNESS)
    out = subprocess.run([shutil.which("php"), str(harness), str(AUTOLOAD),
                          str(REPO / "files/anatomy/agents"), str(REPO)],
                         capture_output=True, text=True, timeout=120,
                         env={"NOS_REPO_ROOT": str(REPO), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr[-800:]
    return json.loads(out.stdout)


def test_the_binding_resolves_to_the_chosen_row(php):
    assert php["chosen"] == {"backend": "ollama", "disarmed": None, "model": "qwen3.5:9b",
                             "uri": "openai-sonnet", "adapter": "openai-sonnet"}, php["chosen"]
    assert "not armed" in php["chosen_disarmed"].get("refused", ""), php["chosen_disarmed"]


def test_the_resolver_refuses_a_forbidden_agent_by_name(php):
    for label, name in (("forbidden", "proposer"), ("claude_cli", "upgrade-architect")):
        why = php[label].get("refused", "")
        assert f"'{name}'" in why and "agents_backend" in why, php[label]


def test_the_resolver_default_is_the_declared_backend(php):
    assert php["default"]["disarmed"] == "minimax", php["default"]
