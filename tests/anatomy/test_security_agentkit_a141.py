"""Anatomy CI gates for A14.1 security fixes (2026-05-07).

Pins the two boundaries the post-A14 security review surfaced:

  Vuln 1: every Wing API presenter MUST extend BaseApiPresenter so token
          validation goes through the canonical requireTokenAuth() path.
          The original A14 AgentsPresenter / AgentSessionsPresenter only
          checked the `Bearer ` prefix - anyone with `Authorization:
          Bearer x` got the agent catalog + session lineage.

  Vuln 2: BashReadOnlyTool MUST use the array form of proc_open (which
          bypasses /bin/sh on POSIX) AND must reject shell-reentrant
          verbs at the allowlist level. The original A14 tool used the
          string form, which delegates to /bin/sh -c, allowing payloads
          like awk 'BEGIN{system(...)}', find . -exec sh -c, git -c
          alias.x=!sh -c, etc.

These tests do NOT execute PHP - they parse source with regex / static
inspection, which is enough for the contract assertions and runs in CI
without a PHP interpreter.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WING_APP = REPO_ROOT / "files" / "anatomy" / "wing" / "app"
API_PRESENTERS_DIR = WING_APP / "Presenters" / "Api"
BASH_TOOL = WING_APP / "AgentKit" / "Tools" / "BashReadOnlyTool.php"


# ---------- Vuln 1: API presenter inheritance ----------


def test_every_api_presenter_extends_base_api_presenter():
    """Without this, a presenter can roll its own auth (or skip it).
    The A14 incident shipped two presenters that did exactly that -
    just `extends Presenter` plus a Bearer-prefix string check, no
    token DB validation. This gate ensures any new API presenter
    inherits the canonical `requireTokenAuth()` path."""
    if not API_PRESENTERS_DIR.is_dir():
        pytest.skip("Api presenter dir missing")

    failures = []
    for php in sorted(API_PRESENTERS_DIR.glob("*.php")):
        if php.name == "BaseApiPresenter.php":
            continue
        src = php.read_text()
        m = re.search(r"^(?:final\s+|abstract\s+)?class\s+(\w+)\s+extends\s+(\w+)",
                      src, re.MULTILINE)
        if not m:
            failures.append(f"{php.name}: no class declaration parsed")
            continue
        cls, parent = m.group(1), m.group(2)
        if parent != "BaseApiPresenter":
            failures.append(
                f"{php.name}: class {cls} extends {parent} - must extend "
                "BaseApiPresenter so requireTokenAuth() runs at startup() "
                "(A14.1 incident class)"
            )

    assert not failures, "Api presenter inheritance failures:\n  - " + "\n  - ".join(failures)


def test_no_api_presenter_does_bearer_prefix_check_without_token_validate():
    """Defensive: the original A14 anti-pattern was a Bearer-prefix check
    WITHOUT a follow-up tokenRepo->validate() call. Some presenters
    (EventsPresenter) legitimately do BOTH because of HMAC bypass paths.
    Flag only files that have the prefix check but NO tokenRepo->validate."""
    if not API_PRESENTERS_DIR.is_dir():
        pytest.skip("Api presenter dir missing")

    bearer_pat = re.compile(r"str_starts_with\s*\(\s*\$\w+\s*,\s*['\"]Bearer ['\"]")
    failures = []
    for php in sorted(API_PRESENTERS_DIR.glob("*.php")):
        if php.name == "BaseApiPresenter.php":
            continue
        src = php.read_text()
        if bearer_pat.search(src) and "tokenRepo->validate" not in src:
            failures.append(
                f"{php.name}: re-implements the Bearer-prefix-only check "
                "WITHOUT a tokenRepo->validate() call - this is the A14.1 "
                "auth-bypass shape. Use BaseApiPresenter::requireTokenAuth() "
                "or, for HMAC bypasses, mirror EventsPresenter's two-path "
                "design (publicActions + private requireBearerToken with "
                "tokenRepo->validate)."
            )
    assert not failures, "\n".join(failures)


# ---------- Vuln 2: BashReadOnlyTool boundaries ----------


@pytest.fixture(scope="module")
def bash_tool_src():
    if not BASH_TOOL.is_file():
        pytest.skip("BashReadOnlyTool.php missing")
    return BASH_TOOL.read_text()


def test_bash_tool_uses_array_form_proc_open(bash_tool_src):
    """proc_open() with a STRING delegates to /bin/sh -c on POSIX,
    which is the original A14 RCE class. proc_open() with an ARRAY
    bypasses /bin/sh entirely and exec()s the binary directly."""
    forbidden = re.search(r"proc_open\s*\(\s*\$command\s*,", bash_tool_src)
    assert forbidden is None, (
        "BashReadOnlyTool.php still calls proc_open($command, ...) - "
        "string form delegates to /bin/sh -c on POSIX. Switch to array form."
    )
    has_array_call = bool(re.search(r"proc_open\s*\(\s*\$argv\b", bash_tool_src)) or \
                     bool(re.search(r"proc_open\s*\(\s*\[", bash_tool_src))
    assert has_array_call, (
        "BashReadOnlyTool.php proc_open call no longer uses the array form. "
        "DO NOT switch back to a string - this is the A14.1 RCE-fix invariant."
    )


def test_bash_tool_forbids_shell_reentrant_verbs(bash_tool_src):
    must_be_forbidden = {
        'awk', 'find', 'sed', 'php', 'perl', 'python', 'ruby', 'node',
        'env', 'sudo', 'ssh', 'xargs', 'bash', 'sh', 'zsh',
        'docker', 'curl', 'wget', 'vim', 'vi', 'nano', 'emacs',
    }

    m = re.search(r"FORBIDDEN_VERBS\s*=\s*\[(.+?)\]", bash_tool_src, re.DOTALL)
    assert m, "BashReadOnlyTool.php has no FORBIDDEN_VERBS constant"
    forbidden_verbs = set(re.findall(r"'([^']+)'", m.group(1)))
    missing = must_be_forbidden - forbidden_verbs
    assert not missing, (
        f"FORBIDDEN_VERBS missing: {sorted(missing)} (A14.1 RCE class)"
    )

    m2 = re.search(r"ALLOWED_VERBS\s*=\s*\[(.+?)\]", bash_tool_src, re.DOTALL)
    assert m2, "BashReadOnlyTool.php has no ALLOWED_VERBS constant"
    allowed_verbs = set(re.findall(r"'([^']+)'", m2.group(1)))
    overlap = must_be_forbidden & allowed_verbs
    assert not overlap, (
        f"ALLOWED_VERBS contains forbidden verbs: {sorted(overlap)}"
    )


def test_bash_tool_input_schema_is_structured(bash_tool_src):
    assert "'verb'" in bash_tool_src, (
        "BashReadOnlyTool.php input schema must declare a 'verb' field. "
        "Free-form 'command' string is the A14.1 RCE precondition."
    )
    assert "'args'" in bash_tool_src, (
        "BashReadOnlyTool.php input schema must declare an 'args' array."
    )
    legacy = re.search(r"\$input\s*\[\s*['\"]command['\"]\s*\]", bash_tool_src)
    assert legacy is None, (
        "BashReadOnlyTool.php still reads $input['command'] - schema moved "
        "to {verb, args[]}."
    )


def test_bash_tool_git_argv_guard(bash_tool_src):
    """git -c alias.x=!sh -c '...' x execs a shell from inside git even when
    called via array-form proc_open. Argv guard must reject -c, --exec-path,
    --ssh-command, --upload-pack/--receive-pack/--upload-archive, and !-prefix."""
    # Locate the git branch in guardArgs by anchoring on the verb literal
    git_branch = re.search(
        r"\$verb\s*===\s*['\"]git['\"](.+?)(?=\$verb\s*===|return null;\s*\}\s*\}|\Z)",
        bash_tool_src, re.DOTALL,
    )
    assert git_branch, "guardArgs() has no 'git' branch - required by A14.1"
    git_body = git_branch.group(1)

    for required_block in ('-c', '--exec-path', '--ssh-command',
                            '--upload-pack', '--receive-pack',
                            '--upload-archive'):
        assert (f"'{required_block}'" in git_body) or (f'"{required_block}"' in git_body), (
            f"guardArgs() git branch does not block {required_block!r}"
        )

    assert "str_starts_with" in git_body and "'!'" in git_body, (
        "guardArgs() git branch does not block aliases starting with '!' "
        "(git aliases prefixed with ! shell-out)"
    )


def test_bash_tool_sqlite3_argv_guard(bash_tool_src):
    """sqlite3 dot-commands escape the SQL evaluator. Argv guard rejects
    args starting with . AND requires -readonly."""
    sqlite_branch = re.search(
        r"\$verb\s*===\s*['\"]sqlite3['\"](.+?)(?=\$verb\s*===|return null;\s*\}\s*\}|\Z)",
        bash_tool_src, re.DOTALL,
    )
    assert sqlite_branch, "guardArgs() has no 'sqlite3' branch - required by A14.1"
    sqlite_body = sqlite_branch.group(1)

    assert "'.'" in sqlite_body and "str_starts_with" in sqlite_body, (
        "guardArgs() sqlite3 branch does not block args starting with '.' "
        "(.shell / .system / .read escape SQL evaluator)"
    )
    assert "-readonly" in sqlite_body, (
        "guardArgs() sqlite3 branch does not require -readonly flag"
    )
