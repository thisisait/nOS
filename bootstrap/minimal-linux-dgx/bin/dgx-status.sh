#!/usr/bin/env bash
# =============================================================================
# dgx-status — what is RED on this box, right now. A reader, nothing else:
# it runs every probe itself (a tailed log looks healthy right up until its
# writer stops), reports an unreadable source as UNKNOWN never as green, and
# exits 0 whatever it finds. Works for any user; a few probes say UNKNOWN
# without root and tell you so.
#
#   dgx-status            human table
#   dgx-status --json     one JSON object per line, for an agent or a pane
# =============================================================================
set -uo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
JSON=0; [ "${1:-}" = "--json" ] && JSON=1
SHORT="$(hostname -s)"; HOST="$SHORT.local"
CA=/etc/nos/mkcert/rootCA.pem
red=0; unknown=0

row() {  # row <state> <name> <detail>
  case "$1" in RED) red=$((red+1));; UNKNOWN) unknown=$((unknown+1));; esac
  if [ "$JSON" = 1 ]; then
    python3 -c 'import json,sys; print(json.dumps({"state":sys.argv[1],"name":sys.argv[2],"detail":sys.argv[3]}))' "$1" "$2" "$3"
  else
    local c; case "$1" in GREEN) c='\033[32m';; RED) c='\033[31m';; *) c='\033[33m';; esac
    printf "${c}%-8s\033[0m %-26s %s\n" "$1" "$2" "$3"
  fi
}
unit() {  # unit <name> [expected=active]
  local s; s="$(systemctl is-active "$1" 2>/dev/null || true)"
  if [ "$s" = "${2:-active}" ]; then row GREEN "$1" "$s"; else row RED "$1" "${s:-unknown}"; fi
}
http() {  # http <name> <url> <expected-code> [curl-args…]
  local name="$1" url="$2" want="$3"; shift 3
  local code; code="$(curl -4 -s -o /dev/null -w '%{http_code}' -m 6 "$@" "$url" 2>/dev/null)"; code="${code:-000}"
  if [ "$code" = "$want" ]; then row GREEN "$name" "$code $url"; elif [ "$code" = 000 ]; then row RED "$name" "no answer $url"; else row RED "$name" "$code (wanted $want) $url"; fi
}

# ── services ────────────────────────────────────────────────────────────────
for u in nginx docker ollama jupyterhub backrest mcpo-nos-tables nos-keap-identity; do unit "$u"; done
unit nos-dgx-backup-verify.timer
for c in iiab-keap-1 iiab-open-webui-1 iiab-n8n-1; do
  st="$(docker inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}nohc{{end}}' "$c" 2>/dev/null || true)"
  case "$st" in
    running/healthy|running/nohc) row GREEN "$c" "$st";;
    "") row UNKNOWN "$c" "docker not readable by $(id -un) (docker group) or container absent";;
    *) row RED "$c" "$st";;
  esac
done
for u in $(getent group nos-users | cut -d: -f4 | tr , ' '); do
  [ "$(id -u "$u")" -ge 1000 ] || continue
  id -nG "$u" | grep -qw docker && continue          # root-daemon user, no rootless
  s="$(systemctl --user -M "$u@" is-active docker 2>/dev/null || true)"
  case "$s" in active) row GREEN "rootless-docker $u" active;; "") row UNKNOWN "rootless-docker $u" "cannot ask $u's systemd (root only)";; *) row RED "rootless-docker $u" "$s";; esac
done

# ── the edge, as a LAN client would see it ──────────────────────────────────
http "web landing"      "https://$HOST/"                 200 --cacert "$CA"
http "web kb"           "https://$HOST/kb/"              200 --cacert "$CA"
http "web keap (gate)"  "https://$HOST:8443/"            401 --cacert "$CA"
http "web chat"         "https://$HOST:8444/"            200 --cacert "$CA"
http "web notebooks"    "https://$HOST:8445/hub/login"   200 --cacert "$CA"
http "web backups(gate)" "https://$HOST:8446/"           401 --cacert "$CA"
http "web automation"   "https://$HOST:8447/"            200 --cacert "$CA"

# ── the organs behind it ────────────────────────────────────────────────────
kv="$(curl -s -m 5 http://127.0.0.1:8091/api/health 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin)["data"]; print(d["status"], d["version"])' 2>/dev/null || true)"
[ -n "$kv" ] && row GREEN "keap api" "$kv" || row RED "keap api" "no /api/health on 127.0.0.1:8091"
ov="$(curl -s -m 5 http://172.17.0.1:11434/api/version 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])' 2>/dev/null || true)"
if [ -n "$ov" ]; then
  loaded="$(curl -s -m 5 http://172.17.0.1:11434/api/ps | python3 -c 'import json,sys; m=json.load(sys.stdin)["models"]; print(", ".join(x["name"] for x in m) or "nothing loaded")' 2>/dev/null)"
  row GREEN "ollama api" "$ov · $loaded"
else row RED "ollama api" "no answer on 172.17.0.1:11434"; fi
http "mcpo nos_tables"  "http://172.17.0.1:8500/openapi.json" 200
idc="$(curl -s -o /dev/null -w '%{http_code}' -m 5 --unix-socket /run/nos-dgx/keap-identity.sock http://keap/api/tables 2>/dev/null || echo 000)"
case "$idc" in 200) row GREEN "identity outpost" "200 as $(id -un) via /run/nos-dgx/keap-identity.sock";; 403) row RED "identity outpost" "403: $(id -un) is not in nos-users";; 000) row RED "identity outpost" "no answer on /run/nos-dgx/keap-identity.sock";; *) row RED "identity outpost" "$idc";; esac
# the tables themselves, with whatever token this user holds
if [ -r /etc/nos/keap.env ]; then
  # shellcheck disable=SC1091
  . /etc/nos/keap.env
  n="$(curl -s -m 5 -H "Authorization: Bearer ${KEAP_AGENT_TOKEN_RO:-}" "${KEAP_API_URL:-http://127.0.0.1:8091}/agent/v1/tables/roadmap/rows" | python3 -c 'import json,sys; d=json.load(sys.stdin); d=d.get("data",d); print(len(d.get("rows",[])))' 2>/dev/null || true)"
  [ -n "$n" ] && row GREEN "roadmap table" "$n row(s) readable" || row RED "roadmap table" "unreadable with the RO token"
else row UNKNOWN "roadmap table" "no /etc/nos/keap.env for $(id -un) (not in nos-users)"; fi

# ── backup: mounted? verdict? ───────────────────────────────────────────────
if mountpoint -q /srv/backup; then row GREEN "backup disk" "/srv/backup mounted, $(df -h /srv/backup | awk 'NR==2{print $4}') free"; else row RED "backup disk" "/srv/backup is not a mountpoint"; fi
LJ=/var/lib/nos-dgx/backup/last.json
if [ -r "$LJ" ]; then
  v="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["verdict"], "—", d["detail"], "· verified", d["verified_at"][:16])' "$LJ" 2>/dev/null || echo "unparseable")"
  case "$v" in OK*) row GREEN "backup verdict" "$v";; UNKNOWN*|unparseable*) row UNKNOWN "backup verdict" "$v";; *) row RED "backup verdict" "$v";; esac
elif [ ! -r "$(dirname "$LJ")" ]; then row UNKNOWN "backup verdict" "$(dirname "$LJ") not readable by $(id -un)"
else row RED "backup verdict" "no verdict yet — the verifier has never run"; fi

# ── host ────────────────────────────────────────────────────────────────────
df -P / | awk 'NR==2{u=$5+0; printf "%s\n", u}' | { read -r pct; if [ "$pct" -lt 85 ]; then row GREEN "disk /" "${pct}% used"; else row RED "disk /" "${pct}% used"; fi; }
days="$(( ( $(date -d "$(openssl x509 -in /etc/nginx/tls/spark.pem -noout -enddate 2>/dev/null | cut -d= -f2)" +%s 2>/dev/null || echo 0) - $(date +%s) ) / 86400 ))"
if [ "$days" -gt 30 ]; then row GREEN "tls leaf" "$days days left"; elif [ "$days" -gt 0 ]; then row RED "tls leaf" "$days days left — re-run the recipe"; else row UNKNOWN "tls leaf" "cannot read /etc/nginx/tls/spark.pem"; fi
gpu="$(nvidia-smi --query-gpu=name,utilization.gpu --format=csv,noheader 2>/dev/null | head -1)"
[ -n "$gpu" ] && row GREEN "gpu" "$gpu" || row UNKNOWN "gpu" "nvidia-smi unavailable"
failed="$(systemctl --failed --no-legend 2>/dev/null | wc -l)"
[ "$failed" = 0 ] && row GREEN "systemd --failed" "none" || row RED "systemd --failed" "$failed unit(s): $(systemctl --failed --no-legend | awk '{print $1}' | paste -sd, -)"

[ "$JSON" = 1 ] || printf '\n%s: %d red, %d unknown  (uptime %s)\n' "$SHORT" "$red" "$unknown" "$(uptime -p)"
exit 0
