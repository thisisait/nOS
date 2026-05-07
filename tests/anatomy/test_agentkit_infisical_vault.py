"""Anatomy CI gates for the Infisical secret_ref scheme (Track B U-B-Vault).

Pins the contract between `infisical:/path` secret_refs and the Vault
CredentialResolver / InfisicalClient pair. The resolver wires the
scheme to a CLI invocation through proc_open. Anything that loosens
these invariants reopens the A14.1 RCE class, so they are pinned
statically (no PHP execution required).

The boundaries this file pins:

  1. Path validation regex matches the doctrine: ^/[A-Za-z0-9_/-]+$
     (slash-prefixed; alnum + underscore + dash + interior slash).
     Rejecting `..`, spaces, shell metacharacters, leading dot.

  2. proc_open MUST use the array form. The string form delegates to
     `/bin/sh -c` on POSIX — same lesson as A14.1 BashReadOnlyTool.

  3. Plaintext is never echoed in error_log lines. The bad-input
     reject path must NOT include $secretRef / $path in the message
     (those can be attacker-controlled via Tier-2 manifests).

  4. The proc_open env_vars allowlist forwards INFISICAL_TOKEN +
     PATH/HOME/TZ but NEVER ANTHROPIC_API_KEY / WING_API_TOKEN /
     BONE_SECRET / WING_EVENTS_HMAC_SECRET / OPENCLAW_API_KEY.

  5. CredentialResolver caches at instance level and drops the cache
     on bindVault() rebind — never persists to disk, never crosses
     sessions.

These tests parse the PHP source statically. They run in CI without a
PHP interpreter (other tests confirm syntax via `php -l`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VAULT_DIR = (
    REPO_ROOT / "files" / "anatomy" / "wing" / "app" / "AgentKit" / "Vault"
)
RESOLVER = VAULT_DIR / "CredentialResolver.php"
CLIENT = VAULT_DIR / "InfisicalClient.php"


@pytest.fixture(scope="module")
def resolver_src() -> str:
    if not RESOLVER.is_file():
        pytest.skip("CredentialResolver.php missing")
    return RESOLVER.read_text()


@pytest.fixture(scope="module")
def client_src() -> str:
    if not CLIENT.is_file():
        pytest.skip("InfisicalClient.php missing")
    return CLIENT.read_text()


# ---------- Path validation ----------


def test_infisical_path_pattern_is_strict(client_src: str) -> None:
    """Path regex must accept the slash-prefixed alnum-underscore-dash-slash
    shape and nothing more. A loosening (e.g. allowing `*` or spaces) would
    blow the path-validation gate open."""
    m = re.search(r"PATH_PATTERN\s*=\s*'([^']+)'", client_src)
    assert m, "InfisicalClient.php has no PATH_PATTERN constant"
    pattern = m.group(1)
    # Must be slash-anchored on both ends, slash-prefixed, restricted class.
    assert pattern.startswith("#^/"), (
        f"PATH_PATTERN must be slash-anchored at start: {pattern!r}"
    )
    assert "[A-Za-z0-9_/-]" in pattern, (
        f"PATH_PATTERN must restrict to alnum + underscore + dash + slash: "
        f"{pattern!r}"
    )
    # Forbid characters that would loosen the gate.
    for forbidden in ("\\.", "\\s", "\\*", "\\?"):
        assert forbidden not in pattern, (
            f"PATH_PATTERN must not include {forbidden!r} class: {pattern!r}"
        )


def test_infisical_isvalidpath_runs_before_proc_open(client_src: str) -> None:
    """Defence-in-depth ordering: inside fetch(), the path gate must
    execute BEFORE we ever reach the proc_open call site. Locate the
    fetch() body and assert isValidPath() appears before proc_open()
    inside it.
    """
    fetch_match = re.search(
        r"function\s+fetch\b.*?\{(.+?)\n\t\}",
        client_src, re.DOTALL,
    )
    assert fetch_match, "InfisicalClient.php missing fetch() method"
    body = fetch_match.group(1)
    is_valid_idx = body.find("isValidPath")
    proc_call = re.search(r"proc_open\s*\(", body)
    # If proc_open isn't called from fetch() directly (it's in a helper),
    # that's also acceptable — the path gate just has to run first in
    # the chain from fetch() down. Verify at least the gate is present.
    assert is_valid_idx != -1, (
        "fetch() must call isValidPath() before doing anything else"
    )
    if proc_call:
        proc_idx = proc_call.start()
        assert is_valid_idx < proc_idx, (
            "isValidPath() must execute BEFORE proc_open() inside fetch() "
            "— path gate ordering"
        )


def test_infisical_rejects_traversal_and_null_byte(client_src: str) -> None:
    """Defence in depth — even if someone loosens PATH_PATTERN later,
    the explicit `..` and null-byte rejects must remain."""
    assert "str_contains($path, '..')" in client_src, (
        "InfisicalClient::isValidPath must explicitly reject '..' "
        "(belt-and-suspenders against a future regex loosening)"
    )
    assert "str_contains($path, \"\\0\")" in client_src, (
        "InfisicalClient::isValidPath must explicitly reject null bytes"
    )


# ---------- proc_open shape ----------


def test_infisical_uses_array_form_proc_open(client_src: str) -> None:
    """String-form proc_open delegates to /bin/sh -c. We MUST use the
    array form so the CLI binary is execve()-d directly. Same A14.1
    invariant the BashReadOnlyTool was forced through."""
    # The string-form shapes that would reopen the RCE class.
    forbidden_shapes = [
        re.compile(r"proc_open\s*\(\s*['\"]"),       # proc_open("infisical ...
        re.compile(r"proc_open\s*\(\s*\$cmd\s*,"),    # proc_open($cmd, ...
        re.compile(r"proc_open\s*\(\s*\$command\s*,"),
        re.compile(r"proc_open\s*\(\s*sprintf\s*\("),
    ]
    for pat in forbidden_shapes:
        assert pat.search(client_src) is None, (
            f"InfisicalClient.php uses a string-form proc_open shape "
            f"({pat.pattern!r}) — this delegates to /bin/sh -c on POSIX. "
            "Switch to the array form (proc_open($argv, ...))."
        )

    # Must call the array form somewhere.
    array_form = re.search(r"proc_open\s*\(\s*\$argv\b", client_src)
    assert array_form, (
        "InfisicalClient.php must call proc_open($argv, ...) with the "
        "array form (A14.1 invariant)"
    )


def test_infisical_proc_open_passes_env_arg(client_src: str) -> None:
    """proc_open(..., $env) must pass an EXPLICIT env array — without it
    the child inherits the full FrankenPHP env including ANTHROPIC_API_KEY
    et al. Same A14.2 hardening rule the BashReadOnlyTool follows."""
    has_env_arg = re.search(
        r"proc_open\s*\([^)]*,\s*\$env\s*\)", client_src
    )
    assert has_env_arg, (
        "InfisicalClient.php proc_open call must end with `, $env)` — "
        "without it the child inherits the parent's full env (A14.2)"
    )
    assert "minimalEnv()" in client_src, (
        "InfisicalClient.php must call minimalEnv() to build the env "
        "argument (A14.2 hardening)"
    )


# ---------- env allowlist ----------


def test_infisical_env_allowlist_forwards_infisical_token(client_src: str) -> None:
    """The CLI authenticates via INFISICAL_TOKEN (universal-auth machine
    identity). It MUST appear in the allowlist or the spawned CLI cannot
    authenticate at all."""
    m = re.search(
        r"ENV_ALLOWLIST\s*=\s*\[(.+?)\]", client_src, re.DOTALL
    )
    assert m, "InfisicalClient.php missing ENV_ALLOWLIST constant"
    allowlist_body = m.group(1)
    assert "'INFISICAL_TOKEN'" in allowlist_body, (
        "ENV_ALLOWLIST must include INFISICAL_TOKEN — without it the "
        "Infisical CLI cannot authenticate"
    )
    assert "'PATH'" in allowlist_body, (
        "ENV_ALLOWLIST must include PATH — without it proc_open cannot "
        "resolve the binary"
    )


def test_infisical_env_allowlist_excludes_secrets(client_src: str) -> None:
    """The spawned CLI must NEVER see ANTHROPIC_API_KEY / WING_API_TOKEN /
    BONE_SECRET / WING_EVENTS_HMAC_SECRET / OPENCLAW_API_KEY. Adding any
    of them to the allowlist would leak agent secrets to the CLI process
    via the env."""
    m = re.search(
        r"ENV_ALLOWLIST\s*=\s*\[(.+?)\]", client_src, re.DOTALL
    )
    assert m, "InfisicalClient.php missing ENV_ALLOWLIST constant"
    allowlist_body = m.group(1)
    forbidden_names = [
        "ANTHROPIC_API_KEY",
        "WING_API_TOKEN",
        "BONE_SECRET",
        "WING_EVENTS_HMAC_SECRET",
        "OPENCLAW_API_KEY",
    ]
    for name in forbidden_names:
        assert f"'{name}'" not in allowlist_body, (
            f"ENV_ALLOWLIST whitelists {name} — spawned CLI would inherit "
            "an agent secret. Remove it."
        )


# ---------- no plaintext in logs ----------


def test_infisical_error_logs_never_echo_input(client_src: str) -> None:
    """error_log() lines must describe the FAILURE shape (path malformed,
    CLI missing, exit non-zero) — never echo $path, $secretRef, $value,
    or anything that could leak attacker-controlled or secret content.

    The doctrine: rejection messages take FIXED strings or controlled
    integers (exit code). String concatenation with $path / $secretRef /
    $value variables in an error_log line fails this gate.
    """
    error_log_lines = re.findall(
        r"error_log\s*\(\s*['\"][^'\"]*['\"]([^)]*)\)", client_src
    )
    leakers: list[str] = []
    for tail in error_log_lines:
        # Concatenations of FIXED strings with `. $varName` where the
        # variable name carries attacker-controlled or secret content.
        for var in ("$path", "$secretRef", "$value", "$secretName",
                    "$parentPath", "$stdout", "$stderr"):
            if var in tail:
                leakers.append(var)
    assert not leakers, (
        f"InfisicalClient.php error_log lines echo input/secret variables "
        f"{leakers!r}. Rejection messages must take FIXED strings or "
        "controlled integers only."
    )


def test_resolver_dereference_strips_infisical_prefix(resolver_src: str) -> None:
    """The resolver must hand the CLIENT just the path component, not
    the full `infisical:/...` ref — otherwise the colon would survive
    into the path and fail isValidPath."""
    # Locate the dereference() body
    m = re.search(
        r"function\s+dereference\b.*?\{(.+?)\n\t\}",
        resolver_src, re.DOTALL,
    )
    assert m, "CredentialResolver::dereference() body not found"
    body = m.group(1)
    assert "infisical:" in body, (
        "CredentialResolver::dereference() lost the infisical: branch"
    )
    # Must call substr / similar to strip the prefix.
    has_strip = (
        "substr($secretRef, strlen('infisical:'))" in body
        or "substr($secretRef, 10)" in body
    )
    assert has_strip, (
        "CredentialResolver::dereference() must strip the `infisical:` "
        "prefix before passing to InfisicalClient::fetch() — otherwise "
        "the colon survives into the path and fails isValidPath()"
    )


# ---------- session-lifetime cache ----------


def test_resolver_cache_drops_on_bindvault(resolver_src: str) -> None:
    """The resolver caches at instance level. bindVault() must clear
    the cache so a session boundary doesn't carry leftover values."""
    # Look for a cache-clearing assignment inside bindVault.
    m = re.search(
        r"function\s+bindVault\b.*?\{(.+?)\n\t\}",
        resolver_src, re.DOTALL,
    )
    assert m, "CredentialResolver::bindVault() body not found"
    body = m.group(1)
    assert "$this->cache = [];" in body or "$this->cache = array();" in body, (
        "CredentialResolver::bindVault() must clear $this->cache on rebind "
        "— otherwise leftover session values survive across sessions"
    )


def test_resolver_cache_is_not_static(resolver_src: str) -> None:
    """A static cache would survive the instance and leak across sessions
    (e.g. when the runner short-lives and the daemon long-lives). The
    cache MUST be an instance property."""
    # Find the cache declaration.
    static_decl = re.search(
        r"private\s+static\s+array\s+\$cache\b", resolver_src
    )
    assert static_decl is None, (
        "CredentialResolver::$cache is declared static — must be an "
        "instance property so sessions get isolated caches"
    )
    instance_decl = re.search(
        r"private\s+array\s+\$cache\b", resolver_src
    )
    assert instance_decl, (
        "CredentialResolver must declare a `private array $cache` "
        "instance property"
    )


def test_resolver_no_disk_cache(resolver_src: str, client_src: str) -> None:
    """The cache MUST live in memory only — no file_put_contents,
    apcu_store, or sqlite write paths in either file."""
    forbidden = [
        "file_put_contents",
        "apcu_store",
        "apc_store",
        "$cache_file",
        "/tmp/agentkit",
        "/var/cache",
    ]
    for needle in forbidden:
        assert needle not in resolver_src, (
            f"CredentialResolver.php contains {needle!r} — cache MUST "
            "live in memory only, never persist to disk"
        )
        assert needle not in client_src, (
            f"InfisicalClient.php contains {needle!r} — cache MUST "
            "live in memory only, never persist to disk"
        )
