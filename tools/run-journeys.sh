#!/usr/bin/env bash
# tools/run-journeys.sh — run the e2e journeys against the LIVE estate.
#
# WHY THIS EXISTS. The journeys under `tests/e2e/journeys/` run NOWHERE.
# `.github/workflows/ci.yml` passes `--ignore=tests/e2e` (correctly — a GitHub
# runner has no Wing, no Authentik and no estate), no playbook tag invokes them,
# no Pulse job schedules them, and no tool wrapped them until this one. They
# execute only when a person happens to type the right half-dozen environment
# variables, and `tests/e2e/lib/` reads eight of them across four modules.
#
# MEASURED 2026-08-11, and this is what the gap costs. `ApprovalsPresenter` was
# retired on 2026-08-08; every anatomy gate was updated the same day;
# `test_approval_flow.py` kept walking `/approvals` and nothing said so for
# three days. When it was finally run it reported a 301 that the CSRF helper
# attributed to the POST — the redirect actually came from the GET one step
# earlier — so even the diagnosis pointed at the wrong hop. Separately,
# `test_operator_login.py` had been SKIPPING on every run anyone ever did,
# because `authentik_login` falls back to the `dev.local` tenant and this estate
# is `pazny.eu`. A skip and a rot, both reading as quiet.
#
# WHAT THIS REFUSES TO DO. Report success when a journey skipped for missing
# CONFIGURATION. A journey that skips because Wing is genuinely down is news; a
# journey that skips because nobody exported NOS_HOST is a test that has been
# switched off by accident, and counting it as "0 failed" is how it stays off.
# `--strict` (the default) exits non-zero on any skip whose reason names a
# variable this script is supposed to have provided.
#
# USAGE
#   tools/run-journeys.sh                 # every journey, strict
#   tools/run-journeys.sh -k approval     # a subset (pytest -k passthrough)
#   tools/run-journeys.sh --lenient       # skips do not fail the run
#   tools/run-journeys.sh --show-env      # print what resolved, run nothing
#
# The estate answers for itself: every value below is read from
# `~/.nos/secrets.yml` and the resolved config layers, never hard-coded here. A
# second copy of the tenant domain in this file is a third place for it to be
# wrong.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

STRICT=1
SHOW_ENV=0
PYTEST_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --lenient)  STRICT=0 ;;
    --show-env) SHOW_ENV=1 ;;
    *)          PYTEST_ARGS+=("$arg") ;;
  esac
done

# ── resolve the estate's own answers ────────────────────────────────────────
# `config.yml` last, because it wins (CLAUDE.md: the LAST layer wins). Reading
# `default.config.yml` alone is the defect `tools/estate-status.py` was written
# to end, and it would silently point these journeys at `dev.local`.
eval "$(python3 - <<'PY'
import pathlib, re, shlex, sys

repo = pathlib.Path.cwd()
home = pathlib.Path.home()


def from_config(key: str, default: str = "") -> str:
    value = default
    for layer in ("default.config.yml", "config.yml"):
        path = repo / layer
        if not path.exists():
            continue
        m = re.search(rf"^{re.escape(key)}:\s*(\S+)", path.read_text(encoding="utf-8"), re.M)
        if m:
            value = m.group(1).strip().strip("\"'")
    return value


secrets = {}
sp = home / ".nos/secrets.yml"
if sp.exists():
    try:
        import yaml
        secrets = yaml.safe_load(sp.read_text(encoding="utf-8")) or {}
    except Exception as exc:                                    # noqa: BLE001
        print(f"echo '[journeys] could not read {sp}: {exc}' >&2")

tenant = from_config("tenant_domain", "dev.local")

exported = {
    # The tenant, which is what `authentik_login` falls back to `dev.local`
    # without — the reason test_operator_login had never once run here.
    "NOS_HOST": tenant,
    "TENANT_DOMAIN": tenant,
    "WING_API_URL": "http://127.0.0.1:9000",
    "WING_DB": str(home / "wing/app/data/wing.db"),
    "WING_DATA_DIR": str(home / "wing/app/data"),
    "WING_API_TOKEN": secrets.get("wing_api_token"),
    "WING_EDGE_TOKEN": secrets.get("wing_edge_token"),
    "WING_EVENTS_HMAC_SECRET": secrets.get("wing_events_hmac_secret"),
    "BONE_SECRET": secrets.get("bone_secret") or secrets.get("bone_hmac_secret"),
    "AUTHENTIK_API_TOKEN": secrets.get("authentik_bootstrap_token"),
}

missing = [k for k, v in exported.items() if not v]
for key, value in exported.items():
    if value:
        print(f"export {key}={shlex.quote(str(value))}")
print(f"export _JOURNEY_MISSING={shlex.quote(' '.join(missing))}")
PY
)"

if [ "$SHOW_ENV" = "1" ]; then
  echo "[journeys] resolved for tenant '${NOS_HOST:-?}':"
  for k in NOS_HOST WING_API_URL WING_DB WING_API_TOKEN WING_EDGE_TOKEN \
           WING_EVENTS_HMAC_SECRET BONE_SECRET AUTHENTIK_API_TOKEN; do
    v="${!k:-}"
    case "$k" in
      *TOKEN|*SECRET) [ -n "$v" ] && v="<set, ${#v} chars>" || v="<MISSING>" ;;
      *)              [ -n "$v" ] || v="<MISSING>" ;;
    esac
    printf '  %-26s %s\n' "$k" "$v"
  done
  exit 0
fi

if [ -n "${_JOURNEY_MISSING:-}" ]; then
  echo "[journeys] NOT RESOLVED from the estate: ${_JOURNEY_MISSING}" >&2
  echo "[journeys] the journeys needing them will skip, and a skip is not a pass." >&2
fi

echo "[journeys] tenant=${NOS_HOST}  wing=${WING_API_URL}"

set +e
# `${PYTEST_ARGS[@]+"${PYTEST_ARGS[@]}"}` and not `"${PYTEST_ARGS[@]}"`: on
# macOS's bash 3.2, an EMPTY array under `set -u` is an unbound variable, so
# running with no arguments — the normal case — aborted before pytest started.
# The estate has this exact scar already (`pulse-run-agent.sh` scope_args, and
# the sibling `${#arr[@]}` Jinja trap in backup.sh); it is written down and it
# still caught this file on its first run.
out="$(python3 -m pytest tests/e2e/ -q -rs ${PYTEST_ARGS[@]+"${PYTEST_ARGS[@]}"} 2>&1)"
rc=$?
set -e
printf '%s\n' "$out"

# A skip that names one of OUR variables is a switched-off test, not an absent
# dependency. Wing being down is the estate's news; NOS_HOST being unset is
# ours, and this script exists precisely so that can never be the reason again.
if [ "$STRICT" = "1" ]; then
  offenders="$(printf '%s\n' "$out" | grep -i '^SKIPPED' \
    | grep -Ei 'NOS_HOST|TENANT_DOMAIN|WING_API_TOKEN|WING_EDGE_TOKEN|HMAC|BONE_SECRET|AUTHENTIK_API_TOKEN|not set|dev\.local' || true)"
  if [ -n "$offenders" ]; then
    echo >&2
    echo "[journeys] REFUSING to call this a pass — journey(s) skipped for" >&2
    echo "[journeys] configuration this script is supposed to provide:" >&2
    printf '%s\n' "$offenders" | sed 's/^/  /' >&2
    exit 1
  fi
fi

exit "$rc"
