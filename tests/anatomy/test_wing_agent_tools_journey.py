"""One journey through Wing's AgentKit tools: loader, tool registry, tool sandbox, LLM transport.

Absorbed 2026-11-08 (roadmap gate-diet-role-journeys); every assert kept verbatim:
  test_a_regex_that_cannot_compile_says_no_to_everything  -> section REGEX
  test_bash_read_only_names_the_shell_habit               -> section SHELL HABIT
  test_an_agent_read_tool_cannot_write_or_exec            -> section READ TOOL SANDBOX
  test_every_registered_tool_actually_loads               -> section TOOL LOADS
  test_the_tool_enum_tracks_registration                  -> section TOOL ENUM
  test_the_sdk_named_parameters_match                     -> section SDK PARAMS
  test_multimodal_one_shot_transport                      -> section MULTIMODAL
  test_agentkit_files_present                             -> section SHIPPED FILES
  test_agentkit_runner_paths                              -> section RUNNER PATHS
Module-level skip marks of the originals now sit on their own section's tests.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
WING_APP = WING / "app"
AGENTKIT = WING_APP / "AgentKit"
TOOLS_DIR = AGENTKIT / "Tools"
AUTOLOAD = WING / "vendor/autoload.php"
COMMON_NEON = WING_APP / "config/common.neon"

NO_PHP = shutil.which("php") is None
NO_VENDOR_REASON = ("php binary or wing vendor/autoload.php missing — run `composer "
                    "install` in files/anatomy/wing")


# ── REGEX ───────────────────────────────────────────────────────────────────
# 2026-08-16, first real AgentKit session: isValidModelUri's `/`-delimited pattern
# did not compile, preg_match returned FALSE (= "no match"), and the loader refused
# EVERY agent. Every AgentKit regex literal is compiled by PHP; the validator must
# still say YES as well as NO.

#: `preg_*('…')` first argument, single-quoted PHP literal.
PREG = re.compile(r"preg_(?:match|match_all|replace|split|quote)\(\s*'((?:[^'\\]|\\.)*)'")


def _patterns() -> list[tuple[pathlib.Path, str]]:
    out = []
    for php in sorted(AGENTKIT.rglob("*.php")):
        for m in PREG.finditer(php.read_text(encoding="utf-8")):
            out.append((php, m.group(1)))
    return out


def test_the_sweep_finds_patterns():
    """Positive control: zero patterns would make the compile check vacuous."""
    found = _patterns()
    assert len(found) >= 3, (
        f"only {len(found)} regex literal(s) found under AgentKit; the "
        "extractor has stopped seeing them and this gate proves nothing."
    )


@pytest.mark.skipif(NO_PHP, reason="php not installed")
def test_every_agentkit_regex_compiles():
    """Ask PHP, not a Python approximation — the delimiter rules are PCRE's."""
    broken = []
    for path, pattern in _patterns():
        # The literal is single-quoted PHP; \' and \\ are its only escapes.
        php_literal = pattern.replace("\\", "\\\\").replace("'", "\\'")
        code = (
            "error_reporting(0);"
            f"$r = @preg_match('{php_literal}', 'x');"
            "echo $r === false ? 'BROKEN' : 'OK';"
        )
        res = subprocess.run(["php", "-r", code], capture_output=True, text=True)
        if res.stdout.strip() != "OK":
            broken.append(f"  {path.relative_to(REPO)}: {pattern}")
    assert not broken, (
        "PHP regex literal(s) that do not compile. preg_match returns FALSE on "
        "a compile error, so the caller reads it as 'no match' and the check "
        "silently rejects everything it is asked about:\n" + "\n".join(broken)
    )


@pytest.mark.skipif(NO_PHP, reason="php not installed")
def test_the_model_uri_validator_accepts_and_rejects():
    """The validator that hid this must prove it can still say YES (both directions, or neither)."""
    src = (AGENTKIT / "AgentLoader.php").read_text(encoding="utf-8")
    # Anchor on the METHOD DEFINITION, not the name: the first occurrence is its call site.
    m = re.search(
        r"function isValidModelUri.*?preg_match\(\s*'((?:[^'\\]|\\.)*)'", src, re.S
    )
    assert m, "isValidModelUri no longer contains a regex literal"
    literal = m.group(1).replace("\\", "\\\\").replace("'", "\\'")
    for uri, expected in (
        ("claude-sonnet", True),
        ("anthropic-claude-sonnet-4-5", True),
        ("openclaw-qwen2.5-coder:32b", True),
        ("garbage", False),
    ):
        code = f"echo (int) (bool) @preg_match('{literal}', '{uri}');"
        got = subprocess.run(["php", "-r", code], capture_output=True, text=True).stdout
        assert got.strip() == str(int(expected)), (
            f"model URI {uri!r}: expected {expected}, got {got.strip()!r}. "
            "If everything now returns 0, the pattern has stopped compiling "
            "again and the loader will refuse every agent."
        )


# ── SHELL HABIT ─────────────────────────────────────────────────────────────
# 2026-09-04, proposer session af942a1d (REM-249): `git log | grep` as separate args
# got git's `unknown command '|'` and the proposer burned its budget. A standalone
# shell-operator arg is now refused legibly; a `|` inside one arg is left alone.
# Executes the real tool.

needs_vendor = pytest.mark.skipif(not AUTOLOAD.is_file(), reason=NO_VENDOR_REASON)

SHELL_HABIT_PROBE = r"""
require __DIR__ . '/vendor/autoload.php';

use App\AgentKit\Tools\BashReadOnlyTool;
use App\AgentKit\Tools\ToolContext;

$ctx = new ToolContext('s', 't', 'tr', 'sp', 'agent:test', 'tu');
$tool = new BashReadOnlyTool();

function run($tool, $ctx, array $input): array {
    $r = $tool->execute($input, $ctx);
    return ['is_error' => $r->isError, 'content' => $r->content];
}

$out = [];
// A pipe written as separate args.
$out['pipe_as_args'] = run($tool, $ctx,
    ['verb' => 'git', 'args' => ['log', '|', 'grep', 'rustfs_']]);
// A redirect operator.
$out['redirect'] = run($tool, $ctx,
    ['verb' => 'cat', 'args' => ['a.txt', '>', 'b.txt']]);
// A pipe INSIDE one arg — a legitimate grep pattern, must NOT be caught by the
// shell-operator rule (it may still fail for other reasons; we only assert the
// message is not the shell-habit one).
$out['pipe_in_one_arg'] = run($tool, $ctx,
    ['verb' => 'git', 'args' => ['log', '--grep=a|b', '--max-count=1']]);

echo json_encode($out);
"""


def _shell_habit_probe() -> dict:
    p = WING / "bash-shell-habit-probe.php"
    p.write_text("<?php\n" + SHELL_HABIT_PROBE, encoding="utf-8")
    try:
        out = subprocess.run(["php", p.name], cwd=WING, capture_output=True,
                             text=True, timeout=60)
    finally:
        p.unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@needs_vendor
def test_a_pipe_written_as_args_is_named_not_run():
    got = _shell_habit_probe()["pipe_as_args"]
    assert got["is_error"] is True
    assert "no shell" in got["content"] and "follow-up" in got["content"], (
        "the pipe arg was not caught with a legible message — the model gets "
        "git's `unknown command` and reads it as git's fault")


@needs_vendor
def test_a_redirect_operator_is_named_too():
    got = _shell_habit_probe()["redirect"]
    assert got["is_error"] is True and "no shell" in got["content"]


@needs_vendor
def test_a_pipe_inside_one_arg_is_not_the_shell_habit():
    got = _shell_habit_probe()["pipe_in_one_arg"]
    # It may error for other reasons (running in the wing cwd), but never with
    # the shell-operator message — `a|b` inside one arg is a real pattern.
    assert "shell operator" not in got["content"], (
        "a `|` inside a single arg was wrongly rejected as a shell pipeline — "
        "grep patterns and --grep=a|b are legitimate")


# ── READ TOOL SANDBOX ───────────────────────────────────────────────────────
# Security review 2026-11-03: `git config --global core.fsmonitor`, `rg --pre`,
# `tree -o`, `git diff --output` and `cat ~/.nos/secrets.yml` all got through
# guardArgs(). Runs the real tool with HOME/NOS_REPO_ROOT in a temp dir: every attack
# refused or inert, and reading the repo still works.

READ_TOOL_HARNESS = r"""<?php
foreach (['LLMClient/ToolSchema.php', 'Tools/ToolInterface.php', 'Tools/ToolResult.php',
          'Tools/ToolContext.php', 'Tools/BashReadOnlyTool.php'] as $f) { require $argv[1] . '/' . $f; }
$tool = new App\AgentKit\Tools\BashReadOnlyTool();
$ctx = new App\AgentKit\Tools\ToolContext('s', 't', 'tr', 'sp', 'agent:test', 'tu');
$out = [];
foreach (json_decode(file_get_contents($argv[2]), true) as $name => $in) {
    $r = $tool->execute($in, $ctx);
    $out[$name] = ['error' => $r->isError, 'content' => $r->content];
}
echo json_encode($out);
"""


def _php() -> list[str] | None:
    if shutil.which("php"):
        return [shutil.which("php")]
    if shutil.which("frankenphp"):
        return [shutil.which("frankenphp"), "php-cli"]
    return None


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    php = _php()
    if php is None or not shutil.which("git"):
        pytest.skip("php (or frankenphp) and git are needed to run the tool")
    tmp = tmp_path_factory.mktemp("bashro")
    # As live: the checkout agents read is ~/.nos/estate, beside the secrets they must not read.
    home = tmp / "home"
    repo = home / ".nos/estate"
    repo.mkdir(parents=True)
    (home / ".nos/secrets.yml").write_text("wing_api_token: not-a-real-token\n")
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1"}
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], env=env, check=True, capture_output=True)
    git("init", "-q")
    (repo / "README").write_text("hello\n")
    git("-c", "user.email=t@t", "-c", "user.name=t", "add", "README")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    marker = tmp / "pwned"
    # A repo-local fsmonitor, as a mounted or cloned repo can carry: git status must not run it.
    git("config", "core.fsmonitor", f"touch {marker}")
    (repo / "secret-link").symlink_to(home / ".nos/secrets.yml")
    cases = {
        "global_config": {"verb": "git", "args": ["config", "--global", "core.fsmonitor", f"touch {marker}"]},
        "status": {"verb": "git", "args": ["status", "--short"]},
        "log": {"verb": "git", "args": ["log", "-1", "--format=%s"]},
        "log_dash_c": {"verb": "git", "args": ["-C", str(repo), "log", "-1", "--format=%s"]},
        "dash_c_secrets": {"verb": "git", "args": ["-C", str(home / ".nos"), "status"]},
        "diff_output": {"verb": "git", "args": ["diff", f"--output={tmp}/written"]},
        "rg_pre": {"verb": "rg", "args": ["--pre", "touch", "hello", "README"]},
        "tree_out": {"verb": "tree", "args": ["-o", f"{tmp}/written2", "."]},
        "cat_readme": {"verb": "cat", "args": ["README"]},
        "cat_estate_abs": {"verb": "cat", "args": [str(repo / "README")]},
        "cat_secrets": {"verb": "cat", "args": [str(home / ".nos/secrets.yml")]},
        "cat_secrets_tilde": {"verb": "grep", "args": ["token", "-r", str(home / ".nos")]},
        "cat_link": {"verb": "cat", "args": ["secret-link"]},
    }
    (tmp / "cases.json").write_text(json.dumps(cases))
    (tmp / "h.php").write_text(READ_TOOL_HARNESS)
    run_env = {**env, "NOS_REPO_ROOT": str(repo)}
    p = subprocess.run([*php, str(tmp / "h.php"), str(AGENTKIT), str(tmp / "cases.json")],
                       env=run_env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    return {"out": json.loads(p.stdout), "marker": marker, "home": home, "tmp": tmp}


def test_git_cannot_write_its_config_or_run_an_fsmonitor(results):
    out = results["out"]
    assert out["global_config"]["error"], out["global_config"]
    assert not (results["home"] / ".gitconfig").exists(), "git config --global wrote ~/.gitconfig"
    assert not results["marker"].exists(), "a configured core.fsmonitor ran: code execution"


def test_no_verb_writes_a_file_or_runs_a_program(results):
    out = results["out"]
    for case in ("diff_output", "rg_pre", "tree_out"):
        assert out[case]["error"], (case, out[case])
    assert not (results["tmp"] / "written").exists() and not (results["tmp"] / "written2").exists()
    assert not results["marker"].exists()


def test_the_estate_secrets_are_not_readable(results):
    out = results["out"]
    for case in ("cat_secrets", "cat_secrets_tilde", "cat_link", "dash_c_secrets"):
        assert out[case]["error"] and "not-a-real-token" not in out[case]["content"], (case, out[case])


def test_reading_the_repo_still_works(results):
    out = results["out"]
    assert not out["log"]["error"] and "init" in out["log"]["content"], out["log"]
    assert not out["status"]["error"], out["status"]
    assert not out["cat_readme"]["error"] and "hello" in out["cat_readme"]["content"]
    assert not out["cat_estate_abs"]["error"] and "hello" in out["cat_estate_abs"]["content"]
    assert not out["log_dash_c"]["error"] and "init" in out["log_dash_c"]["content"], out["log_dash_c"]


# ── TOOL LOADS ──────────────────────────────────────────────────────────────
# 2026-08-08: AskOperatorTool lacked `use ...\ToolSchema;` — `php -l` passed, the
# class could not load, and its eight regex gates stayed green; a reviewer found it
# in twelve minutes. So each registered tool is required for real.

needs_php = pytest.mark.skipif(NO_PHP, reason="php not installed on this runner")

NEON = COMMON_NEON

#: Loaded first so the interface's return type resolves. Order matters.
PRELUDE = [
    "AgentKit/LLMClient/ToolSchema.php",
    "AgentKit/Tools/ToolResult.php",
    "AgentKit/Tools/ToolContext.php",
    "AgentKit/Tools/ToolInterface.php",
]


def registered_tools() -> list[str]:
    """Class short-names registered in the ToolRegistry factory setup."""
    src = NEON.read_text(encoding="utf-8")
    names = re.findall(r"register\(@App\\AgentKit\\Tools\\(\w+)\)", src)
    assert names, (
        "no tools found in common.neon's ToolRegistry setup — the registry "
        "block moved or was renamed; point this gate at the new shape rather "
        "than letting it pass vacuously."
    )
    return names


@needs_php
def test_the_registry_is_not_empty():
    """A gate that iterates an empty list is a gate that always passes."""
    assert len(registered_tools()) >= 5, (
        f"only {len(registered_tools())} tools registered; the estate has had "
        "at least five since MigrationWriteTool. If tools were removed, update "
        "this floor deliberately."
    )


@needs_php
@pytest.mark.parametrize("tool", registered_tools())
def test_the_tool_class_materialises(tool: str, tmp_path: Path):
    """Require the file for real and assert the class exists afterwards."""
    path = TOOLS_DIR / f"{tool}.php"
    assert path.is_file(), (
        f"common.neon registers {tool} but {path.relative_to(REPO)} does not "
        "exist. The registry would throw at session start."
    )

    requires = "\n".join(f"require '{WING_APP}/{p}';" for p in PRELUDE)
    script = tmp_path / "load.php"
    # Autoload siblings in the Tools dir the way composer does (abstract bases,
    # 2026-08-28); the covariance check this gate provokes still runs either way.
    script.write_text(textwrap.dedent(f"""\
        <?php
        {requires}
        spl_autoload_register(function ($class) {{
            $short = substr($class, strrpos($class, '\\\\') + 1);
            $file = '{TOOLS_DIR}/' . $short . '.php';
            if (str_starts_with($class, 'App\\\\AgentKit\\\\Tools\\\\') && is_file($file)) {{
                require $file;
            }}
        }});
        require '{path}';
        echo class_exists('App\\\\AgentKit\\\\Tools\\\\{tool}', false) ? 'OK' : 'MISSING';
    """), encoding="utf-8")

    proc = subprocess.run(
        ["php", "-d", "error_reporting=E_ALL", str(script)],
        capture_output=True, text=True, timeout=60,
    )
    combined = (proc.stdout + proc.stderr).strip()
    assert proc.returncode == 0 and "OK" in proc.stdout, (
        f"{tool} does not load.\n\n{combined}\n\n"
        "php -l would pass this — a missing `use` is valid syntax. Only "
        "executing the file provokes the check that catches it."
    )


@needs_php
def test_every_tool_imports_the_schema_it_returns():
    """The specific slip, kept as a fast signal beside the authoritative load test."""
    missing = []
    for tool in registered_tools():
        src = (TOOLS_DIR / f"{tool}.php").read_text(encoding="utf-8")
        if "ToolSchema" in src and "use App\\AgentKit\\LLMClient\\ToolSchema;" not in src:
            missing.append(tool)
    assert not missing, (
        f"tool(s) referencing ToolSchema without importing it: {missing}. "
        "Unqualified, it resolves to App\\AgentKit\\Tools\\ToolSchema, which "
        "does not exist."
    )


# ── TOOL ENUM ───────────────────────────────────────────────────────────────
# agentkit.md §6 ruling 5, 2026-09-02: ask-operator was built but not in the schema
# enum (undeclarable for months); bash-write and mcp-pulse sat in the enum with no
# implementation (landmines). Both directions are checked.

SCHEMA = REPO / "state" / "schema" / "agent.schema.yaml"


def _enum_ids() -> set[str]:
    doc = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    tools = doc["properties"]["tools"]
    items = tools.get("items", tools)
    return set(items["properties"]["id"]["enum"])


def _registered_ids() -> set[str]:
    out = set()
    for php in TOOLS_DIR.glob("*.php"):
        src = php.read_text(encoding="utf-8")
        if "implements ToolInterface" not in src and "extends McpWingTool" not in src:
            continue
        if re.search(r"^abstract class", src, re.M):
            continue  # a base class registers nothing itself
        m = re.search(r"function id\(\)[^{]*\{\s*return '([a-z0-9-]+)';", src)
        assert m, f"{php.name} is a concrete tool but its id() is not a literal"
        out.add(m.group(1))
    assert out, "no ToolInterface implementations found — the glob or layout moved"
    return out


def test_every_enum_member_has_an_implementation():
    dead = _enum_ids() - _registered_ids()
    assert not dead, (
        f"enum members with no implementation: {sorted(dead)}. A declarable "
        "tool that cannot exist is a landmine (bash-write, mcp-pulse were "
        "this); intent belongs in the roadmap, not the contract")


def test_every_implementation_is_declarable():
    hidden = _registered_ids() - _enum_ids()
    assert not hidden, (
        f"implemented tools missing from the enum: {sorted(hidden)}. "
        "ask-operator sat here for months — built, and no manifest could "
        "grant it")


# ── SDK PARAMS ──────────────────────────────────────────────────────────────
# 2026-08-16: AnthropicAdapter spread `max_tokens` into create(...$params); the SDK
# names it $maxTokens. Classified TRANSIENT, retried, fell back, and surfaced as an
# OpenClaw 404. Asks the vendored SDK by reflection what its parameters are called.

needs_sdk = pytest.mark.skipif(
    NO_PHP or not AUTOLOAD.is_file(),
    reason="php or the vendored SDK is not installed here",
)

ADAPTER = AGENTKIT / "LLMClient/AnthropicAdapter.php"


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


@needs_sdk
def test_the_extractor_found_the_spread_array():
    """Positive control — an empty key set would make the check below vacuous."""
    keys = _params_array_keys()
    assert len(keys) >= 3, (
        f"only {len(keys)} key(s) extracted from the $params array; the shape "
        "of AnthropicAdapter has changed and this gate is reading nothing."
    )
    assert "model" in keys, "the extractor no longer sees the array it guards"


@needs_sdk
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


# ── MULTIMODAL ──────────────────────────────────────────────────────────────
# D1 invoice-vision blocker: one_shot was text-only and OpenAiCompatAdapter dropped
# image blocks, so qwen2.5vl never saw the page. Retro-red: legacy_translate() is the
# pre-fix loop (proves the DROP); the real adapter proves the CARRY; OneShot stays one call.

#: Fake PNG bytes, deliberately low entropy, base64 computed at import — never a
#: source literal (test_a_fixture_is_never_a_real_secret scans for those).
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
        pytest.skip(NO_VENDOR_REASON)
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
    # The caption text survives; the image block appears NOWHERE. That silent loss is the bug.
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


_ONESHOT_PRELUDE = f"""
require '{AUTOLOAD}';
require '{AGENTKIT}/Agent.php';
require '{AGENTKIT}/OneShot.php';
require '{AGENTKIT}/LLMClient/LLMResponse.php';
require '{AGENTKIT}/LLMClient/Message.php';
require '{AGENTKIT}/LLMClient/ToolSchema.php';
require '{AGENTKIT}/LLMClient/LLMClientInterface.php';

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


@pytest.mark.skipif(NO_PHP, reason="php not installed")
@pytest.mark.skipif(not AUTOLOAD.exists(), reason="wing vendor tree not installed")
def test_one_shot_attaches_the_image_and_stays_one_call(tmp_path):
    png_path = tmp_path / "page.png"
    # OneShot only needs a readable file at this path, not a decodable image.
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


@pytest.mark.skipif(NO_PHP, reason="php not installed")
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


# ── SHIPPED FILES ───────────────────────────────────────────────────────────
# Reality-vs-promises review 2026-05-26: AgentKit tests skip-guard "file not present
# yet", so a DELETED contract file went green-skip. The shipped files must exist, and
# the neon agents path (off-by-one 2026-05-26) plus the role's rsync must land them.

WING_BIN = WING / "bin"
# Nette's %appDir% is app/Bootstrap (the Configurator caller); neon paths resolve from it.
APP_DIR = WING_APP / "Bootstrap"
AGENTS_DIR = REPO / "files" / "anatomy" / "agents"
WING_TASKS = REPO / "roles" / "pazny.wing" / "tasks" / "main.yml"

SHIPPED = [
    AGENTKIT / "Agent.php",
    AGENTKIT / "Runner.php",
    AGENTKIT / "AgentLoader.php",
    AGENTKIT / "LLMClient" / "LLMClientInterface.php",
    AGENTKIT / "LLMClient" / "AnthropicAdapter.php",
    AGENTKIT / "LLMClient" / "OpenAiCompatAdapter.php",
    AGENTKIT / "Vault" / "CredentialResolver.php",
    AGENTKIT / "Telemetry" / "OtelExporter.php",
    AGENTKIT / "Tools" / "McpWingTool.php",
    AGENTKIT / "Webhook" / "WebhookDispatcher.php",
    WING_BIN / "run-agent.php",
    REPO / "files" / "anatomy" / "agents" / "conductor" / "agent.yml",
]


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_agentkit_shipped_file_present(path):
    assert path.is_file(), (
        f"AgentKit contract file missing: {path.relative_to(REPO)} — it is "
        "documented as SHIPPED, so its deletion must fail loudly here rather "
        "than silently green-skip the tests that guard it with skip('not present')."
    )


def test_agentloader_neon_path_resolves_to_agents_dir():
    """The neon AgentLoader path must resolve to files/anatomy/agents.

    Regression guard for the 2026-05-26 off-by-one: `%appDir%/../../agents` landed on
    the nonexistent files/anatomy/wing/agents, so /agents was always empty.
    """
    neon = COMMON_NEON.read_text(encoding="utf-8")
    # 2026-06-12: the loader consumes the named %agentsDir% parameter (CLI-overridable,
    # see RUNNER PATHS below); the web-resolved default lives in the parameters block.
    assert "AgentLoader(%agentsDir%)" in neon, (
        "AgentLoader must consume the %agentsDir% parameter (CLI-overridable)"
    )
    m = re.search(r"agentsDir:\s*%appDir%/(\S+)", neon)
    assert m, "agentsDir: %appDir%/... parameter default not found in common.neon"
    resolved = (APP_DIR / m.group(1)).resolve()
    assert resolved == AGENTS_DIR.resolve(), (
        f"agentsDir default resolves to {resolved}, not {AGENTS_DIR}. The neon "
        f"default `%appDir%/{m.group(1)}` is wrong — %appDir% is the Bootstrap "
        "dir, so the agent definitions are three levels up + /agents."
    )
    assert (resolved / "conductor" / "agent.yml").is_file(), (
        "resolved agents dir has no conductor/agent.yml — the loader root is empty."
    )


def test_wing_role_deploys_agent_definitions():
    """The wing role must rsync files/anatomy/agents to the host (~/wing/agents), or the catalog 404s."""
    tasks = WING_TASKS.read_text(encoding="utf-8")
    assert "files/anatomy/agents/" in tasks and "/agents/" in tasks, (
        "roles/pazny.wing/tasks/main.yml does not rsync files/anatomy/agents/ to "
        "the host — AgentLoader's deployed root (~/wing/agents) will be empty."
    )


# ── RUNNER PATHS ────────────────────────────────────────────────────────────
# 2026-06-12 release sweep: the CLI runner resolved agents via the %appDir% default
# (wrong under bin/, "agent.yml not found" on every deployed run), and the operator
# trigger spawned PHP_BINARY — empty under FrankenPHP → proc_open 500.

RUN_AGENT = WING_BIN / "run-agent.php"
# A3.1 (2026-06-16): the spawn body moved to App\AgentKit\OperatorTrigger::spawn.
OPERATOR_TRIGGER = AGENTKIT / "OperatorTrigger.php"


def test_common_neon_uses_agents_dir_parameter():
    src = COMMON_NEON.read_text()
    assert "agentsDir: %appDir%/../../../agents" in src, (
        "common.neon lost the agentsDir parameter default — the CLI override "
        "in bin/run-agent.php keys off this parameter name."
    )
    assert "App\\AgentKit\\AgentLoader(%agentsDir%)" in src, (
        "AgentLoader must consume %agentsDir% (a named parameter the CLI can "
        "override), not an inline %appDir%-relative path."
    )


def test_run_agent_cli_overrides_agents_dir():
    src = RUN_AGENT.read_text()
    assert "addConfig(['parameters' => ['agentsDir' => __DIR__ . '/../../agents']])" in src, (
        "bin/run-agent.php must override agentsDir with __DIR__/../../agents — "
        "the %appDir%-relative neon default resolves to <wing>/../agents under "
        "the CLI bootstrap (deploy nesting) and every deployed run dies with "
        "'agent.yml not found'."
    )


def test_spawn_runner_never_uses_bare_php_binary():
    src = OPERATOR_TRIGGER.read_text()
    assert "WING_PHP_BIN" in src, (
        "OperatorTrigger::spawn lost the WING_PHP_BIN resolution — "
        "PHP_BINARY is empty under FrankenPHP's embedded SAPI and proc_open "
        "throws 'First element must contain a non-empty program name' (500 on "
        "every operator trigger)."
    )
    # argv[0] must come from the resolved $phpBin, never the raw constant.
    argv_blocks = re.findall(r"\$argv\s*=\s*\[\s*([^,]+),", src)
    assert argv_blocks, "no $argv array found in OperatorTrigger"
    for first in argv_blocks:
        assert first.strip() != "PHP_BINARY", (
            "argv[0] is the raw PHP_BINARY constant again — empty under "
            "FrankenPHP; use the resolved $phpBin."
        )
