#!/usr/bin/env bash
# =============================================================================
# nos-notify.sh — best-effort A9 notification → Bone /api/v1/notifications.
#
# A small, dependency-light emitter so host-side scripts (the os-update resume,
# future recipes) can fan a notification into the canonical A9 path (wing-inbox
# + ntfy + mail per routing) instead of only a transient macOS popup.
#
# Usage:  nos-notify.sh <severity> <title> <body> [channels-csv] [supersede-key]
#   severity : critical | high | medium | low | info
#   channels : default "wing-inbox,ntfy"
#   supersede-key : class id, or the literal `none`. When a key is given, this
#     message retires the caller's earlier UNREAD messages of the same class
#     (2026-08-23). Per-caller on purpose: this script hardcodes origin_plugin,
#     so every host script would otherwise share one class and retire each
#     other's news.
#
#     `none` MEANS SOMETHING, AND SILENCE NO LONGER SHOULD (2026-08-27). Pass it
#     when the message is a distinct occurrence rather than the current answer to
#     a standing question — a macOS update settling is not a restatement of the
#     last one, which is why nos-os-resume.sh's own key is the exception that
#     proves the rule rather than a counter-example.
#
#     Measured that day: 206 of 212 rows in the inbox carried no key, and only
#     two classes appeared in the record at all (a third call site declared one
#     but had not fired since). The retirement machinery worked perfectly on
#     those two — 183 retired by 194, three backup rows retired leaving exactly
#     one live — and could not reach the other 97%. The inbox did not grow
#     because nobody read it; it grew because almost nothing could leave.
#
#     Omitting the argument still sends — a lost notification is worse than an
#     accumulating one, so this never fails its caller. It is
#     `tests/anatomy/test_every_notifier_declares_supersession.py` that refuses an
#     undeclared call site, at commit time, where it costs nothing.
#
# Uses a LITERAL title+body+channels (NOT template+context): a template name only
# resolves if a harvested plugin manifest registers it, and these host scripts are
# not plugins — a template would 400 in Bone and be dropped (the lesson the
# upgrade-engine reboot_required notification learned). Reads the HMAC secret from
# $WING_EVENTS_HMAC_SECRET or ~/.nos/secrets.yml. SILENT no-op (exit 0) when jq /
# openssl / curl / the secret / Bone are unavailable — it must never fail its
# caller (a login-time settle).
# =============================================================================
set -uo pipefail

sev="${1:-info}"
title="${2:-nOS}"
body="${3:-}"
channels="${4:-wing-inbox,ntfy}"
supersede="${5:-}"
# `none` is a DECLARATION that this message is a distinct occurrence, and it
# must not reach Bone as a class id — the regex there would accept it and every
# caller that passed it would then share one class and retire each other.
[ "$supersede" = "none" ] && supersede=""

# WHO IS SENDING. This script hardcoded `os-resume` for every caller until
# 2026-08-25, and it is the shared sender for at least five of them: the
# os-update settle it is named for, the cortex corpus diff, the KEAP
# consolidator, the KEAP linter and a readiness probe. Thirty-three rows in the
# live inbox wear a borrowed identity, and `bin/reconcile-inbox.php` keys a
# restatement CLASS on exactly that identity — so the first keyed os-resume
# emission would have retired thirty-five unrelated rows. Measured, simulated,
# and now refused by that tool; this is the other half, so new rows stop
# arriving mislabelled.
#
# The defaults keep the os-update caller working unchanged. Every other caller
# should set these — a Pulse job does it in its `env:` block beside
# NOS_NOTIFY_BIN.
origin="${NOS_NOTIFY_ORIGIN:-os-resume}"
actor="${NOS_NOTIFY_ACTOR:-agent:os-resume}"

for t in jq openssl curl; do
  command -v "$t" >/dev/null 2>&1 || exit 0
done

secret="${WING_EVENTS_HMAC_SECRET:-}"
if [ -z "$secret" ] && [ -f "${HOME}/.nos/secrets.yml" ]; then
  # simple `key: value` line — strip key, leading space, and optional quotes.
  secret="$(grep -E '^wing_events_hmac_secret:' "${HOME}/.nos/secrets.yml" \
            | head -1 | sed -E 's/^[^:]+:[[:space:]]*//; s/^["'"'"']//; s/["'"'"']$//')"
fi
[ -z "$secret" ] && exit 0

url="${BONE_URL:-http://127.0.0.1:${BONE_PORT:-8099}}/api/v1/notifications"

chan_json="$(printf '%s' "$channels" | jq -R 'split(",")')"
payload="$(jq -nc --arg s "$sev" --arg t "$title" --arg b "$body" --argjson ch "$chan_json" \
  --arg sk "$supersede" --arg op "$origin" --arg aid "$actor" \
  '{severity:$s, title:$t, body:$b, channels:$ch,
    origin_plugin:$op, actor_id:$aid,
    metadata:{source:$op}}
   + (if $sk == "" then {} else {supersede_key:$sk} end)')"
# -a: Bone verifies over Python json.dumps output, which escapes non-ASCII.
# A Czech title signs clean here and 401s there without it.
compact="$(printf '%s' "$payload" | jq -a --sort-keys -c .)"
ts="$(date +%s)"
sig="$(printf '%s.%s' "$ts" "$compact" | openssl dgst -sha256 -hmac "$secret" | awk '{print $NF}')"

code="$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
  -H "X-Wing-Timestamp: $ts" -H "X-Wing-Signature: $sig" \
  -H "Content-Type: application/json" \
  -d "$compact" "$url" 2>/dev/null || echo 000)"

case "$code" in
  200|201) exit 0 ;;
  *) echo "nos-notify: Bone POST returned HTTP $code (notification dropped)" >&2; exit 0 ;;
esac
