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


# ── CLI — the shell callers' entry point ─────────────────────────────────
#
#   printf '%s' "$JOB_ENV_JSON" | python3 -m pulse.secrets            # JSON out
#   printf '%s' "$JOB_ENV_JSON" | python3 -m pulse.secrets --exports  # export lines
#
# Exit codes: 0 resolved · 2 malformed input · 3 unresolvable reference.
# stdout carries NOTHING on failure — a partial env is worse than none.

_IDENT = r"^[A-Za-z_][A-Za-z0-9_]*$"


def _main(argv: list[str]) -> int:
    import json
    import re
    import shlex
    import sys

    exports = False
    for arg in argv:
        if arg == "--exports":
            exports = True
        else:
            print(f"pulse.secrets: unknown argument {arg!r} "
                  "(only --exports)", file=sys.stderr)
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
