#!/usr/bin/env bash
# =============================================================================
# nos-os-settle.sh — post-macOS-update settle (SUDO-FREE).
#
# Run by nos-os-resume.sh after the host has rebooted into a new macOS. It does
# the things that ARE safe + automatable without sudo/GUI, and REPORTS (does not
# attempt) anything that needs a human (CLT reinstall after a major bump). This
# is the codified replacement for the manual "after a macOS update" checklist.
#
# Sudo-free by design: a launchd login agent cannot answer the playbook's sudo
# vars_prompt. So settle ensures Docker Desktop is up + verifies host health, and
# for the rare sudo/GUI repair it emits a clear ATTENTION line. A full
# `ansible-playbook main.yml` re-converge stays an explicit operator action.
#
# Exit: 0 = clean (Docker up, no attention items). 1 = attention item(s) remain.
# Prints a human-readable report to stdout (the resume captures it to a log).
# =============================================================================
set -uo pipefail   # NOT -e: run EVERY check + report, don't abort on the first

REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
issues=0
note() { echo "$1"; }
section() { echo ""; echo "── $1"; }

section "Docker Desktop"
if command -v docker >/dev/null 2>&1; then
  if ! docker info >/dev/null 2>&1; then
    note "WARN: Docker daemon down — launching Docker Desktop..."
    open -a Docker 2>/dev/null || note "ATTENTION: 'open -a Docker' failed (is Docker Desktop installed?)"
    for _ in $(seq 1 24); do            # up to ~120s for the VM to come up
      docker info >/dev/null 2>&1 && break
      sleep 5
    done
  fi
  if docker info >/dev/null 2>&1; then
    note "OK: Docker daemon up."
    # Name the unhealthy containers (not just a count) so the post-update report
    # is actionable — a macOS/Docker update can break a service via a changed
    # filesystem-driver behaviour (e.g. gitlab puma realpath ENOTSUP on VirtioFS).
    unhealthy="$(docker ps --filter health=unhealthy --format '{{.Names}}' 2>/dev/null | paste -sd, -)"
    if [ -n "$unhealthy" ]; then
      note "WARN: unhealthy container(s): ${unhealthy} — inspect: docker logs <name> (or tools/nos-stacks.sh)"
    fi
  else
    note "ATTENTION: Docker daemon still down after wait — stacks will not run until Docker Desktop is up."
    issues=$((issues + 1))
  fi
else
  note "ATTENTION: docker CLI not found on PATH."
  issues=$((issues + 1))
fi

section "Python interpreter"
want="$(tr -d ' \n' < "$REPO/.python-version" 2>/dev/null || echo '')"
# Resolve the interpreter nOS ACTUALLY uses — the pyenv shim, evaluated with the
# repo as CWD so it reads .python-version. A bare `python3` under the login
# agent's minimal PATH (no ~/.pyenv/shims) resolves to Homebrew's python and
# falsely WARNs: the live 26.3.1 -> 26.5.1 test hit exactly this (Homebrew was
# 3.14.6 while the pinned pyenv shim was correctly 3.13.13).
py="${HOME}/.pyenv/shims/python3"
[ -x "$py" ] || py="python3"
pyver="$(cd "$REPO" && "$py" --version 2>&1 | awk '{print $2}')"
if [ -n "$want" ] && [ "$pyver" != "$want" ]; then
  note "WARN: nOS python3 is '$pyver', pinned '$want' — run 'pyenv rehash' / check PATH before a playbook run."
else
  note "OK: python3 ${pyver:-unknown} (pyenv shim)."
fi

section "Command Line Tools"
if xcode-select -p >/dev/null 2>&1 && command -v g++ >/dev/null 2>&1 && g++ --version >/dev/null 2>&1; then
  note "OK: CLT present (g++ works)."
else
  note "ATTENTION: Command Line Tools broken (common after a MAJOR macOS bump)."
  note "          Fix (needs human/GUI): xcode-select --install, then re-run the playbook."
  issues=$((issues + 1))
fi

section "nOS host daemons"
loaded="$(launchctl list 2>/dev/null | grep -c 'eu\.thisisait' || true)"
note "OK: ${loaded:-0} eu.thisisait launchd agent(s) loaded (a missing one is re-bootstrapped by the next playbook run)."

section "Summary"
if [ "$issues" -eq 0 ]; then
  note "SETTLE OK — Docker up, no attention items. A 'ansible-playbook main.yml' re-converge is OPTIONAL."
  exit 0
fi
note "SETTLE INCOMPLETE — ${issues} attention item(s) above need a human and/or a playbook run."
exit 1
