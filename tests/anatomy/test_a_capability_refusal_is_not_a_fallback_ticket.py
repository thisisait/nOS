"""A capability refusal must propagate — never become a fallback re-send.

THE INVERSION THIS PINS (found in the second adversarial pass, 2026-08-12).
`ClaudeCliAdapter` refuses tool schemas because the CLI runs its own tool loop
and would drop them silently — the docblock calls that refusal its whole point.
But the refusal was thrown as plain `LLMPermanentError`, and
`Runner::callWithRetry` answers a permanent error by re-sending the SAME
request — tools included — to `modelFallbackUri`. All nine agent profiles
declare tools and fall back to `openclaw-qwen2.5-coder:32b`, whose adapter
sends tools as an unenforced "passthrough hint". So the loud refusal became
exactly the silent tool-drop it exists to prevent, one hop later, on a 32B
local model wearing the ceremony's identity.

THE CONTRACT, as now written in `LLMCapabilityError`'s docblock: transient →
retry then fallback; permanent (a fact about the BACKEND: auth, retirement) →
fallback; capability (a fact about the REQUEST's shape) → propagate. A request
the backend cannot honour does not become honourable by being sent elsewhere —
it either hits the same wall or changes meaning without anyone deciding to.

WHAT THIS CANNOT COVER. Whether a backend that ACCEPTS tools actually honours
them — OpenClawAdapter forwards tools to a gateway whose tool surface is the
gateway's promise, not something the adapter can verify per-call. This gate
closes the path where our own code converts a refusal into a drop; it cannot
make a remote gateway honest.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
LLM = REPO / "files/anatomy/wing/app/AgentKit/LLMClient"
RUNNER = REPO / "files/anatomy/wing/app/AgentKit/Runner.php"
ADAPTER = LLM / "ClaudeCliAdapter.php"

pytestmark = pytest.mark.skipif(
    shutil.which("php") is None, reason="php not installed on this runner"
)

PRELUDE = [
    "LLMResponse.php",
    "Message.php",
    "ToolSchema.php",
    "LLMTransientError.php",
    "LLMPermanentError.php",
    "LLMCapabilityError.php",
    "LLMClientInterface.php",
    "ClaudeCliAdapter.php",
]


def php(script: str, tmp_path: Path) -> subprocess.CompletedProcess:
    requires = "\n".join(f"require '{LLM}/{p}';" for p in PRELUDE)
    f = tmp_path / "probe.php"
    f.write_text(f"<?php\n{requires}\n{script}\n", encoding="utf-8")
    return subprocess.run(
        ["php", "-d", "error_reporting=E_ALL", str(f)],
        capture_output=True, text=True, timeout=60,
    )


def test_the_tools_refusal_is_a_capability_error(tmp_path: Path) -> None:
    """Executed, not grepped — the class must load and the throw must be the
    NARROW type, because the narrow type is what the Runner's fallback gate
    keys on. A refusal thrown as plain LLMPermanentError re-opens the drop."""
    out = php(textwrap.dedent("""\
        $a = new App\\AgentKit\\LLMClient\\ClaudeCliAdapter('claude-sonnet', 'sonnet');
        $tool = new App\\AgentKit\\LLMClient\\ToolSchema('t', 'd', ['type' => 'object']);
        $msg = new App\\AgentKit\\LLMClient\\Message('user',
            [['type' => 'text', 'text' => 'hi']]);
        try {
            $a->send('', [$msg], [$tool]);
            echo 'NO-THROW';
        } catch (App\\AgentKit\\LLMClient\\LLMCapabilityError $e) {
            echo 'CAPABILITY';
        } catch (App\\AgentKit\\LLMClient\\LLMPermanentError $e) {
            echo 'PERMANENT';
        }
    """), tmp_path)
    assert out.stdout.strip() == "CAPABILITY", (
        "handing the claude CLI adapter a tool schema must raise "
        f"LLMCapabilityError.\nstdout: {out.stdout}\nstderr: {out.stderr}"
    )


def test_capability_error_narrows_permanent_not_replaces_it(tmp_path: Path) -> None:
    """Every existing `catch (LLMPermanentError)` outside the Runner must keep
    catching the refusal — the narrowing is only where the fallback decision
    lives. A sibling class would silently escape those handlers."""
    out = php(textwrap.dedent("""\
        echo is_subclass_of(
            'App\\\\AgentKit\\\\LLMClient\\\\LLMCapabilityError',
            'App\\\\AgentKit\\\\LLMClient\\\\LLMPermanentError'
        ) ? 'OK' : 'NOT-A-SUBCLASS';
    """), tmp_path)
    assert out.stdout.strip() == "OK", (
        f"stdout: {out.stdout}\nstderr: {out.stderr}"
    )


def test_the_runner_gates_capability_before_permanent() -> None:
    """PHP dispatches to the FIRST matching catch, and LLMCapabilityError IS an
    LLMPermanentError — so if the permanent catch comes first, the capability
    catch is dead code and the fallback re-send is back. Order is the fix."""
    full = RUNNER.read_text(encoding="utf-8")
    start = full.find("private function callWithRetry")
    assert start != -1, "callWithRetry moved — repoint this gate, don't delete it"
    # Scoped to the fallback decision: run() has its own LLMPermanentError catch
    # (session bookkeeping), which is fine and not this gate's subject.
    src = full[start:]
    cap = src.find("catch (LLMCapabilityError")
    perm = src.find("catch (LLMPermanentError")
    assert cap != -1, "Runner has no LLMCapabilityError catch — the gate is gone"
    assert perm != -1, "Runner has no LLMPermanentError catch — callWithRetry moved?"
    assert cap < perm, (
        "the LLMCapabilityError catch must come BEFORE the LLMPermanentError "
        "catch; after it, it is unreachable and the refusal falls back again."
    )
    body = src[cap:perm]
    # `$agent->modelFallbackUri` — the CODE access shape, not the bare word,
    # which the catch's own explanatory comment legitimately names. The first
    # cut of this assert matched its own subject's prose, the recorded failure
    # mode of gates that grep what they argue about.
    assert "$agent->modelFallbackUri" not in body, (
        "the capability catch consults the fallback uri — a capability refusal "
        "is about the request's shape and must propagate, not be re-sent."
    )
    assert re.search(r"throw \$exc;", body), (
        "the capability catch must rethrow — swallowing it would report a "
        "completed call that never happened."
    )


def test_the_prompt_is_positional_after_end_of_options() -> None:
    """Measured 2026-08-12 (claude 2.1.220): without `--`, a folded prompt that
    opens with `-` dies as `error: unknown option`. The `--` must be appended
    to argv before the prompt is."""
    src = ADAPTER.read_text(encoding="utf-8")
    dashdash = src.find("$argv[] = '--';")
    prompt = src.find("$argv[] = $prompt;")
    assert dashdash != -1 and prompt != -1 and dashdash < prompt, (
        "ClaudeCliAdapter must append `--` (end of options) to argv before the "
        "positional prompt — a prompt starting with `-` is otherwise parsed as "
        "a flag."
    )


def test_max_tokens_reaches_the_cli() -> None:
    """The parameter must be read, not merely accepted — the same shape the
    adapter's own tools refusal condemns. CLAUDE_CODE_MAX_OUTPUT_TOKENS is the
    one cap the CLI exposes (measured 2026-08-12: honoured, and exceeding it is
    a discard-error, which send() maps to stop_reason=max_tokens)."""
    src = ADAPTER.read_text(encoding="utf-8")
    assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS" in src, (
        "maxTokens is no longer passed to the CLI — either wire it back or "
        "delete this gate together with the docblock claim that it is honoured."
    )
    assert "output token maximum" in src, (
        "the over-cap discard-error is no longer mapped; a capped call that "
        "runs over would surface as a generic permanent backend failure."
    )


def test_the_synth_session_sentinel_is_not_a_model_uri() -> None:
    """`claude-cli` was a safe sentinel until `claude` became a provider — then
    it started parsing as `claude --model cli`, a model that does not exist.
    The sentinel must stay OUTSIDE the uri grammar so Factory::fromUri throws
    on it instead of dispatching a ghost."""
    repo_src = (REPO / "files/anatomy/wing/app/Model/AgentSessionRepository.php")\
        .read_text(encoding="utf-8")
    m = re.search(r"'model_uri'\s*=>\s*'([^']+)'", repo_src)
    assert m, "synthRow no longer sets model_uri — did the synth path move?"
    sentinel = m.group(1)
    assert not re.match(r"^[a-z]+-.+$", sentinel), (
        f"synth sentinel '{sentinel}' parses as a model uri (provider-dash-"
        "model); Factory::fromUri would accept its shape and dispatch a model "
        "nobody has."
    )
