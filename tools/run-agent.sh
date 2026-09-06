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
AGENT_NAME=""
PASSTHRU=()
for arg in "$@"; do
    case "$arg" in
        --show-env)            SHOW_ENV=1 ;;
        --agent=*)             AGENT_NAME="${arg#*=}"; PASSTHRU+=("$arg") ;;
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

# EXPORT WHAT THE DAEMON HAS, rather than a list of what it is thought to need.
#
# The first draft named ten variables. The first real ceremony then failed on
# `KEAP_AGENT_TOKEN_RO is not set`, then a Bone 401, then "Missing HMAC
# headers" — none of them missing from the daemon, all of them missing from
# THAT LIST. The agent had four working tools and no credential for three of
# them, and spent 39k tokens discovering it politely.
#
# A hand-kept enumeration of someone else's environment drifts the moment the
# environment grows, and it drifts silently, because an unexported credential
# looks exactly like an unconfigured service. The running job is the authority
# on what the runtime holds; this passes it through and checks only the names
# whose ABSENCE has a specific, misleading symptom.
# THE MEASUREMENT KNOBS, and only these, may be set by the caller.
#
# The passthrough exists because a terminal inherits none of the daemon's
# environment, and it overwrites unconditionally on purpose — a caller's stale
# WING_API_TOKEN winning over the daemon's current one is a bug that looks like
# an auth failure somewhere else. But tools/nos-ops-harness.py has to vary the
# BACKEND and the MODEL ID per run; that is the whole measurement, and with an
# unconditional overwrite every size ran on whatever the plist pinned while the
# report labelled it otherwise. None of these three is a credential.
# A space-padded string, not an associative array: /bin/bash on macOS is 3.2
# and `declare -A` is a syntax error there — which this script found the first
# time it ran after the change.
CALLER_WINS=" "
# NOS_MINIMAX_MODEL joined 2026-09-06: the block above says the whole point is
# to "vary the BACKEND and the MODEL ID per run", but the minimax model id was
# not caller-overridable — so a run could pick the minimax backend yet never the
# minimax VERSION (M3 / M2.7 / M2.7-highspeed / M2.5 / …). Same rule as the local
# model ids: a caller who sets it wins over the plist; unset, the daemon's pin holds.
for k in NOS_ARMED_BACKENDS NOS_LOCAL_MODEL NOS_LOCAL_SMALL_MODEL NOS_MINIMAX_MODEL; do
    eval "v=\${$k:-}"
    [ -n "$v" ] && CALLER_WINS="${CALLER_WINS}${k} "
done

while IFS= read -r line; do
    name="${line%% => *}"
    value="${line#* => }"
    [[ "$name" =~ ^[A-Z][A-Z0-9_]*$ ]] || continue
    case "$CALLER_WINS" in *" $name "*) continue ;; esac
    export "$name=$value"
done < <(printf '%s\n' "$LOADED" | sed -n 's/^[[:space:]]*\([A-Z][A-Z0-9_]*\) => \(.*\)$/\1 => \2/p')

# Absence of these is not a warning — each produces an error naming something
# other than itself (a TypeError in the DI container; an unbound resolve
# demanding a key nobody sets).
REQUIRED=(NOS_REPO_ROOT)
REPORTED=(NOS_ARMED_BACKENDS NOS_MINIMAX_MODEL WING_API_TOKEN NOS_AGENT_WING_TOKEN \
          NOS_AUTHENTIK_TOKEN KEAP_AGENT_TOKEN_RO WING_EVENTS_HMAC_SECRET)

# ── The agent's OWN Wing principal ───────────────────────────────────────────
# The passthrough above just handed this process the daemon's WING_API_TOKEN —
# the OPERATOR's admin bearer. An agent presenting it is recorded as the
# operator: every event it writes carries actor_id 'ansible-provisioned', and
# "which agent did this" has no answer. Its own api_tokens row already exists
# (roles/pazny.wing/tasks/post.yml provisions one per agent, named after it);
# what the CLI path lacked was any way to present it.
#
# Absence is a WARN and not a refusal: on a pre-converge estate the per-agent
# secret is not persisted yet, and refusing would break the runner over an
# attribution defect it is fixing. McpWingTool logs the same fallback.
SECRETS_FILE="${NOS_SECRETS_FILE:-$HOME/.nos/secrets.yml}"
if [[ -n "$AGENT_NAME" ]]; then
    secret_key="${AGENT_NAME//-/_}_wing_api_token"
    agent_token="$(python3 -c 'import sys,yaml;print((yaml.safe_load(open(sys.argv[1])) or {}).get(sys.argv[2]) or "")' \
        "$SECRETS_FILE" "$secret_key" 2>/dev/null || true)"
    if [[ -n "$agent_token" ]]; then
        export NOS_AGENT_WING_TOKEN="$agent_token"
    else
        echo "[run-agent] WARN: no ${secret_key} in ${SECRETS_FILE} — Wing will" >&2
        echo "[run-agent] attribute this run to the operator token, not to ${AGENT_NAME}." >&2
    fi
fi

# ── The agent's OWN Bone principal ───────────────────────────────────────────
# Measured on the first bound night
# (docs/plans/rsi-research/07-first-bound-night.md §4): the CLI path
# exchanges the agent's client_credentials for a scoped Authentik token and
# hands the child NOS_AUTHENTIK_TOKEN; THIS path performed no exchange at all,
# so McpBoneTool sent no Authorization header and every Bone endpoint behind
# require_scope() answered 401. A scoped Wing token on a runtime that cannot
# authenticate to Bone is half a principal.
#
# The grant is pulse/secrets.py — the same implementation the daemon and every
# other runner use, not a second curl. Scopes are the agent's `capabilities:`,
# because Authentik grants only what is explicitly requested.
#
# WARN, not refuse, for the same reason as the Wing token above: a
# pre-converge estate has no agent client secret yet, and the tools the run
# does not need still work. It says so, so a 401 is never a mystery.
# shellcheck source=lib/pulse-env.sh
source "$REPO_ROOT/tools/lib/pulse-env.sh"
if [[ -n "$AGENT_NAME" && -z "${NOS_AUTHENTIK_TOKEN:-}" ]]; then
    grant_env=$(AGENT_NAME="$AGENT_NAME" \
        NOS_AGENT_PROFILE="${NOS_AGENT_PROFILE:-$REPO_ROOT/files/anatomy/agents/$AGENT_NAME/agent.yml}" \
        python3 - <<'PY' 2>/dev/null || true
import json, os, yaml
name = os.environ["AGENT_NAME"]
profile = os.environ["NOS_AGENT_PROFILE"]
scopes = os.environ.get("NOS_AGENT_SCOPES", "")
if not scopes:
    try:
        with open(profile) as fh:
            scopes = " ".join(yaml.safe_load(fh).get("capabilities") or [])
    except Exception:
        scopes = ""
print(json.dumps({
    "NOS_AUTHENTIK_URL": os.environ.get("NOS_AUTHENTIK_URL", ""),
    "NOS_AGENT_CLIENT_ID": os.environ.get("NOS_AGENT_CLIENT_ID") or f"nos-{name}",
    # A pointer, resolved by the same store reader the daemon uses. The Pulse
    # path already sets this to exactly this spelling.
    "NOS_AGENT_CLIENT_SECRET": (os.environ.get("NOS_AGENT_CLIENT_SECRET")
                                or f"secret:agent_{name.replace('-', '_')}_client_secret"),
    "NOS_AGENT_SCOPES": scopes,
}))
PY
    )
    mint_err="$(mktemp -t nos-agent-mint)"
    if agent_ak_token="$(pulse_mint_agent_token "$grant_env" 2>"$mint_err")" \
       && [[ -n "$agent_ak_token" ]]; then
        export NOS_AUTHENTIK_TOKEN="$agent_ak_token"
        echo "[run-agent] minted an Authentik token for nos-${AGENT_NAME}" >&2
    else
        # Print the mint's OWN reason. "No token" is not a diagnosis, and the
        # operator shell reaches here for a mundane one — NOS_AUTHENTIK_URL is
        # in the Pulse job env, not in the daemon environment this script
        # inherits — which reads as a broken credential unless it says so.
        echo "[run-agent] WARN: no Authentik token for ${AGENT_NAME} — Bone" >&2
        echo "[run-agent] endpoints behind require_scope() will answer 401." >&2
        sed 's/^/[run-agent]   /' "$mint_err" >&2
    fi
    rm -f "$mint_err"
fi

missing=()
for name in "${REQUIRED[@]}"; do
    [[ -z "${!name:-}" ]] && missing+=("$name")
done

if [[ ${#missing[@]} -gt 0 ]]; then
    echo "[run-agent] REFUSING: the running Wing job does not carry: ${missing[*]}" >&2
    echo "[run-agent] Without them the container dies or the agent resolves" >&2
    echo "[run-agent] unbound — and the error names something else." >&2
    exit 1
fi

if [[ "$SHOW_ENV" == "1" ]]; then
    echo "[run-agent] resolved from the running ${LABEL}:" >&2
    for name in "${REQUIRED[@]}" "${REPORTED[@]}"; do
        value="${!name:-}"
        [[ -z "$value" ]] && { printf '  %-26s <absent>\n' "$name"; continue; }
        # ANYWHERE IN THE NAME, not at the end. The first draft matched
        # `*TOKEN|*SECRET|*KEY` as suffixes and printed KEAP_AGENT_TOKEN_RO in
        # full, because it ends in `_RO` — a redaction that covers the names it
        # was written against and leaks the next one someone adds.
        case "$name" in
            *TOKEN*|*SECRET*|*KEY*|*PASSWORD*|*HMAC*|*CREDENTIAL*)
                printf '  %-26s <set, %d chars>\n' "$name" "${#value}" ;;
            *)  printf '  %-26s %s\n' "$name" "$value" ;;
        esac
    done
    exit 0
fi

if [[ ${#PASSTHRU[@]} -eq 0 ]]; then
    echo "[run-agent] nothing to run — pass --agent=<name> (see --show-env)." >&2
    exit 2
fi

# A Pulse job carries its ceremony in NOS_AGENT_TASK (the CLI runner's spelling)
# because the catalog's arg-regex bans whitespace — a prompt cannot be an arg.
if [[ -n "${NOS_AGENT_TASK:-}" ]] \
   && ! printf '%s\n' ${PASSTHRU[@]+"${PASSTHRU[@]}"} | grep -q '^--prompt='; then
    PASSTHRU+=("--prompt=$NOS_AGENT_TASK")
fi

# A bound run is about to spend real money at a third party. Say which backend
# before it happens, so the operator watching can stop it if it is the wrong one.
echo "[run-agent] armed backends: ${NOS_ARMED_BACKENDS:-<none>}" >&2
echo "[run-agent] ceilings: tokens=${NOS_AGENT_SESSION_TOKEN_CEILING:-<default>} wall=${NOS_AGENT_SESSION_WALL_CLOCK_S:-<default>}s" >&2

# The same mutex the CLI path takes. Not `exec` below: exec would drop the
# release trap and leak the lock for the rest of the night.
# STDOUT IS THE SUMMARY, NOTHING ELSE (2026-08-30). Six of this script's
# sixteen `[run-agent]` lines went to stdout while ten already went to
# stderr; a caller that parses the summary — tools/nos-ops-harness.py does,
# 44 runs of it — got `[run-agent] armed backends: …` in front of the JSON
# and reported `runner emitted no JSON summary` for every single one.
# shellcheck source=../files/anatomy/scripts/agent-run-lock.sh
source "$REPO_ROOT/files/anatomy/scripts/agent-run-lock.sh"
nos_agent_lock_acquire "${NOS_AGENT_NAME:-agentkit}" 300 agentkit || exit 2

SUMMARY_FILE="$(mktemp -t nos-agent-summary)"
trap 'nos_agent_lock_release; rm -f "$SUMMARY_FILE"' EXIT

# THE SCHEDULER'S RUN AND THE AGENT'S SESSION ARE ONE THING (2026-08-29).
# The Pulse daemon hands its run's uuid4 down as PULSE_RUN_ID and records the
# same value as `pulse_runs.actor_action_id`; adopting it as the session uuid
# closes the last link, because the Runner already stamps the session uuid as
# `actor_action_id` on every event it writes. Without this the nightly run and
# the session it produced were two unrelated rows.
#
# Guarded on the UUID shape because bin/run-agent.php refuses anything else,
# and only when the caller has not already chosen one.
if [[ -n "${PULSE_RUN_ID:-}" ]] \
   && [[ "$PULSE_RUN_ID" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] \
   && [[ ! " ${PASSTHRU[*]} " == *" --session-uuid="* ]]; then
    PASSTHRU+=("--session-uuid=$PULSE_RUN_ID")
    echo "[run-agent] session uuid adopted from PULSE_RUN_ID — the run and the session are one row" >&2
fi

cd "$WING_APP"
php bin/run-agent.php "${PASSTHRU[@]}" | tee "$SUMMARY_FILE"

# ── MR post-step ─────────────────────────────────────────────────────────────
# The agent has no forge tool and must not get one: a session that can push is a
# session that can merge its own work. It writes into the working tree with
# `migration_file_write`, and THIS reads what the tool itself recorded —
# `metadata.path_written` on the agent_tool_result event — rather than trusting
# the model's prose about what it wrote. recipe-pr.sh re-validates through the
# recipe gates and refuses to open an MR that does not pass; a human merges.
#
# Recipes only. A migration write needs migration-pr.sh with a migration-id and
# a version bump in the same MR, and that path is NOT wired here — say so rather
# than open a half MR.
SESSION_UUID="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("session_uuid") or "")' "$SUMMARY_FILE" 2>/dev/null || true)"
if [[ -n "$SESSION_UUID" && -x "$REPO_ROOT/tools/recipe-pr.sh" ]]; then
    while IFS= read -r recipe; do
        svc="$(basename "$recipe" .yml)"
        echo "[run-agent] $recipe was written — opening an MR via recipe-pr.sh $svc" >&2
        (cd "$REPO_ROOT" && ./tools/recipe-pr.sh "$svc" --open-pr) \
            || echo "WARN: recipe-pr.sh refused $svc — the recipe is in the tree, NO MR was opened" >&2
    done < <(sqlite3 -readonly "${WING_DB_PATH:-$HOME/wing/app/data/wing.db}" \
        "SELECT DISTINCT json_extract(result_json, '\$.metadata.path_written')
           FROM events
          WHERE type = 'agent_tool_result' AND actor_action_id = '$SESSION_UUID'
            AND json_extract(result_json, '\$.metadata.path_written') LIKE 'upgrades/%'" 2>/dev/null || true)
fi
