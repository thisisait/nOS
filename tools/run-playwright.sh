#!/usr/bin/env bash
# tools/run-playwright.sh — the Playwright e2e suite (tests/e2e) on a host without node.
#
# The DGX (Linux) has no node, npx or browsers, so the suite runs in the official Playwright image
# matching the installed @playwright/test, on the host network with the host's /etc/hosts (the
# tenant's names). The tester is provisioned and torn down HERE, on the host, where the helper's
# Python and ~/.nos/secrets.yml live; the container gets only its login (NOS_SKIP_PROVISION=1)
# through a 0600 env file, never argv. --iris: the tester is named in the thalamus identity map
# for the run (tests/e2e/lib/iris_map.py), so the face/Iris journeys (FACE_E2E=1) reach Iris.
#
#   tools/run-playwright.sh [playwright args]            # e.g. journeys/iris-face.spec.ts
#   NOS_TESTER_TIER=user FACE_E2E=1 tools/run-playwright.sh journeys/
#
# One-time: (cd tests/e2e && npm install) — or in a node container on a host without node.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
E2E="$REPO/tests/e2e"
PY="${NOS_PYTHON:-python3}"
OUT="$E2E/.playwright-out"
mkdir -p "$OUT"

PW_VERSION="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' \
  "$E2E/node_modules/@playwright/test/package.json" 2>/dev/null)" || {
  echo "[playwright] tests/e2e/node_modules missing: run npm install there first" >&2; exit 2; }
IMAGE="${PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright:v${PW_VERSION}-noble}"

NOS_HOST="${NOS_HOST:-$(cd "$REPO" && "$PY" - <<'PY'
import sys; sys.path.insert(0, "tools")
import nos_identity as ni
print((ni.resolve_flag("tenant_domain") or [("", "dev.local")])[-1][1])
PY
)}"

TESTER="$OUT/host-tester.json"
ENVF="$OUT/tester.env"
cleanup() {
  if [ -f "$TESTER" ]; then
    (cd "$REPO" && "$PY" tools/e2e-auth-helper.py teardown --input "$TESTER") || true
    rm -f "$TESTER"
  fi
  rm -f "$ENVF" "$OUT/face-state.json"  # the signed-in cookie outlives nothing
}
trap cleanup EXIT

(cd "$REPO" && "$PY" tools/e2e-auth-helper.py provision --tier "${NOS_TESTER_TIER:-provider}" --iris --output "$TESTER")
umask 077
"$PY" - "$TESTER" > "$ENVF" <<'PY'
import json, sys
t = json.load(open(sys.argv[1]))
print(f"NOS_TESTER_USER={t['username']}")
print(f"NOS_TESTER_PASSWORD={t['password']}")
PY

echo "[playwright] tenant=$NOS_HOST image=$IMAGE tier=${NOS_TESTER_TIER:-provider} face=${FACE_E2E:-0}"
docker run --rm --network host --ipc host \
  -v /etc/hosts:/etc/hosts:ro \
  -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$E2E:/w" -w /w \
  --env-file "$ENVF" \
  -e NOS_SKIP_PROVISION=1 -e NOS_HOST="$NOS_HOST" -e FACE_E2E="${FACE_E2E:-0}" \
  ${FACE_URL:+-e FACE_URL="$FACE_URL"} ${APPS_SUBDOMAIN:+-e APPS_SUBDOMAIN="$APPS_SUBDOMAIN"} \
  "$IMAGE" npx --no-install playwright test "$@"
