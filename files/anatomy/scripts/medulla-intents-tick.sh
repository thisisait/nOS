#!/bin/bash
# medulla-intents-tick.sh — the Pulse job's door to `medulla intents tick`
# (row wing-apply-through-medulla, slice 1b-iii).
#
# Why a wrapper: the medulla's HTTP client is built without TLS, and Authentik's token endpoint is https
# (its issuer is what Bone checks). So the nos-medulla client_credentials grant happens here, with curl,
# exactly as pulse-run-agent.sh does it for agents, and the bearer is handed to the medulla in its env.
# The client secret is read from custody (macOS Keychain / /etc/nos/medulla.env), passed to curl on
# stdin, never in argv or a log. The medulla still gates on MEDULLA_EXECUTES_INTENTS and the halt.
set -u -o pipefail

# The job exists only while install_medulla_intents is on (the plugin's flag), so here it is on.
export MEDULLA_EXECUTES_INTENTS=1

bin="${NOS_MEDULLA_BIN:-}"
for cand in "$bin" "$HOME/thalamus/bin/medulla" /usr/local/libexec/nos/medulla; do
    [[ -n "$cand" && -x "$cand" ]] && { bin="$cand"; break; }
done
[[ -x "${bin:-}" ]] || { echo "intents: no medulla binary (NOS_MEDULLA_BIN, ~/thalamus/bin, /usr/local/libexec/nos)" >&2; exit 11; }

if [[ "$(uname -s)" == "Darwin" ]]; then
    secret=$(security find-generic-password -a nos -s nos.medulla.bone-client-secret -w 2>/dev/null) || secret=""
else
    secret=$(sed -n 's/^MEDULLA_BONE_CLIENT_SECRET=//p' /etc/nos/medulla.env 2>/dev/null | head -n 1) || secret=""
fi
[[ ${#secret} -ge 32 ]] || { echo "intents: no bone client secret in the medulla's custody (a converge writes it)" >&2; exit 11; }

[[ "${NOS_AUTHENTIK_URL:-}" == https://* ]] || { echo "intents: NOS_AUTHENTIK_URL is unset or not https" >&2; exit 11; }
resp=$(printf '%s' "$secret" | curl -sS -m 20 -w '\n%{http_code}' -X POST \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode 'grant_type=client_credentials' \
    --data-urlencode 'client_id=nos-medulla' \
    --data-urlencode 'client_secret@-' \
    --data-urlencode 'scope=nos:upgrades:read' \
    "${NOS_AUTHENTIK_URL%/}/application/o/token/") || { echo "intents: Authentik unreachable" >&2; exit 11; }
unset secret
code=$(printf '%s' "$resp" | tail -n 1)
[[ "$code" == "200" ]] || { echo "intents: Authentik refused the nos-medulla grant (HTTP $code)" >&2; exit 11; }
MEDULLA_BONE_TOKEN=$(printf '%s' "$resp" | sed '$d' | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))')
[[ -n "$MEDULLA_BONE_TOKEN" ]] || { echo "intents: Authentik returned no access_token" >&2; exit 11; }
export MEDULLA_BONE_TOKEN
exec "$bin" intents tick
