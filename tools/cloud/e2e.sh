#!/usr/bin/env bash
# tools/cloud/e2e.sh — nOS end to end, inside a disposable Linux sandbox.
#
# Tiers, cheapest first; each prints a verdict line and keeps its full log under
# ~/.nos/e2e/<tier>.log (an LLM reads the verdict, a human opens the log):
#
#   static       syntax-check + the pytest suite (the CI `pytest` job's scope;
#                tests/wet is excluded — it asserts the OPERATOR's blank estate,
#                pilot trio included, and CI only ever skips it for lack of one)
#   preflight    docker answers + every image the profile needs is PULLABLE
#   converge     ansible-playbook main.yml -e @profiles/cloud-e2e.yml
#                (the playbook ends in its own STRICT smoke — tasks/post-smoke.yml)
#   smoke        re-run tools/nos-smoke.py --strict against what converged
#   idempotence  a second converge must report changed=0
#   all          static → preflight → converge → smoke → idempotence
#   reset        docker rm every container + drop the rendered stacks (sandbox only)
#
#   tools/cloud/e2e.sh static
#   tools/cloud/e2e.sh converge -e install_gitea=true     # extra args → ansible
#   NOS_E2E_PROFILE=profiles/dev-minimal.yml tools/cloud/e2e.sh converge
#
# Refuses every removal token (remove=/confirm=/blank=/flush=/uninstall=) — a
# teardown is `reset`, which only runs where CLAUDE_CODE_REMOTE=true or
# NOS_E2E_SANDBOX=1 says the machine is disposable. docs/cloud-e2e.md.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"
# shellcheck disable=SC1091
. tools/cloud/env.sh

PROFILE="${NOS_E2E_PROFILE:-profiles/cloud-e2e.yml}"
LOGS="${HOME}/.nos/e2e"
mkdir -p "$LOGS"
TIER="${1:-}"; shift || true
# macOS ships bash 3.2, where "${EXTRA[@]}" on an EMPTY array under `set -u`
# is an unbound-variable ERROR — and EXTRA is empty for `e2e.sh reset`, the
# very call the disposability guard exists for. Expand through the
# `${a[@]+…}` idiom everywhere below, never bare.
EXTRA=("$@")

say()  { printf '[e2e] %s\n' "$*"; }
pass() { printf '[e2e] PASS %-11s %s\n' "$1" "${2:-}"; }
fail() { printf '[e2e] FAIL %-11s %s\n' "$1" "${2:-}"; }

for a in ${EXTRA[@]+"${EXTRA[@]}"}; do
  case "$a" in
    *remove=*|*confirm=true*|*blank=*|*flush=*|*uninstall=*)
      fail guard "removal token '$a' refused — use \`$0 reset\` in a sandbox"; exit 2 ;;
  esac
done

# The sandbox's egress intercepts TLS; its CA (SSL_CERT_FILE) is what an image
# build must trust to reach npm/PyPI. Passed as nos_build_ca_bundle — a
# BuildKit secret, never a layer. Empty on a host with plain egress.
BUILD_CA="${NOS_BUILD_CA_BUNDLE:-${SSL_CERT_FILE:-}}"
[ -n "$BUILD_CA" ] && [ ! -s "$BUILD_CA" ] && BUILD_CA=""

# ansible-playbook from the frozen venv, BY PATH, with the venv OFF $PATH: the
# playbook's own tasks shell out to `pip3` / `python3`, and those must reach the
# host's tools, never the controller venv (the incident: bootstrap.sh, step 2).
playbook() {
  local log="$1"; shift
  env PATH="$(printf '%s' "$PATH" | tr ':' '\n' | grep -v '/.ci-venv/bin' | paste -sd:)" \
    ANSIBLE_FORCE_COLOR=0 \
    "$REPO/.ci-venv/bin/ansible-playbook" main.yml \
      -e nos_sudo_password='' \
      -e allow_weak_prefix=true \
      -e ansible_python_interpreter="$NOS_MODULE_PYTHON" \
      -e @"$PROFILE" \
      ${BUILD_CA:+-e nos_build_ca_bundle="$BUILD_CA"} \
      "$@" ${EXTRA[@]+"${EXTRA[@]}"} </dev/null >"$log" 2>&1
}

recap() { grep -A2 '^PLAY RECAP' "$1" | grep -E 'ok=' | head -1 | sed 's/^ *//'; }

first_failure() {
  # The task name + message of the first fatal, compact enough for a verdict.
  awk '/^TASK \[/{t=$0} /^fatal:|^failed:/{print t; f=1} f&&/msg:/{print; exit}' "$1" \
    | sed 's/\*\+$//' | head -3
}

tier_static() {
  local log="$LOGS/static.log"
  if ! .ci-venv/bin/ansible-playbook main.yml --syntax-check </dev/null >"$log" 2>&1; then
    fail static "syntax-check — $log"; tail -5 "$log"; return 1
  fi
  .ci-venv/bin/python -m pytest tests/ \
    --ignore=tests/wing-api --ignore=tests/wing-frontend --ignore=tests/e2e \
    --ignore=tests/wet \
    -q -p no:cacheprovider -n "${NOS_E2E_JOBS:-auto}" </dev/null >>"$log" 2>&1
  local rc=$?
  local line; line="$(grep -E '^[0-9]+ (passed|failed)|[0-9]+ passed' "$log" | tail -1)"
  if [ $rc -eq 0 ]; then pass static "$line"; else
    fail static "$line — $log"; grep -E '^FAILED' "$log" | head -20; fi
  return $rc
}

tier_preflight() {
  local log="$LOGS/preflight.log"
  if ! docker info >/dev/null 2>&1; then
    fail preflight "docker does not answer — run tools/cloud/bootstrap.sh"; return 1
  fi
  .ci-venv/bin/python tools/cloud/registry-reach.py --profile "$PROFILE" ${EXTRA[@]+"${EXTRA[@]}"} \
    >"$log" 2>&1
  local rc=$?
  if [ $rc -eq 0 ]; then pass preflight "$(tail -1 "$log")"; else
    fail preflight "— $log"; grep -E 'BLOCKED|MISSING' "$log" | head -20; fi
  return $rc
}

tier_converge() {
  local log="$LOGS/converge.log"
  say "converge ($PROFILE) — log: $log"
  playbook "$log" -e nos_smoke_strict=true
  local rc=$?
  if [ $rc -eq 0 ]; then pass converge "$(recap "$log")"; else
    fail converge "rc=$rc $(recap "$log")"; first_failure "$log"; fi
  return $rc
}

tier_smoke() {
  local log="$LOGS/smoke.log"
  .ci-venv/bin/python tools/nos-smoke.py --strict --failed-only --no-jsonl \
    </dev/null >"$log" 2>&1
  local rc=$?
  if [ $rc -eq 0 ]; then pass smoke "$(tail -1 "$log")"; else
    fail smoke "rc=$rc — $log"; tail -15 "$log"; fi
  return $rc
}

tier_idempotence() {
  local log="$LOGS/idempotence.log"
  playbook "$log"
  local rc=$? r; r="$(recap "$log")"
  if [ $rc -ne 0 ]; then fail idempotence "rc=$rc $r"; first_failure "$log"; return 1; fi
  if printf '%s' "$r" | grep -q 'changed=0 '; then pass idempotence "$r"; return 0; fi
  fail idempotence "$r"
  # Which tasks changed — the whole point of the tier.
  grep -B1 '^changed:' "$log" | grep '^TASK' | sed 's/\*\+$//' | sort | uniq -c | sort -rn | head -20
  return 1
}

tier_reset() {
  if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ] && [ "${NOS_E2E_SANDBOX:-}" != "1" ]; then
    fail reset "refused: not a disposable sandbox (set NOS_E2E_SANDBOX=1 to declare one)"
    return 2
  fi
  say "reset: removing every container, volume and rendered stack on this sandbox"
  docker ps -aq | xargs -r docker rm -f >/dev/null 2>&1
  docker volume ls -q | xargs -r docker volume rm >/dev/null 2>&1
  docker network prune -f >/dev/null 2>&1
  [ -x "$HOME/.local/bin/nos-proc" ] && for u in "$HOME"/.config/systemd/user/*.service; do
    [ -e "$u" ] && "$HOME/.local/bin/nos-proc" stop "$(basename "$u")"
  done
  # The data a converge created, so the next one meets a FRESH machine: bind-
  # mounted service data (~/nos), rendered stacks, the persisted secret store
  # and the prefix state. Leaving the store while wiping the data is the
  # half-reset that produced "password authentication failed for user
  # authentik" here (measured). ≈ `nos --remove=data`, without the prompts.
  rm -rf "$HOME/stacks" "$HOME/nos" "$HOME/projects" \
         "$HOME/.nos/state.yml" "$HOME/.nos/secrets.yml" "$HOME/.nos/proc" \
         "$REPO/.ansible-prefix-state"
  # ~/projects holds nextcloud_dir / wordpress_dir and the service registry —
  # a stale nextcloud/config there made the "fresh" converge meet an estate
  # that believed it was installed (measured 2026-09-26).
  # Host organs' runtime trees (venvs, wing.db, cortex store). Tools the
  # converge installs (~/.nvm, ~/.local/bin/{frankenphp,composer.phar}) stay:
  # re-downloading them proves nothing about nOS.
  rm -rf "$HOME/bone" "$HOME/pulse" "$HOME/wing" "$HOME/cortex"
  pass reset "images kept (re-pull is the slow part)"
}

case "$TIER" in
  static)      tier_static ;;
  preflight)   tier_preflight ;;
  converge)    tier_converge ;;
  smoke)       tier_smoke ;;
  idempotence) tier_idempotence ;;
  reset)       tier_reset ;;
  all)
    tier_static && tier_preflight && tier_converge && tier_smoke && tier_idempotence ;;
  *)
    sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
