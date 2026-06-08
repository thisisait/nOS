#!/usr/bin/env bash
# tools/ci-local.sh — run a command inside a FROZEN venv that reproduces the CI
# integration job 1:1 (ansible-core 2.21+, lockfile-pinned collections/roles,
# Python 3.13.13). This is the LOCAL PRE-RELEASE GATE.
#
# Why it exists: the v0.5-beta release took 21 CI push/watch cycles because the
# operator's daily ansible-core 2.20.5 never reproduced the runner's 2.21
# filter-load path locally (VaultDecryptionContext is a 2.21 symbol; a 2.20.x
# controller silently skips ansible.builtin.core filters). Run this before a
# release push and that whole class of divergence surfaces on the dev box.
#
# NOTE on "1:1 on the SAME macOS": GitHub's hosted macOS runner is NOT this Mac
# (its framework-Python custom-module quirk forced the macOS Integration job to
# continue-on-error). This script freezes the TOOLCHAIN (ansible-core +
# collections + Python) identically; a truly identical ENVIRONMENT would need a
# self-hosted runner. The toolchain freeze is what catches the 2.21-class breaks.
#
# Usage:
#   tools/ci-local.sh                    # filter-load probe + syntax-check (fast gate)
#   tools/ci-local.sh ansible-playbook main.yml    # full wet-test in the frozen env
#   tools/ci-local.sh --rebuild [cmd...] # recreate the venv from scratch first
#   tools/ci-local.sh --refresh-lock     # re-resolve ranges → print versions for the lock
#
# The frozen venv lives in .ci-venv/ (gitignored). Collections/roles install into
# .ci-venv/ansible-home (ANSIBLE_HOME) so the operator's daily ~/.ansible (2.20.x
# era) is never touched.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── Frozen toolchain (overridable via tools/ci-freeze.env) ───────────────────
NOS_PYTHON_VERSION="3.13.13"
NOS_ANSIBLE_CORE="ansible-core>=2.21,<2.24"
# shellcheck disable=SC1091
[ -f "${REPO_ROOT}/tools/ci-freeze.env" ] && . "${REPO_ROOT}/tools/ci-freeze.env"

VENV="${REPO_ROOT}/.ci-venv"
export ANSIBLE_HOME="${VENV}/ansible-home"

REBUILD=0
REFRESH_LOCK=0
case "${1:-}" in
  --rebuild)      REBUILD=1; shift ;;
  --refresh-lock) REFRESH_LOCK=1; shift ;;
esac

pick_python() {
  # Prefer the exact frozen Python via pyenv, else python3.13, else python3.
  if command -v pyenv >/dev/null 2>&1 \
     && pyenv versions --bare 2>/dev/null | grep -qx "$NOS_PYTHON_VERSION"; then
    echo "$(pyenv root)/versions/${NOS_PYTHON_VERSION}/bin/python3"
  elif command -v "python${NOS_PYTHON_VERSION%.*}" >/dev/null 2>&1; then
    command -v "python${NOS_PYTHON_VERSION%.*}"
  else
    command -v python3
  fi
}

if [ "$REBUILD" = 1 ] && [ -d "$VENV" ]; then
  echo "[ci-local] removing existing $VENV"
  rm -rf "$VENV"
fi

if [ ! -x "${VENV}/bin/python" ]; then
  PY="$(pick_python)"
  echo "[ci-local] creating frozen venv at .ci-venv/ using $PY ($("$PY" --version 2>&1))"
  "$PY" -m venv "$VENV"
  "${VENV}/bin/pip" install --quiet --upgrade pip
  echo "[ci-local] pip install ${NOS_ANSIBLE_CORE} + pyyaml jsonschema (controller)"
  "${VENV}/bin/pip" install --quiet "$NOS_ANSIBLE_CORE" pyyaml jsonschema
fi

export PATH="${VENV}/bin:${PATH}"
# Module interpreter = the venv python (has ansible-core + pyyaml + jsonschema).
# Locally this is cleaner than CI's split-interpreter dance — the venv-resolution
# bug that forced CI onto a non-venv $PY is a GitHub framework-Python quirk only.
export ANSIBLE_PYTHON_INTERPRETER="${VENV}/bin/python"

# Galaxy deps from the FROZEN lock (falls back to requirements.yml if absent).
GALAXY_SRC="${REPO_ROOT}/requirements.lock.yml"
[ -f "$GALAXY_SRC" ] || GALAXY_SRC="${REPO_ROOT}/requirements.yml"
echo "[ci-local] ansible-galaxy install -r $(basename "$GALAXY_SRC")  (ANSIBLE_HOME=.ci-venv/ansible-home)"
for attempt in 1 2 3 4 5 6; do
  if out="$("${VENV}/bin/ansible-galaxy" install -r "$GALAXY_SRC" 2>&1)"; then
    echo "$out"; break
  fi
  echo "$out"
  # Only retry KNOWN transient signatures (Galaxy archive 502/504 etc.); fail
  # fast on hard errors (bad pin, bad file) so a config bug doesn't burn 6×backoff.
  if echo "$out" | grep -qiE '50[234]|bad gateway|gateway time-?out|timed? ?out|temporarily|connection (reset|refused|aborted)|EOF occurred|TLS'; then
    echo "[ci-local] transient galaxy error; sleeping ${attempt}0s"
    sleep "${attempt}0"
    [ "$attempt" = 6 ] && { echo "[ci-local] galaxy install failed after 6 attempts"; exit 1; }
  else
    echo "[ci-local] non-transient galaxy error — not retrying"
    exit 1
  fi
done

if [ "$REFRESH_LOCK" = 1 ]; then
  echo "[ci-local] resolved toolchain — update requirements.lock.yml + tools/ci-freeze.env to match:"
  "${VENV}/bin/ansible" --version | head -1
  "${VENV}/bin/ansible-galaxy" collection list 2>/dev/null \
    | grep -Ei 'community.general|community.docker|community.mysql|ansible.posix|geerlingguy.mac' || true
  "${VENV}/bin/ansible-galaxy" role list 2>/dev/null \
    | grep -Ei 'elliotweiser|geerlingguy.dotfiles' || true
  exit 0
fi

echo "[ci-local] === frozen toolchain ==="
"${VENV}/bin/ansible" --version | head -1
"${VENV}/bin/python" --version

if [ "$#" -gt 0 ]; then
  echo "[ci-local] running in frozen env: $*"
  exec "$@"
fi

# Default fast gate: prove core filters load (the 2.21 / VaultDecryptionContext
# class — syntax-check alone does NOT resolve templates) then syntax-check the
# playbook. Full wet-test: tools/ci-local.sh ansible-playbook main.yml
echo "[ci-local] filter-load probe (bool / to_nice_json)"
"${VENV}/bin/ansible" localhost -m ansible.builtin.debug \
  -a '{"msg": "{{ [] | to_nice_json }} {{ true | bool }}"}'
echo "[ci-local] syntax-check"
"${VENV}/bin/ansible-playbook" main.yml --syntax-check
echo "[ci-local] OK — frozen toolchain loads core filters and main.yml syntax is clean"
