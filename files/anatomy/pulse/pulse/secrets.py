"""THE `secret:` reference resolver — one implementation, every caller.

`secret:<name>` in a job's env is a POINTER into ``~/.nos/secrets.yml``
(0600), never a value (AgentKit's ``secret_ref`` rule, applied to the
runtime that actually runs the jobs — see ``discover-pulse-catalog.py``).

Two kinds of caller share this module, and sharing is the point:

- the Pulse daemon (``daemon.py::_resolve_secrets`` delegates here), and
- the on-demand shell runners (``tools/run-*.sh``, ``cortex-seed-fixtures.sh``)
  via ``tools/lib/pulse-env.sh`` → ``python3 -m pulse.secrets``.

The 2026-08-11 migration shipped with only the daemon resolving; every
operator-triggered run of a migrated job exported the literal
``secret:wing_api_token`` and died on a 401 at whatever tier the job pins.
Two resolvers that agree today are the estate's oldest defect wearing a
new hat, so the semantics live HERE and nowhere else:

- **Presence, not truthiness.** ``mail_password`` is legitimately ``''`` on a
  mailpit estate; declared-and-empty is an answer, not-declared is a fault.
- **Refuse on an unknown name, never pass the literal through.** A
  ``secret:foo`` reaching a subprocess is a token-shaped string: the call
  401s somewhere else and the real fault becomes invisible.
- **Read per resolution, never cache.** A converge rewrites the store; a
  holder of a boot-time copy authenticates with a rotated-away value and
  blames the upstream.

Import surface is stdlib + PyYAML only — the host interpreter that runs the
shell tools must be able to execute this without the daemon's dependencies.
"""

from __future__ import annotations

import logging
import pathlib

log = logging.getLogger("pulse.secrets")

#: What a stored env value looks like when it is a POINTER rather than a
#: value. Deliberately one scheme, not AgentKit's two: `infisical:` would
#: mean this runtime holds a vault credential, which is the thing it is
#: trying to stop holding.
SECRET_PREFIX = "secret:"


class UnresolvableSecretError(RuntimeError):
    """A reference names something the store does not declare.

    Subclasses RuntimeError so the daemon's existing exception path
    (synthetic rc=255 run-finish) keeps its behaviour unchanged.
    """


def secrets_path() -> pathlib.Path:
    return pathlib.Path.home() / ".nos/secrets.yml"


def load_store() -> dict:
    """Read per resolution, not cached.

    A converge rewrites this file; a caller holding a parsed copy would
    authenticate with a rotated-away value and report the upstream's
    refusal as the fault. The file is small and this runs once per job.

    Unreadable (missing parser, bad YAML) parses as EMPTY — which makes
    every reference unresolvable and refuses the job. Fail-closed: the
    2026-08-11 deployed-venv-without-PyYAML incident refused 25/25 jobs
    loudly rather than passing literals quietly, and that was correct.
    """
    path = secrets_path()
    if not path.is_file():
        return {}
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:                                      # noqa: BLE001
        log.error("could not read %s: %s", path, exc)
        return {}


def resolve_env(env: dict) -> dict:
    """``secret:wing_api_token`` → the value from ``~/.nos/secrets.yml``.

    A REFERENCE THAT CANNOT BE RESOLVED FAILS THE JOB (raises
    ``UnresolvableSecretError`` naming every missing entry). Literals pass
    through untouched, so unmigrated jobs keep running unchanged.
    """
    refs = {k: v for k, v in env.items()
            if isinstance(v, str) and v.startswith(SECRET_PREFIX)}
    if not refs:
        return env

    store = load_store()
    out = dict(env)
    missing = []
    for key, ref in refs.items():
        name = ref[len(SECRET_PREFIX):]
        # PRESENCE, not truthiness. `mail_password` is legitimately '' on an
        # estate using mailpit rather than Stalwart, and the first cut of
        # this check treated an empty value as an absent name — which would
        # have refused every notification job on a correctly-configured
        # host. Declared-and-empty is an answer; not declared is a fault.
        if name not in store:
            missing.append(f"{key} -> {name}")
            continue
        out[key] = str(store[name] if store[name] is not None else '')
    if missing:
        raise UnresolvableSecretError(
            "unresolvable secret reference(s): " + ", ".join(missing)
            + f" (store: {secrets_path()}). The job was NOT run — a "
            "literal 'secret:…' reaching a subprocess would look like a "
            "credential and fail as one somewhere else."
        )
    return out


def token_preflight(env: dict) -> tuple[int, str]:
    """Ask Authentik the ONE question a liveness probe cannot: can THIS
    client mint a token RIGHT NOW.

    Found 2026-08-25: every agent runner pre-flighted with
    `GET /-/health/live/`, printed `✓ … liveness → 200`, and handed the job
    to pulse-run-agent.sh — whose first act is a client_credentials grant
    that can die on `invalid_grant`. The server answering says nothing about
    whether the credential the estate holds is the one the provider holds,
    and nothing on the estate compared the two. A check that cannot fail the
    way it matters is the estate's signature defect.

    Takes the job env (references still welcome — they are resolved here,
    through the same code path the daemon uses), performs the actual grant,
    and returns `(exit_code, message)`:

        0 — HTTP 200; the credential is the one Authentik accepts
        1 — the grant was REFUSED (or the server did not answer) — message
            carries the client_id and HTTP status, never the secret
        2 — the env carries no usable credential / no NOS_AUTHENTIK_URL —
            fail-closed, a job this function cannot vouch for does not run

    (Unresolvable references raise UnresolvableSecretError exactly like
    resolve_env — the CLI maps that to exit 3, same as `--exports`.)

    Lives HERE, beside the resolver, for the same reason the resolver does:
    one implementation, every caller (tools/lib/pulse-env.sh is a zero-logic
    shim; a jq-and-curl copy in shell would be the second implementation
    that agrees today and drifts tomorrow). stdlib only — urllib is the
    whole HTTP client, and the secret never touches argv or a log line.
    """
    creds = _client_creds(env)  # may raise UnresolvableSecretError — see CLI
    if isinstance(creds, str):
        return 2, creds
    cid, secret, ak_url = creds
    code, _body = _grant(ak_url, cid, secret)
    if code == 200:
        return 0, (f"✓ Authentik token grant for {cid} → 200 "
                   "(credential verified, not just liveness)")
    return 1, _grant_refused(ak_url, cid, code)


def mint_agent_token(env: dict) -> tuple[int, str]:
    """The SAME grant as token_preflight, keeping the token it throws away.

    Found 2026-08-28 (docs/plans/rsi-research/07-first-bound-night.md §4): the
    CLI path exchanges the agent's client_credentials and hands the child
    NOS_AUTHENTIK_TOKEN; the BOUND path performed no exchange at all, so
    McpBoneTool sent no Authorization header and every scoped Bone endpoint
    answered 401. A scoped Wing token on a runtime that cannot authenticate to
    Bone is half a principal.

    Returns `(0, access_token)` or `(1|2, message)` with the same exit-code
    meanings as token_preflight. The token is returned, never logged.

    Scopes come from `NOS_AGENT_SCOPES` in the env — Authentik grants ONLY
    what is explicitly requested, so an unscoped grant yields a JWT whose
    scope claim is empty and whose every scoped call 403s.
    """
    creds = _client_creds(env)
    if isinstance(creds, str):
        return 2, creds
    cid, secret, ak_url = creds
    code, body = _grant(ak_url, cid, secret, str(env.get("NOS_AGENT_SCOPES") or ""))
    if code != 200:
        return 1, _grant_refused(ak_url, cid, code)
    import json as _json
    try:
        token = str((_json.loads(body) or {}).get("access_token") or "")
    except ValueError:
        token = ""
    if not token:
        return 1, (f"Authentik answered 200 for client_id={cid} with no "
                   "access_token — the body is not a token response")
    return 0, token


def _client_creds(env: dict):
    """(client_id, secret, authentik_url) — or a refusal message as a str."""
    env = resolve_env(env)  # may raise UnresolvableSecretError — see CLI
    cid = env.get("NOS_AGENT_CLIENT_ID") or env.get("NOS_CONDUCTOR_CLIENT_ID") or ""
    secret = (env.get("NOS_AGENT_CLIENT_SECRET")
              or env.get("NOS_CONDUCTOR_CLIENT_SECRET") or "")
    ak_url = env.get("NOS_AUTHENTIK_URL", "")
    if not cid or not secret:
        return ("job env carries no agent client credential "
                "(NOS_AGENT_CLIENT_ID/SECRET) — refusing to vouch for it")
    if not ak_url:
        return ("NOS_AUTHENTIK_URL is empty — cannot verify the client "
                "credential, refusing to proceed on hope")
    return cid, secret, ak_url


def _grant(ak_url: str, cid: str, secret: str, scopes: str = "") -> tuple[int, bytes]:
    """One client_credentials POST. `(status or 0 for no answer, body)`."""
    import ssl
    import urllib.error
    import urllib.parse
    import urllib.request

    fields = {
        "grant_type": "client_credentials",
        "client_id": cid,
        "client_secret": secret,
    }
    if scopes:
        fields["scope"] = scopes
    body = urllib.parse.urlencode(fields).encode()
    # Local estates terminate TLS with mkcert; the runners' curl used -k.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(
            urllib.request.Request(_token_url(ak_url), data=body, method="POST"),
            timeout=15, context=ctx,
        ) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, b""


def _token_url(ak_url: str) -> str:
    return ak_url.rstrip("/") + "/application/o/token/"


def _grant_refused(ak_url: str, cid: str, code: int) -> str:
    shown = code if code else "no answer"
    return (f"Authentik {_token_url(ak_url)} returned {shown} for "
            f"client_id={cid} — this client cannot obtain a token. 400 means "
            "the provider refused the credential the estate holds (store: "
            f"{secrets_path()} vs the provider's client_secret); "
            "'no answer' means the server is unreachable.")


# ── CLI — the shell callers' entry point ─────────────────────────────────
#
#   printf '%s' "$JOB_ENV_JSON" | python3 -m pulse.secrets            # JSON out
#   printf '%s' "$JOB_ENV_JSON" | python3 -m pulse.secrets --exports  # export lines
#   printf '%s' "$JOB_ENV_JSON" | python3 -m pulse.secrets --token-preflight
#   printf '%s' "$JOB_ENV_JSON" | python3 -m pulse.secrets --mint-token
#
# Exit codes: 0 resolved · 2 malformed input · 3 unresolvable reference;
# --token-preflight and --mint-token add 1 = the grant was refused / server
# unreachable. stdout carries NOTHING on failure — a partial env is worse
# than none, and for --mint-token a message on stdout would be exported as
# if it were a bearer.

_IDENT = r"^[A-Za-z_][A-Za-z0-9_]*$"


def _main(argv: list[str]) -> int:
    import json
    import re
    import shlex
    import sys

    exports = False
    preflight = False
    mint = False
    for arg in argv:
        if arg == "--exports":
            exports = True
        elif arg == "--token-preflight":
            preflight = True
        elif arg == "--mint-token":
            mint = True
        else:
            print(f"pulse.secrets: unknown argument {arg!r} (only --exports "
                  "/ --token-preflight / --mint-token)", file=sys.stderr)
            return 2
    if sum((exports, preflight, mint)) > 1:
        print("pulse.secrets: --exports, --token-preflight and --mint-token "
              "are separate calls", file=sys.stderr)
        return 2

    raw = sys.stdin.read().strip()
    if raw in ("", "null", "[]"):
        # PHP json_encode spells an empty env as [] — an empty dict, not a
        # malformed one. pulse_jobs rows measurably carry it (backup, npm-scan).
        env = {}
    else:
        try:
            env = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"pulse.secrets: stdin is not JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(env, dict):
            print(f"pulse.secrets: env must be a JSON object, got "
                  f"{type(env).__name__}", file=sys.stderr)
            return 2

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING,
                        format="pulse.secrets: %(message)s")
    if preflight:
        try:
            rc, message = token_preflight(env)
        except UnresolvableSecretError as exc:
            print(f"pulse.secrets: {exc}", file=sys.stderr)
            return 3
        print(message, file=(sys.stdout if rc == 0 else sys.stderr))
        return rc

    if mint:
        try:
            rc, out = mint_agent_token(env)
        except UnresolvableSecretError as exc:
            print(f"pulse.secrets: {exc}", file=sys.stderr)
            return 3
        if rc != 0:
            print(f"pulse.secrets: {out}", file=sys.stderr)
            return rc
        sys.stdout.write(out)          # the token, alone, no newline noise
        return 0

    try:
        resolved = resolve_env(env)
    except UnresolvableSecretError as exc:
        print(f"pulse.secrets: {exc}", file=sys.stderr)
        return 3

    if exports:
        for key in sorted(resolved):
            if not re.match(_IDENT, key):
                # A key that is not a shell identifier cannot become an
                # `export` line without becoming an injection channel.
                print(f"pulse.secrets: env key {key!r} is not a valid "
                      "shell identifier — refusing to emit exports",
                      file=sys.stderr)
                return 2
            sys.stdout.write(f"export {key}={shlex.quote(str(resolved[key]))}\n")
    else:
        json.dump(resolved, sys.stdout)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
