#!/bin/bash
# SessionStart hook — Claude Code on the web only. Thin on purpose: the logic
# lives in tools/cloud/bootstrap.sh so a human (or a resumed session) runs the
# exact same thing by hand. Synchronous: the first test run must not race the
# venv. docs/cloud-e2e.md.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"
tools/cloud/bootstrap.sh

# Every later Bash call in the session sources this — the frozen toolchain on
# PATH, the distro module interpreter, the pytest environment contract.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo ". \"$PWD/tools/cloud/env.sh\"" >> "$CLAUDE_ENV_FILE"
fi
