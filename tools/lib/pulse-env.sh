#!/usr/bin/env bash
# =============================================================================
# pulse-env.sh — resolve `secret:<name>` references in a pulse_jobs env blob.
#
# Sourced by every on-demand runner that reads pulse_jobs.env_json
# (tools/run-*.sh, tools/cortex-seed-fixtures.sh). This file contains NO
# resolution logic — it is a shim over THE resolver, pulse/secrets.py, the
# same module the Pulse daemon delegates to. One implementation, N callers:
# the 2026-08-11 migration proved that a resolver the shell path does not
# share is a resolver the shell path does not have (every operator-triggered
# run of a migrated job exported the literal `secret:wing_api_token` and
# died on a 401).
#
# Usage (after `source tools/lib/pulse-env.sh`):
#
#   JOB_ENV_JSON=$(printf '%s' "$JOB_ENV_JSON" | resolve_pulse_env_json) \
#       || _die "…"                       # JSON in → resolved JSON out
#   … | resolve_pulse_env_json --exports  # JSON in → `export K='v'` lines
#
# Exit codes (from python3 -m pulse.secrets):
#   0 resolved · 2 malformed input · 3 unresolvable reference (stdout EMPTY —
#   the literal is never passed through; the missing name is on stderr).
# =============================================================================

if [ -n "${BASH_SOURCE:-}" ]; then
    _PULSE_ENV_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
    # zsh (an operator sourcing this interactively — the wing-live-verify
    # recipes source things too): FUNCTION_ARGZERO (on by default) makes $0
    # the file being sourced for the duration of the source. Measured here
    # rather than assumed: ${(%):-%N} reads as "(eval)" once eval-wrapped
    # for bash's parser, so $0 is the one spelling both shells survive.
    _PULSE_ENV_LIB_DIR="$(cd "$(dirname "$0")" && pwd)"
fi
_PULSE_PKG_DIR="$(cd "${_PULSE_ENV_LIB_DIR}/../../files/anatomy/pulse" && pwd)" \
    || { echo "pulse-env.sh: cannot locate files/anatomy/pulse from ${_PULSE_ENV_LIB_DIR}" >&2; return 1; }

# stdin: env JSON (object; `[]`/`null`/empty accepted as empty) → stdout: see
# usage above. The store is ~/.nos/secrets.yml, read per call, never cached.
resolve_pulse_env_json() {
    PYTHONPATH="${_PULSE_PKG_DIR}${PYTHONPATH:+:$PYTHONPATH}" \
        python3 -m pulse.secrets "$@"
}

# pulse_token_preflight <env-json>
#
# Ask the ONE question the old liveness probe could not: can THIS client mint
# a token from Authentik RIGHT NOW. `/-/health/live/` returning 200 proves the
# server answers; every agent runner shipped with only that check, so a
# pre-flight printed "✓ Authentik … liveness → 200" and the run died moments
# later on `invalid_grant` — a check that cannot fail the way it matters.
#
# ZERO-LOGIC SHIM, like resolve_pulse_env_json above and for the same reason:
# the grant check lives in pulse/secrets.py::token_preflight beside the
# resolver it depends on. Exit codes: 0 = grant OK · 1 = grant refused or
# server unreachable · 2 = env carries no usable credential (fail-closed) ·
# 3 = unresolvable secret reference. The secret never appears on argv, in a
# message, or in a log line.
pulse_token_preflight() {
    printf '%s' "$1" | PYTHONPATH="${_PULSE_PKG_DIR}${PYTHONPATH:+:$PYTHONPATH}" \
        python3 -m pulse.secrets --token-preflight
}
