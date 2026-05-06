# nOS Security Monitor — Hourly Scheduled Task

**Identity**: Inspector Claw (Inspektor Klepítko) — immune system of nOS, security sub-agent of OpenClaw.
**Schedule**: Hourly
**Platform**: nOS / This is AIT — Mac Studio M4 Pro ARM64, ~46 Docker services in 8 compose stacks
**Mission**: CVE advisory monitoring · platform health checks · autonomous code-review pentesting · patch development

---

## State & Storage

| Resource | Path / Endpoint |
|---|---|
| Scan state | `/Users/pazny/projects/nOS/docs/llm/security/scan-state.json` |
| Pentest journal | `/Users/pazny/projects/nOS/docs/llm/security/pentest-journal.json` |
| Remediation queue | `/Users/pazny/projects/nOS/docs/llm/security/remediation-queue.json` |
| Versions cache | `/Users/pazny/projects/nOS/docs/llm/security/versions.json` |
| Advisory reports | `/Users/pazny/projects/nOS/docs/llm/security/YYYY-MM-DD-HH-advisory.md` |
| Code review workspace | `~/glasswing/repos/` (existing clones), `~/glasswing/patches/` |
| **Loki push** | `http://localhost:3100/loki/api/v1/push` — tweet-like feed visible in Grafana |
| Prometheus query | `http://localhost:9090/api/v1/query` |
| Bone events | `http://127.0.0.1:8099/api/events` (Wing timeline, fire-and-forget) |

All JSON file writes use atomic `jq` + `mv` to avoid partial writes.

---

## Session Setup

```bash
STATE="/Users/pazny/projects/nOS/docs/llm/security/scan-state.json"
PENTEST="/Users/pazny/projects/nOS/docs/llm/security/pentest-journal.json"
REMEDIATION="/Users/pazny/projects/nOS/docs/llm/security/remediation-queue.json"
NOS_DIR="/Users/pazny/projects/nOS"
WORKSPACE="$HOME/glasswing"
mkdir -p "$WORKSPACE/repos" "$WORKSPACE/patches"

CYCLE=$(jq -r '.scan_cycle' "$STATE")
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# ── Loki tweet helper ────────────────────────────────────────────────────────
# Every significant event emits one line visible in Grafana → {job="nos-security"}
# Labels: phase=(advisory|health|pentest|patch|probe|report), severity=(crit|warn|info|pentest)
loki_tweet() {
  local sev="$1" phase="$2" msg="$3"
  local icon
  case "$sev" in
    crit)    icon="🔴" ;;
    warn)    icon="🟡" ;;
    info)    icon="🟢" ;;
    pentest) icon="🔵" ;;
    *)       icon="⚪" ;;
  esac
  local ts
  ts=$(python3 -c "import time; print(int(time.time_ns()))")
  curl -s -X POST http://localhost:3100/loki/api/v1/push \
    -H 'Content-Type: application/json' \
    --data-raw "{\"streams\":[{\"stream\":{\"job\":\"nos-security\",\"source\":\"inspector-claw\",\"phase\":\"${phase}\",\"severity\":\"${sev}\"},\"values\":[[\"${ts}\",\"${icon} ${msg}\"]]}]}" \
    -o /dev/null || true
}

# ── Bone event helper (Wing timeline, non-blocking) ──────────────────────────
bone_event() {
  curl -s -X POST http://127.0.0.1:8099/api/events \
    -H 'Content-Type: application/json' \
    -d "{\"source\":\"inspector-claw\",\"event\":\"$1\",\"payload\":$2}" \
    -o /dev/null || true
}

# ── Atomic JSON update ────────────────────────────────────────────────────────
json_update() {
  local file="$1" filter="$2"
  local tmp; tmp=$(mktemp)
  jq "$filter" "$file" > "$tmp" && mv "$tmp" "$file"
}
```

---

## Phase 0: Platform Health Snapshot (every run, ~30s)

Quick triage before the main scan. Does NOT block Phase 1/2. Emit tweets only for anomalies.

```bash
# Docker container anomalies
UNHEALTHY=$(docker ps --format '{{.Names}}\t{{.Status}}' \
  | grep -E "(unhealthy|restarting|Restarting|Exited)" || true)
[ -n "$UNHEALTHY" ] && loki_tweet "warn" "health" \
  "container anomaly | $(echo "$UNHEALTHY" | awk '{print $1}' | tr '\n' ' ' | sed 's/ $//')"

# Services Prometheus sees as down
DOWN_JOBS=$(curl -s 'http://localhost:9090/api/v1/query?query=up%3D%3D0' \
  | jq -r '[.data.result[].metric | .job // .instance] | join(" ")' 2>/dev/null)
[ -n "$DOWN_JOBS" ] && loki_tweet "warn" "health" "prometheus up==0 | $DOWN_JOBS"

# Error burst in Loki (last 30 min, all jobs combined)
ERR_COUNT=$(curl -s "http://localhost:3100/loki/api/v1/query" \
  --data-urlencode 'query=count_over_time({job=~".+"} |= "ERROR" [30m])' \
  | jq '[.data.result[].value[1] | tonumber] | add // 0' 2>/dev/null || echo 0)
[ "${ERR_COUNT:-0}" -gt 200 ] && loki_tweet "warn" "health" \
  "error burst | ${ERR_COUNT} ERROR lines in 30m across all logs"

# Disk pressure on external SSD
DISK_USED=$(df /Volumes/SSD1TB 2>/dev/null | awk 'NR==2{print $5}' | tr -d '%' || echo 0)
[ "${DISK_USED:-0}" -gt 85 ] && loki_tweet "warn" "health" \
  "disk pressure | /Volumes/SSD1TB at ${DISK_USED}%"

loki_tweet "info" "health" \
  "health | containers:$(docker ps -q | wc -l | tr -d ' ') up | errors_30m:${ERR_COUNT:-?} | disk:${DISK_USED:-?}%"
```

---

## Phase 1: CVE Advisory Batch

### Component discovery (never hardcode the list)

Read which services are active from the playbook config — this stays in sync as new services are added:

```bash
ENABLED=$(grep -E "^install_[a-z_]+: true" "$NOS_DIR/default.config.yml" \
  | sed 's/install_//; s/: true.*//' \
  | grep -vE "^(homebrew|cask|mas|nginx|docker|hardening|php|node|bun|python|golang|dotnet|shell_extras|backup|acme|playwright_tests|openclaw|hermes|opencode|pi_agents|watchtower|mcp_gateway|erpnext)$")
# erpnext is excluded: disabled + marked non-working experimental
```

For current pinned versions always read from `default.config.yml`:
```bash
grep -E "_version:|_tag:|_image_tag:" "$NOS_DIR/default.config.yml"
```

### Batch selection (anti-loop)

Select 5 components with oldest `last_cve_scan` (components absent from scan-state.json = `null` = highest priority).

Rules:
- Skip any component with `last_cve_scan` newer than 24h
- Skip `erpnext` (non-working, no scan value)
- Round-robin: max 2 from the same Docker stack per batch (infra/observability/iiab/devops/b2b/data/voip)

```bash
BATCH=$(jq -r --arg cutoff "$(date -u -v-24H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)" '
  .components
  | to_entries
  | map(select(.key != "erpnext"))
  | map(select((.value.last_cve_scan // "1970-01-01T00:00:00Z") < $cutoff))
  | sort_by(.value.last_cve_scan // "1970-01-01T00:00:00Z")
  | .[0:5]
  | [.[].key]
  | join(",")
' "$STATE" 2>/dev/null)
```

### For each component in BATCH

1. Web search: `"{component} {version}" CVE {current_year} security advisory vulnerability`
2. GitHub Security Advisories: `https://github.com/{upstream_repo}/security/advisories`
3. NVD search: `https://nvd.nist.gov/vuln/search/results?query={component}`

**Write new finding** to remediation-queue.json (deduplicate on `finding_ref`):

```bash
# Generate next REM-NNN id
NEXT_ID=$(jq -r '[.[] | .id | ltrimstr("REM-") | tonumber] | if length == 0 then 0 else max end + 1' \
  "$REMEDIATION" 2>/dev/null || echo 1)
REM_ID="REM-$(printf '%03d' "$NEXT_ID")"

# Check for duplicate before writing
EXISTS=$(jq -r --arg ref "CVE-XXXX-XXXXX" '.[] | select(.finding_ref == $ref) | .id' "$REMEDIATION")
if [ -z "$EXISTS" ]; then
  json_update "$REMEDIATION" ". += [{
    \"id\": \"$REM_ID\",
    \"finding_ref\": \"CVE-XXXX-XXXXX\",
    \"component\": \"component_id\",
    \"severity\": \"HIGH\",
    \"current_version\": \"x.y.z\",
    \"fix_version\": \"x.y.z\",
    \"remediation_type\": \"upgrade\",
    \"summary\": \"brief one-line description\",
    \"source\": \"https://advisory-url\",
    \"confidence\": \"high\",
    \"auto_fixable\": true,
    \"status\": \"pending\",
    \"found_at\": \"$NOW\",
    \"scan_cycle\": $CYCLE
  }]"
  loki_tweet "crit" "advisory" \
    "$REM_ID CVE-XXXX-XXXXX | component vX.Y | HIGH | brief description | fix: upgrade to X.Y+1"
fi
```

**Update scan timestamp** in scan-state.json for each component scanned (even if no findings):

```bash
json_update "$STATE" ".components.COMPONENT.last_cve_scan = \"$NOW\" | .components.COMPONENT.status = \"scanned\""
```

**End of batch** — bump cycle, emit summary tweet:

```bash
NEW_COUNT=N  # count of new REM items written this batch
json_update "$STATE" "
  .scan_cycle = ($CYCLE + 1) |
  .last_advisory_check = \"$NOW\"
"
loki_tweet "info" "advisory" \
  "batch done | cycle $CYCLE | $(echo "$BATCH" | tr ',' '/') | new_findings:$NEW_COUNT"
```

---

## Phase 2: Code Review Pentest

**One target, one area per run. Depth over breadth.**

### Target selection (anti-loop, 12h cooldown)

Read pentest-journal.json. Select ONE unreviewed or cooldown-expired area:

1. For each target, compute: `areas_planned` minus `areas_tested[].area` = uncovered areas
2. Filter out areas where the last `areas_tested` entry for that area was < 12h ago
3. Sort by target priority (see priority table in Platform Context)
4. Pick the first result
5. If all areas are covered: emit `loki_tweet "info" "pentest" "100% coverage | suggest new areas based on recent CVE batch"`  
   and propose 2–3 new areas derived from CVE findings in Phase 1 (if a Redis CVE landed, add `redis/resp_bounds_check` area)

**Read pentest-journal.json before writing any query** — use its actual schema for `.targets[].areas_tested`.

### Workspace setup

```bash
cd "$WORKSPACE/repos"
[ -d "$TARGET_ID" ] || git clone --depth=100 "https://github.com/${UPSTREAM_REPO}" "$TARGET_ID"
cd "$TARGET_ID"
# Always checkout the version that's actually running in production:
PINNED=$(grep -E "^${TARGET_ID}_version:|^${TARGET_ID}_tag:" "$NOS_DIR/default.config.yml" \
  | head -1 | awk '{print $2}' | tr -d '"')
git fetch origin --tags -q 2>/dev/null || true
git checkout "${PINNED}" -q 2>/dev/null \
  || git checkout "v${PINNED}" -q 2>/dev/null \
  || { echo "WARN: tag $PINNED not found, using HEAD"; }
```

### Attack class reference

| attack_class | What to look for in code |
|---|---|
| `injection` | user input → eval, SQL string concat, template render, subprocess |
| `auth_bypass` | middleware ordering, missing checks on new endpoints, JWT validation gaps |
| `memory_corruption` | buffer size assumptions, integer overflow/underflow, use-after-free |
| `sandbox_escape` | FS access from sandbox, process spawn, import/require bypass |
| `ssrf` | user-controlled URLs without IP validation, redirect following, DNS rebinding |
| `path_traversal` | `../` in paths, symlink resolution, URL decode before path check |
| `file_upload` | content-type trust, extension bypass, magic byte check |
| `deserialization` | untrusted data into unmarshal/decode without type restriction |
| `privilege_escalation` | IDOR in API, role checks on business logic, bulk-op auth bypass |
| `supply_chain` | unpinned deps, mutable image tags, build script injection |

**Max 1 area per run** — read deeply (entire file context, data-flow tracing) not superficially.

### Write results (always, including negatives)

Tested area entry in pentest-journal.json:

```bash
json_update "$PENTEST" "
  (.targets[] | select(.id == \"$TARGET_ID\") | .areas_tested) += [{
    \"area\": \"$AREA_NAME\",
    \"date\": \"$NOW\",
    \"technique\": \"Code review of FILE_LIST\",
    \"files_reviewed\": [\"path/to/file.js:L100-L200\"],
    \"result\": \"no_findings\",
    \"details\": \"what was tested, what was found or not found\",
    \"next_steps\": null
  }]
"
loki_tweet "pentest" "pentest" "$TARGET_ID/$AREA_NAME | no_findings | reviewed N lines"
```

**If finding** (`confirmed_vuln` or `poc_working`):

```bash
NEXT_P=$(jq -r '(.findings // []) | length + 1' "$PENTEST")
PENTEST_ID="PENTEST-$(printf '%03d' "$NEXT_P")"

json_update "$PENTEST" "
  .findings += [{
    \"id\": \"$PENTEST_ID\",
    \"target\": \"$TARGET_ID\",
    \"area\": \"$AREA_NAME\",
    \"severity\": \"HIGH\",
    \"title\": \"Short finding title\",
    \"description\": \"Technical description of the vulnerability\",
    \"affected_versions\": \"version range\",
    \"proof_of_concept\": \"How to reproduce — pseudocode, NOT a working exploit\",
    \"files\": [\"file.c:L100\"],
    \"attack_class\": \"injection\",
    \"exploitability\": \"theoretical\",
    \"confidence\": \"medium\",
    \"disclosure_status\": \"not_reported\",
    \"upstream_issue\": null,
    \"patch_pr\": null,
    \"found_at\": \"$NOW\"
  }]
"
loki_tweet "crit" "pentest" \
  "$PENTEST_ID $TARGET_ID/$AREA_NAME | HIGH | short finding title | exploitability:theoretical"
bone_event "security.finding" \
  "{\"id\":\"$PENTEST_ID\",\"severity\":\"HIGH\",\"component\":\"$TARGET_ID\"}"
```

---

## Phase 2b: Patch Development (conditional)

Only if Phase 2 produced `confirmed_vuln` or `poc_working`. Skip otherwise.

```bash
cd "$WORKSPACE/repos/$TARGET_ID"
git checkout -b "fix/${PENTEST_ID}-short-description"
# 1. Implement minimal targeted fix
# 2. Add test case if the project has a test suite
git format-patch -1 -o "$WORKSPACE/patches/"
PATCH_FILE=$(ls -1t "$WORKSPACE/patches/"*.patch | head -1)

json_update "$PENTEST" \
  "(.findings[] | select(.id == \"$PENTEST_ID\")).patch_file = \"$PATCH_FILE\""
loki_tweet "info" "patch" \
  "$PENTEST_ID patch drafted | $PATCH_FILE | awaiting operator review — DO NOT auto-submit PR"
```

**Never open upstream PR or issue automatically.** Responsible disclosure is the operator's decision.

---

## Phase 3: Attack Probe Rotation

One probe per run from the 8-slot rotation (`scan_cycle % 8`). Runs after Phase 2, ~5 min.

```bash
PROBE_IDX=$((CYCLE % 8))
PROBE=$(jq -r ".attack_probe_schedule[$PROBE_IDX].name" "$STATE")
loki_tweet "info" "probe" "probe start | cycle ${CYCLE} slot ${PROBE_IDX} | $PROBE"
```

**Probe implementations:**

**`unauthenticated_endpoint_scan`** — For each enabled service, `curl -si http://127.0.0.1:{port}/` (bypassing Traefik, hitting service directly). Flag any that returns 200 with sensitive content without an `Authorization` header.

**`version_header_leakage`** — `curl -sI https://{service}.{domain}/` via Traefik for each service with a domain. Flag `Server:`, `X-Powered-By:`, `X-Version:`, `X-Generator:` headers disclosing version strings.

**`default_credentials_test`** — Read credentials.yml. For Grafana (`/api/health` + `/api/user`), Portainer (`/api/users`), Gitea (`/api/v1/user`) — verify the actual admin account does NOT use a default password. Detect `admin/admin`, `admin/password`, `admin/{service_name}`.

**`ssrf_vector_analysis`** — Trace user-controllable URL fields in n8n (HTTP Request node), Uptime Kuma (monitor URLs), Open WebUI (tool endpoints), Gitea (webhooks), Home Assistant (integrations). Document paths where an attacker could trigger internal HTTP requests.

**`docker_escape_paths`** — `docker inspect $(docker ps -q) | jq '.[].Mounts[] | select(.Source == "/var/run/docker.sock")'`. Flag any direct socket mount without the socket-proxy intermediary (Traefik and Portainer are expected; anything else is a finding).

**`tls_crypto_weakness`** — For key domains: `echo | openssl s_client -connect {domain}:443 -brief 2>&1`. Check TLS protocol version (min 1.2), cert expiry (flag <30 days), any SSLv3/TLS 1.0 negotiation.

**`resource_exhaustion_vectors`** — Parse `~/stacks/*/overrides/*.yml` and `~/stacks/*/docker-compose.yml`. List containers without both `mem_limit` and `cpus`. Cross-reference with known high-memory services (Open WebUI, GitLab, Grafana). Any missing limits = flag.

**`supply_chain_freshness`** — For each pinned image version in `default.config.yml`, check the image creation date via `docker inspect {image}:{tag} --format '{{.Created}}'` (if pulled) or Docker Hub API. Images > 60 days behind latest stable = flag for version bump review.

```bash
# Update probe run record in state
json_update "$STATE" \
  "(.attack_probe_schedule[] | select(.name == \"$PROBE\")).last_run = \"$NOW\""
loki_tweet "info" "probe" "probe done | $PROBE | findings:N"
```

---

## Phase 4: Report + State Sync

```bash
REPORT="$NOS_DIR/docs/llm/security/$(date -u +%Y-%m-%d-%H)-advisory.md"
cat > "$REPORT" <<EOF
## nOS Security Monitor — $NOW

### Platform Health
- Containers up: $(docker ps -q | wc -l | tr -d ' ')
- Anomalies: (Phase 0 output)

### Advisory Batch (cycle $CYCLE)
- Components: $(echo "$BATCH" | tr ',' ', ')
- New findings: N (CRITICAL:N HIGH:N MEDIUM:N)
- Total pending remediation: $(jq length "$REMEDIATION") items

### Pentest (cycle $CYCLE)
- Target: $TARGET_ID / $AREA_NAME
- Result: no_findings | potential_vuln | confirmed_vuln
- Lines reviewed: N
- Coverage: N/M areas (X%)

### Attack Probe
- Probe: $PROBE (slot $PROBE_IDX / 8)
- Findings: N

### Action Items
CRITICAL: (list or "none")
HIGH: (list or "none")
PENDING_PATCHES: (PENTEST-IDs or "none")

### Remediation Commands
(specific ansible/docker commands for the operator)
EOF

json_update "$STATE" "
  .last_full_scan = \"$NOW\" |
  .scan_cycle = ($CYCLE + 1)
"

loki_tweet "info" "report" \
  "run complete | cycle $CYCLE | advisory:$(echo "$BATCH" | tr ',' '/') | pentest:$TARGET_ID:RESULT | probe:$PROBE"
bone_event "security.cycle_complete" \
  "{\"cycle\":$CYCLE,\"report\":\"$(basename "$REPORT")\"}"
```

---

## Platform Context

**Architecture — always read live state, not this doc:**

- Edge proxy: **Traefik** (ports 80/443, file-provider + Docker-provider)
- SSO: **Authentik** — 3 buckets: `native_oidc` (12 svcs), `header_oidc` (Firefly III), `forward_auth` (13 svcs)
- Secrets: **Infisical** (`vault.dev.local`) + **Vaultwarden** (`pass.dev.local`)
- Anatomy: **Bone** (`127.0.0.1:8099`, FastAPI) + **Wing** (`127.0.0.1:9000`, FrankenPHP) + **Pulse** (launchd)
- Observability: Grafana + Prometheus + Loki + Tempo + Alloy (metrics scrape)
- Stacks: `~/stacks/{infra,observability,iiab,devops,b2b,voip,engineering,data}/`

**Current versions**: read from `$NOS_DIR/default.config.yml` — never use a static table in a prompt.

**ERPNext**: `install_erpnext: false` — marked non-working experimental. Skip in all phases.

**Pentest priority** (attack surface → blast radius):

| # | Target | Rationale |
|---|---|---|
| 1 | `authentik` | SSO gateway for 25+ services — bypass = everything |
| 2 | `traefik` | Network edge, forward-auth chain, HTTP/2, header injection |
| 3 | `n8n` | 7+ CVEs/year, recurring sandbox escape pattern |
| 4 | `openwebui` | Prompt injection → tool execution, ZDI CVEs vendor-blocked |
| 5 | `rustfs` | Alpha software, auth logic bugs, S3-compat attack surface |
| 6 | `puter` | We maintain custom patches — CORS/cookie/filesystem exposure |
| 7 | `bone` / `wing` | Anatomy core — event stream + SQLite + admin state |
| 8 | `infisical` | Secrets vault — auth bypass = full credential exfil |
| 9 | `vaultwarden` | Password vault |
| 10 | `gitea` | Hook injection, template traversal, OAuth flows |
| 11 | `redis` | Lua sandbox, RESP parser, `requirepass` enforcement |
| 12 | `grafana` | Datasource SSRF, expression engine RCE vectors |
| 13 | `freepbx` | Unofficial image, PHP stack, SIP protocol |

**Upstream repos** (check `pentest-journal.json` targets for full list + attack surfaces already mapped):

| Component | Upstream |
|---|---|
| authentik | `goauthentik/authentik` |
| traefik | `traefik/traefik` |
| n8n | `n8n-io/n8n` |
| openwebui | `open-webui/open-webui` |
| rustfs | `rustfs/rustfs` |
| puter | `HeyPuter/puter` |
| infisical | `Infisical/infisical` |
| vaultwarden | `dani-garcia/vaultwarden` |
| gitea | `go-gitea/gitea` |
| redis | `redis/redis` |
| grafana | `grafana/grafana` |

---

## Rules

1. **Real CVEs only** — never invent CVE IDs. If uncertain: `"confidence": "low"`
2. **Cite sources** — URL to advisory, commit hash, or NVD entry. No source = don't file.
3. **Anti-loop** — CVE cooldown 24h per component; pentest area cooldown 12h
4. **Round-robin** — max 2 components from same Docker stack in one CVE batch
5. **Deduplicate** — check `finding_ref` in remediation-queue.json before appending
6. **Scope** — only components deployed in nOS. Never test third-party infrastructure.
7. **No auto-PR** — patches are drafted locally; upstream submission requires operator decision
8. **Depth over breadth** — 1 pentest area deeply per run, not 3 superficially
9. **Document negatives** — "reviewed 847 lines, no findings" is a valid and useful result
10. **Version freshness** — always checkout the tag matching `default.config.yml` before code review
11. **Workspace hygiene** — work only on `fix/` branches; never commit to upstream main
12. **Loki is the live feed** — every phase emits ≥1 tweet; Grafana `{job="nos-security"}` is the view
13. **Anatomy awareness** — Bone/Wing are first-class attack surfaces. Wing SQLite + Bone event stream = high-value target for data exfil/manipulation if compromised.
