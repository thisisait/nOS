#!/usr/bin/env bash
# tools/run-agent.sh — run an AgentKit agent against the LIVE estate.
#
# WHY THIS EXISTS. `bin/run-agent.php` is the documented entry point for a
# supervised agent run, and it CANNOT WORK from a shell, because the daemon's
# environment is in the launchd plist and a terminal inherits none of it.
# Measured 2026-08-16, running the first supervised night, in this order:
#
#   1. no NOS_REPO_ROOT   -> the DI container dies before the agent loads:
#        TypeError: MigrationWriteTool::__construct(): Argument #1
#        ($repoRoot) must be of type string, false given
#      `::getenv()` yields FALSE for unset, and common.neon's own comment
#      promises "empty -> the tool fail-softs" — a fail-soft that cannot
#      happen, because false is a type error, not an empty string.
#
#   2. no NOS_ARMED_BACKENDS -> a BOUND agent resolves UNBOUND and asks for a
#      key nobody sets: "ANTHROPIC_API_KEY missing". The binding is not
#      broken; it was never armed in this process. The error names the wrong
#      thing, which is the expensive kind.
#
#   3. no tier model env  -> an armed backend with an empty model id refuses
#      at resolution rather than sending a blank model. Correct, and equally
#      confusing when the cause is a missing export.
#
# WHAT THIS REFUSES TO DO. Start a run it cannot make honest. Every variable
# below is read FROM THE RUNNING JOB — `launchctl print` is the daemon's own
# statement about what it holds, not a second copy of the plist that could
# drift — and a missing one aborts BEFORE the agent opens a session and spends
# anything. A half-configured run costs money and produces a session row that
# looks like evidence.
#
# USAGE
#   tools/run-agent.sh --agent=librarian --prompt="…"
#   tools/run-agent.sh --show-env                 # print what resolved, run nothing
#   tools/run-agent.sh --ceiling-tokens=5000 --agent=…   # tighten for one run
#   tools/run-agent.sh --ceiling-seconds=120 --agent=…
#
# Everything else is passed through to bin/run-agent.php unchanged.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WING_APP="${WING_APP:-$HOME/wing/app}"
LABEL="${WING_LAUNCHD_LABEL:-eu.thisisait.nos.wing}"

SHOW_ENV=0
PASSTHRU=()
for arg in "$@"; do
    case "$arg" in
        --show-env)            SHOW_ENV=1 ;;
        --ceiling-tokens=*)    export NOS_AGENT_SESSION_TOKEN_CEILING="${arg#*=}" ;;
        --ceiling-seconds=*)   export NOS_AGENT_SESSION_WALL_CLOCK_S="${arg#*=}" ;;
        *)                     PASSTHRU+=("$arg") ;;
    esac
done

if [[ ! -d "$WING_APP" ]]; then
    echo "[run-agent] no deployed Wing at $WING_APP — converge first." >&2
    exit 2
fi

# ── Read the RUNNING job, not the file on disk ───────────────────────────────
# `launchctl print` is what the process actually has. The plist is what it will
# have at the next bootstrap, and those differ every time a converge renders a
# variable the daemon has not reloaded — the drift that cost this estate a
# notification link in August and is documented in roles/pazny.wing.
if ! LOADED="$(launchctl print "gui/$(id -u)/${LABEL}" 2>/dev/null)"; then
    echo "[run-agent] ${LABEL} is not loaded in launchd — start Wing first." >&2
    exit 2
fi

# The env block prints as `KEY => value` lines, indented.
resolve() {
    printf '%s\n' "$LOADED" \
        | sed -n "s/^[[:space:]]*$1 => \(.*\)$/\1/p" \
        | head -1
}

# Names the child needs, and why. Absence of any of these is not a warning.
REQUIRED=(NOS_REPO_ROOT)
OPTIONAL=(NOS_ARMED_BACKENDS NOS_MINIMAX_MODEL NOS_MINIMAX_SMALL_MODEL \
          NOS_MISTRAL_MODEL NOS_MISTRAL_SMALL_MODEL \
          WING_API_URL WING_API_TOKEN KEAP_API_URL BONE_API_URL)

missing=()
for name in "${REQUIRED[@]}"; do
    value="$(resolve "$name")"
    if [[ -z "$value" ]]; then
        missing+=("$name")
    else
        export "$name=$value"
    fi
done
for name in "${OPTIONAL[@]}"; do
    value="$(resolve "$name")"
    [[ -n "$value" ]] && export "$name=$value"
done

if [[ ${#missing[@]} -gt 0 ]]; then
    echo "[run-agent] REFUSING: the running Wing job does not carry: ${missing[*]}" >&2
    echo "[run-agent] Without them the container dies or the agent resolves" >&2
    echo "[run-agent] unbound — and the error names something else." >&2
    exit 1
fi

if [[ "$SHOW_ENV" == "1" ]]; then
    echo "[run-agent] resolved from the running ${LABEL}:"
    for name in "${REQUIRED[@]}" "${OPTIONAL[@]}"; do
        value="${!name:-}"
        [[ -z "$value" ]] && { printf '  %-26s <absent>\n' "$name"; continue; }
        case "$name" in
            *TOKEN|*SECRET|*KEY) printf '  %-26s <set, %d chars>\n' "$name" "${#value}" ;;
            *)                   printf '  %-26s %s\n' "$name" "$value" ;;
        esac
    done
    exit 0
fi

if [[ ${#PASSTHRU[@]} -eq 0 ]]; then
    echo "[run-agent] nothing to run — pass --agent=<name> (see --show-env)." >&2
    exit 2
fi

# A bound run is about to spend real money at a third party. Say which backend
# before it happens, so the operator watching can stop it if it is the wrong one.
echo "[run-agent] armed backends: ${NOS_ARMED_BACKENDS:-<none>}"
echo "[run-agent] ceilings: tokens=${NOS_AGENT_SESSION_TOKEN_CEILING:-<default>} wall=${NOS_AGENT_SESSION_WALL_CLOCK_S:-<default>}s"

cd "$WING_APP"
exec php bin/run-agent.php "${PASSTHRU[@]}"
