"""Anatomy gate: a scheduled job stores a pointer to a secret, never the secret.

MEASURED 2026-08-11, on the live wing.db:

    SELECT count(*) FROM pulse_jobs WHERE env_json LIKE '%_pw_%'   ->  19 of 29

Nineteen rows held a derived credential IN THE CLEAR — agent OAuth client
secrets, `KEAP_AGENT_TOKEN_RW`, `WING_EVENTS_HMAC_SECRET` — every one of them
`<prefix>_pw_*`, so a single row also reveals the prefix that yields the rest by
construction (the REM-144 class). `wing.db` is read by Wing, the `/audit`
timeline and the events API, is reachable by anything running as this UID, and
is copied out nightly by the backup.

THE CONTRADICTION THIS CLOSES. AgentKit has held the rule since A14 —
`agent_credentials.secret_ref` is a POINTER (`env:VAR`, `infisical:/path`)
resolved at session-open, never a value — and `w-agentkit-spine` exists because
that rule is a property of the runtime which is NOT running the agents. The one
that IS did the opposite. After the change: 0 plaintext, 25 rows carrying
`secret:<name>`, resolved by `pulse/daemon.py::_resolve_secrets` at exec time
from `~/.nos/secrets.yml` (0600).

WHAT THIS GATE CANNOT DO: read the operator's live database. It asserts the
SHAPE — that the catalog emits references, that the daemon resolves them, and
that an unresolvable one refuses rather than passing a literal through. The
count above is a measurement, recorded here because a number in a docstring is
evidence and a number in an assertion would be a moving target.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
CATALOG = REPO / "files/anatomy/scripts/discover-pulse-catalog.py"
DAEMON = REPO / "files/anatomy/pulse/pulse/daemon.py"
RESOLVER = REPO / "files/anatomy/pulse/pulse/secrets.py"
STORE_TEMPLATE = REPO / "templates/secrets.yml.j2"


def test_the_catalog_emits_references_for_secret_shaped_values() -> None:
    src = CATALOG.read_text(encoding="utf-8")
    refs = re.findall(r'"secret:(\w+)"', src)
    assert len(refs) >= 15, (
        f"the catalog emits only {len(refs)} secret reference(s). It used to "
        "substitute the VALUES, which is how nineteen job rows came to hold "
        "credentials in the clear."
    )
    # The specific ones that were measured in the clear.
    for name in ("wing_api_token", "keap_agent_token_rw", "bone_secret"):
        assert name in refs, f"{name} is no longer emitted as a reference"


def test_the_prefix_itself_is_never_turned_into_a_reference() -> None:
    """The trap that would fail every job at exec time instead of at render.

    Manifests concatenate: `{{ global_password_prefix }}_pw_agent_curator`.
    Substituting the prefix alone renders
    `secret:global_password_prefix_pw_agent_curator` — a name nothing holds — so
    the concatenations are matched WHOLE and replaced by a reference to a name
    the store carries.
    """
    src = CATALOG.read_text(encoding="utf-8")
    m = re.search(r'"\{\{ global_password_prefix \}\}":\s*(\S+)', src)
    assert m, "the bare-prefix substitution is gone; check what replaced it"
    assert not m.group(1).startswith('"secret:'), (
        "`{{ global_password_prefix }}` now maps to a reference. Every "
        "concatenated site renders as `secret:global_password_prefix_pw_…`, "
        "which resolves to nothing and fails the job when it runs rather than "
        "when it is registered."
    )
    whole = re.findall(r'"\{\{ global_password_prefix \}\}_pw_(\w+)":\s*"secret:', src)
    assert whole, (
        "no whole-literal substitutions remain, so the agent client secrets are "
        "back to being rendered as values."
    )


def test_the_daemon_resolves_at_exec_time() -> None:
    """Since 2026-08-12 the resolution logic lives in pulse/secrets.py (shared
    with the on-demand shell runners — see test_secret_resolution_is_shared.py);
    the daemon's `_resolve_secrets` is a delegation. Both halves are asserted:
    the daemon still resolves at the exec site, and the module it delegates to
    still refuses on an unknown name."""
    src = DAEMON.read_text(encoding="utf-8")
    assert "self._resolve_secrets(env" in src, (
        "the Pulse daemon no longer resolves references at exec time. Every "
        "job would receive the literal string `secret:…` as its credential."
    )
    body = src[src.index("def _resolve_secrets"):]
    body = body[: body.index("\n    def ", 1)]
    assert "resolve_env(" in body, (
        "`_resolve_secrets` no longer delegates to pulse.secrets.resolve_env — "
        "either the resolution went missing or a second implementation grew "
        "back inside the daemon."
    )
    resolver = RESOLVER.read_text(encoding="utf-8")
    assert "raise UnresolvableSecretError" in resolver, (
        "an unresolvable reference no longer refuses. Passing `secret:foo` "
        "through hands a subprocess a token-shaped string: the call 401s, the "
        "job reports a plausible upstream error, and the real fault — a name "
        "that is not in the store — is invisible."
    )
    assert "secrets.yml" in resolver, "the resolver no longer reads the 0600 store"


def test_the_store_is_read_per_resolution_not_cached() -> None:
    """A converge rewrites the store; a caller holding a boot-time copy would
    authenticate with a rotated-away value and blame the upstream."""
    src = RESOLVER.read_text(encoding="utf-8")
    body = src[src.index("def load_store"):]
    body = body[: body.index("\ndef ", 1)]
    assert "yaml.safe_load" in body, "the store reader stopped parsing the file"
    assert "_cache" not in body and "@cache" not in body and "lru_cache" not in src, (
        "the secret store is cached. After a prefix rotation the daemon would "
        "keep presenting the old value until it was restarted."
    )


def test_every_referenced_name_is_one_the_store_declares() -> None:
    """A reference to a name the template never writes is a job that cannot run.

    Checked against `templates/secrets.yml.j2` rather than the operator's live
    file, so this holds on a machine that has never converged.
    """
    referenced = set(re.findall(r'"secret:(\w+)"', CATALOG.read_text(encoding="utf-8")))
    declared = set(re.findall(r"^(\w+):", STORE_TEMPLATE.read_text(encoding="utf-8"), re.M))
    missing = sorted(referenced - declared)
    assert not missing, (
        f"the catalog references name(s) the secrets template does not write: "
        f"{missing}. Each one is a job that will refuse at exec time — correctly, "
        "but for a reason introduced here rather than by the operator."
    )


def test_the_resolver_declares_the_parser_it_needs() -> None:
    """The repo is not the running system, in its sharpest form: a dependency.

    MEASURED 2026-08-11, minutes after the references landed. The repo-side
    probe resolved all 25 jobs; the DEPLOYED venv resolved 0, because
    `~/pulse/venv` carried no YAML parser. `_secret_store()` caught the
    ImportError, logged it, returned `{}`, and every job refused — correctly,
    and for a reason that existed only in the runtime. The operator's own
    interpreter has yaml, which is exactly why the check passed where it was
    written and failed where it runs.

    The refusal was the honest outcome; the declaration is the fix.
    """
    pyproject = (REPO / "files/anatomy/pulse/pyproject.toml").read_text(encoding="utf-8")
    deps = pyproject[pyproject.index("dependencies = ["):]
    deps = deps[: deps.index("]")]
    assert re.search(r"(?i)pyyaml", deps), (
        "the Pulse package no longer declares a YAML parser, but the daemon "
        "reads ~/.nos/secrets.yml to resolve every `secret:` reference. Without "
        "it the store parses as empty and all reference-carrying jobs refuse — "
        "silently in the repo, loudly and only on the host."
    )
    resolver = RESOLVER.read_text(encoding="utf-8")
    assert "import yaml" in resolver, (
        "the resolver no longer imports the parser it declares"
    )


def test_no_secret_shaped_token_is_substituted_as_a_value() -> None:
    """The `_pw_` blind spot, closed by shape instead of by list.

    MEASURED 2026-08-12, live wing.db: the `audit-chain-verify` row carried
    `WING_EVENTS_HMAC_SECRET_RETIRED` as a 64-hex literal — the LEAKED chain
    key, the very one rotation retired — while this file's docstring said
    "0 plaintext". Both were true: the 2026-08-11 sweep and its gate keyed on
    the `_pw_` naming pattern, and the retired key is not `_pw_`-shaped. A
    claim scoped by a pattern reads as a claim about the world.

    So this asserts by SHAPE over the whole substitution table: any token whose
    name says it is credential-like must map to a `secret:` reference, never
    through `_env(` — a value channel. New secret-shaped tokens are covered the
    day they are added, not the day someone remembers this file.
    """
    src = CATALOG.read_text(encoding="utf-8")
    secretish = re.compile(r"(secret|token|password|_pw_|hmac|credential)", re.I)
    offenders = []
    for m in re.finditer(r'"(\{\{ [^"]+ \}\}[^"]*)":\s*(_env\("([^"]+)"\)|"[^"]*")', src):
        token, value = m.group(1), m.group(2)
        # The prefix itself must stay a value (concatenation — see the gate
        # above); it is the one deliberate exception and it is named.
        if token == "{{ global_password_prefix }}":
            continue
        if secretish.search(token) and value.startswith("_env("):
            offenders.append(f"{token} -> {value}")
    assert not offenders, (
        "secret-shaped token(s) substituted as VALUES into pulse_jobs.env_json "
        "(the retired-chain-key class):\n  " + "\n  ".join(offenders)
    )
