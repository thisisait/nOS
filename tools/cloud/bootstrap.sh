#!/usr/bin/env bash
# tools/cloud/bootstrap.sh — make a fresh Linux sandbox able to test nOS end to end.
#
# Built for Claude Code on the web (an Ubuntu 24.04 container, root, PID 1 is
# `process_api` — no systemd — and an egress proxy that refuses Galaxy, ghcr blob
# storage, quay.io and lscr.io). Runs from the SessionStart hook
# (.claude/hooks/session-start.sh) and by hand. Idempotent; every step checks
# before it acts, so a resumed session pays seconds, not minutes.
#
#   tools/cloud/bootstrap.sh            # everything
#   tools/cloud/bootstrap.sh --no-docker  # toolchain only (static tiers)
#
# What it provides, and nothing more:
#   1. apt: sqlite3 + the module interpreter's deps (python3-yaml/jsonschema/jinja2)
#   2. the frozen controller venv (.ci-venv, tools/ci-local.sh) + the lock's
#      collections (galaxy, or git when galaxy is refused) + the pytest deps
#   3. the Wing vendor tree (composer), which ~150 anatomy gates execute
#   4. dockerd, when nothing answers on the socket and there is no init to ask
#
# It never touches config.yml / credentials.yml and never converges — that is
# tools/cloud/e2e.sh, which the operator (or the agent) runs deliberately.
# docs/cloud-e2e.md is the runbook.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"
WANT_DOCKER=1
[ "${1:-}" = "--no-docker" ] && WANT_DOCKER=0

LOG_DIR="${HOME}/.nos/cloud"
mkdir -p "$LOG_DIR"
say() { printf '[cloud-bootstrap] %s\n' "$*"; }

[ "$(uname -s)" = "Linux" ] || { say "not Linux — nothing to do (macOS uses tools/ci-local.sh)"; exit 0; }

# ── 0. apt sources the egress refuses (sandbox only) ────────────────────────
# The cloud image ships PPAs (deadsnakes, ondrej/php) on launchpadcontent.net,
# which the proxy answers 403. `apt-get update` shrugs that off as a warning;
# Ansible's apt `update_cache` does not — it fails the run ("Failed to update
# apt cache after 5 retries"), but only once the 1 h cache_valid_time lapses,
# so it bites the SECOND converge of a session (measured 2026-09-25). A source
# the sandbox cannot reach is renamed to *.nos-cloud-disabled — reversible,
# and only where the machine is declared disposable.
if { [ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || [ "${NOS_E2E_SANDBOX:-}" = "1" ]; } \
   && [ "$(id -u)" = 0 ] && [ -d /etc/apt/sources.list.d ]; then
  for src in /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
    [ -f "$src" ] || continue
    for url in $(grep -hoE 'https?://[^ ]+' "$src" | sort -u); do
      code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$url" || true)"
      if [ "$code" = "000" ] || [ "$code" = "403" ]; then
        mv "$src" "${src}.nos-cloud-disabled"
        say "apt source unreachable ($url → ${code}) — disabled ${src##*/}"
        break
      fi
    done
  done
fi

# ── 1. apt ──────────────────────────────────────────────────────────────────
APT_PKGS=(sqlite3 python3-yaml python3-jsonschema python3-jinja2 python3-apt jq curl git)
missing=()
for p in "${APT_PKGS[@]}"; do
  dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
done
if [ "${#missing[@]}" -gt 0 ]; then
  SUDO=""; [ "$(id -u)" = 0 ] || SUDO="sudo -n"
  say "apt install ${missing[*]}"
  $SUDO apt-get update -q >"$LOG_DIR/apt.log" 2>&1 || true
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -q "${missing[@]}" >>"$LOG_DIR/apt.log" 2>&1 \
    || { say "apt install failed — see $LOG_DIR/apt.log"; exit 1; }
fi

# ── 2. frozen venv + collections ────────────────────────────────────────────
# A venv whose ansible-core no longer equals the pin is not frozen any more —
# rebuild it. (Measured 2026-09-25: the playbook's own "Install global Pip
# packages" task ran the venv's pip3 because the venv was first on PATH, and
# its `ansible` entry dragged ansible-core 2.21.0 → 2.21.4 mid-run. e2e.sh now
# converges with the venv OFF PATH; this check is the backstop.)
if [ -x .ci-venv/bin/python ]; then
  # shellcheck disable=SC1091
  want="$(. tools/ci-freeze.env; echo "${NOS_ANSIBLE_CORE#ansible-core==}")"
  have="$(.ci-venv/bin/python -c 'import importlib.metadata as m; print(m.version("ansible-core"))' 2>/dev/null || echo none)"
  if [ "$want" != "$have" ]; then
    say "frozen venv drifted (ansible-core $have, pin $want) — rebuilding"
    rm -rf .ci-venv
  fi
fi
# ci-local.sh builds .ci-venv from tools/ci-freeze.env and installs the lock
# (git fallback when galaxy is refused); `true` makes it stop there.
tools/ci-local.sh true >"$LOG_DIR/ci-local.log" 2>&1 \
  || { say "frozen venv failed — see $LOG_DIR/ci-local.log"; tail -5 "$LOG_DIR/ci-local.log"; exit 1; }
# Same list as the CI pytest job (.github/workflows/ci.yml) + xdist.
PYTEST_DEPS=(pytest pytest-xdist pyyaml jsonschema httpx jinja2 requests markdown==3.10.2 fastapi textual)
if ! .ci-venv/bin/python -c 'import pytest, xdist, httpx, fastapi, textual, markdown' >/dev/null 2>&1; then
  say "pip install pytest deps into .ci-venv"
  .ci-venv/bin/pip install -q "${PYTEST_DEPS[@]}" >"$LOG_DIR/pip.log" 2>&1 \
    || { say "pip failed — see $LOG_DIR/pip.log"; exit 1; }
fi
say "toolchain: $(.ci-venv/bin/ansible --version </dev/null 2>/dev/null | head -1)"

# ── 3. wing vendor tree ─────────────────────────────────────────────────────
if command -v composer >/dev/null 2>&1 && [ ! -f files/anatomy/wing/vendor/autoload.php ]; then
  say "composer install (wing vendor)"
  composer install --no-progress --no-interaction --no-scripts -d files/anatomy/wing \
    >"$LOG_DIR/composer.log" 2>&1 || say "composer install failed — see $LOG_DIR/composer.log"
fi

# ── 4. docker ───────────────────────────────────────────────────────────────
docker_up() { docker info >/dev/null 2>&1; }
# Docker Hub's anonymous budget is per egress IP, and a cloud sandbox SHARES its
# egress IP — measured 24/100 left on 2026-09-25 before this session pulled
# anything. mirror.gcr.io is Google's public pull-through cache of Docker Hub;
# a miss falls through to Hub. Written only when no daemon.json exists — an
# operator's own daemon config is never edited.
if [ "$WANT_DOCKER" = 1 ] && [ ! -e /etc/docker/daemon.json ] && [ "$(id -u)" = 0 ]; then
  mkdir -p /etc/docker
  printf '{\n  "registry-mirrors": ["https://mirror.gcr.io"]\n}\n' > /etc/docker/daemon.json
  say "docker: registry mirror mirror.gcr.io (Docker Hub rate limit is per shared IP)"
  if docker_up && [ "$(ps -p 1 -o comm= 2>/dev/null)" != "systemd" ]; then
    say "restarting dockerd to pick up the mirror"
    pkill -x dockerd || true
    for _ in $(seq 1 30); do pgrep -x dockerd >/dev/null || break; sleep 1; done
  fi
fi
if [ "$WANT_DOCKER" = 1 ] && command -v dockerd >/dev/null 2>&1 && ! docker_up; then
  if [ "$(ps -p 1 -o comm= 2>/dev/null)" = "systemd" ]; then
    say "systemd is PID 1 — starting docker.service"
    systemctl start docker || true
  else
    # No init system: nothing else will own dockerd, so it runs detached with
    # its log under ~/.nos/cloud. It inherits HTTPS_PROXY, which is how image
    # pulls reach Docker Hub through the sandbox's egress proxy.
    say "no init system — starting dockerd (log: $LOG_DIR/dockerd.log)"
    nohup dockerd >"$LOG_DIR/dockerd.log" 2>&1 </dev/null &
    disown || true
  fi
  for _ in $(seq 1 30); do docker_up && break; sleep 1; done
fi
if [ "$WANT_DOCKER" = 1 ]; then
  if docker_up; then
    say "docker: $(docker info --format '{{.ServerVersion}} ({{.Driver}})' 2>/dev/null)"
  else
    say "docker: NOT answering — converge tiers will refuse (see $LOG_DIR/dockerd.log)"
  fi
fi

say "ready — next: tools/cloud/e2e.sh static   (docs/cloud-e2e.md)"
