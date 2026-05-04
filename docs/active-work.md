# Active work — what to do right now

> **Always-current pointer for the next session.** Read this BEFORE
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md) — that file is the
> long-form plan, this one is just the next-step finger-pointer.
>
> Last updated: 2026-05-03 evening (post-push) • by: pazny+claude
> • status: P0–P3 + Phase A/B/C-partial landed and pushed; sanity-check
>   HMAC false-positive fixed; next track is GitHub Actions CI green +
>   tune-and-thin doctrine pilot on Group D / C-real items

---

## Current track: **CI green pass + tune-and-thin pilot** (post-security-batch)

> **P0–P3 batch DONE 2026-05-03 evening.** 5 production blockers + 5
> chained Bone HMAC bugs all fixed; Wing /hub clean (51/51 systems
> with proper ids); Tier-2 wet-test pipeline complete (post-blank.sh,
> tests/wet/, Cowork prompt); 30 stale remediation_items reconciled
> (was 54 pending, now 24).

### Last verified state (2026-05-03 evening, post-batch)

`--tags apps,wing,nginx,traefik` re-run: `ok=151 changed=12 failed=0`.
Earlier full blank: `ok=920 changed=282 failed=0`.

- Wing /hub: 51 systems with clean IDs (was 51 with `install_*` prefix orphans)
- Bone /api/services: 51/51 with derived `id` field (was 0/51)
- Bone events DB: HMAC pipeline functional (HTTP 200 accepted=true)
- Pulse: idle-tolerant, healthy, ready for 24/7 (warns on 302 from
  unfinished Wing API endpoints; no crash)
- code-server, Open WebUI, Puter all reachable + SSO works on pazny.eu
- Tier-2 (twofauth/roundcube/documenso) green
- **66 remediation_items resolved / 14 pending** (was 26/54 at session start;
  +40 cleared this session via Phase A, mem_limit reconcile, openwebui hardening,
  Phase C openwebui prompt-injection, plus reconciler regex fix)
- All Phase A/B/C commits pushed to `origin/master` (2026-05-03 evening)

### What just landed (P0–P3 batch)

| Pri | Fix | Files |
|---|---|---|
| P0 | Wing systems IDs — strip `install_` prefix in PHP, sweep stale `*.dev.local` rows | `app/Model/SystemRepository.php`, `bin/ingest-registry.php`, `templates/service-registry.json.j2` |
| P1 | code-server Traefik route — `noverify@file` ↔ `insecure-skip` rename | `roles/pazny.traefik/templates/dynamic/middlewares.yml.j2` |
| P1 | Puter cert — added `*.os.pazny.eu` SAN, LE re-issued | `roles/pazny.acme/defaults/main.yml` |
| P2 | Open WebUI SSO — `REQUESTS_CA_BUNDLE` conditional on `tenant_domain_is_local` | `roles/pazny.open_webui/templates/compose.yml.j2` |
| P3 | HMAC chain — symmetric default + epoch ts + jq -cS canonical body + sha256= prefix accept + app.deployed type + WING_DB_PATH plist key | `default.config.yml`, `apps_runner/tasks/post.yml`, `bone/events.py`, `bone/templates/bone.plist.j2` |
| Bonus | Tier-2 wet-test infra + Bone HMAC delivery + apps_runner image probe local-cache fallback + ansible.builtin.pip → command sweep + plugin loader Ansiballz fix + 30 remediation_items reconciled | (see commits) |

---

## Current sub-step: **GitHub Actions CI green pass + tune-and-thin pilot**

Security batch + sanity-check fix pushed (2026-05-03 evening). Working tree
clean. **Two parallel sub-tracks for the next session:**

1. **CI green pass** — GitHub Actions currently failing per CLAUDE.md
   known debt. Separate session work; no blank required.
2. **Tune-and-thin doctrine pilot** — every role we touch from now on (for
   Group D / Group C-real fixes below) gets harvested into a tendons +
   vessels plugin draft under `files/anatomy/plugins/<service>-base/`
   alongside the in-place fix. Goal: shrink the Track Q backlog
   incrementally rather than as one mass migration. **Harvest rule:**

   - Wiring that connects the role to anatomy (Wing UI, Pulse jobs, audit,
     GDPR) → **tendon** block in the draft plugin manifest.
   - Wiring that connects it to infra/observability (DB, Prometheus,
     Loki, Grafana, OIDC, notifiers) → **vessel** block.
   - The role itself stays Tier-1 (`pazny.<service>`); only post-tasks +
     templated config moves into the plugin.
   - **Tier-2 demotion** (`apps/<name>.yml` manifest) is reserved for
     long-tail apps where Tier-1 install_<service> toggle, manifest entry,
     and bespoke Authentik integration are NOT required. Don't demote
     strategic services to Tier-2 just to look minimalistic — thin-role +
     plugin is the right shape there.

Operator's next blank, when triggered, runs:

```bash
ansible-playbook main.yml -K -e blank=true
bash tools/post-blank.sh   # expect: GREEN, 14/14 wet tests
```

## Tune-and-thin pilots landed (2026-05-03 evening)

| # | Target | Tier | What landed | REM closed |
|---|---|---|---|---|
| 1 | Woodpecker | 1 (role) | Live REM-002 hardening in role compose + `files/anatomy/plugins/woodpecker-base/` draft (plugin.yml + compose-extension template + README + harvest map) | REM-002 |
| 2 | Qdrant | 2 (app) | NEW Tier-2 manifest `apps/qdrant.yml` (vector DB, install today) + `files/anatomy/plugins/qdrant-base/` draft (default-collection bootstrap, Bone/Wing client glue, Prometheus scrape, Grafana dashboard slot, Wing /hub card) + LIVE Bone Python client + Wing PHP client + plist/compose env + Alloy scrape + Grafana dashboard JSON | n/a — new substrate |
| 3 | Portainer | 1 (role) | Live REM-001 hardening in `templates/stacks/infra/docker-compose.yml.j2` (drop NODES/PLUGINS/SECRETS/CONFIGS/SWARM/SYSTEM Docker Swarm flags + gate EXEC + DISTRIBUTION via 2 toggles) + `files/anatomy/plugins/portainer-base/` draft (272-LOC post.yml harvest as declarative `api_calls.sequence`) | REM-001 |
| 4 | Grafana | 1 (role) | Live mkcert CA conditional fix (mirrors Open WebUI 2026-05-03 morning regression class) + `files/anatomy/plugins/grafana-base/` README promoted with live-now map (every plugin block tagged with current pre-Q home) | A6.5 doctrine target |
| 5 | Vaultwarden | 1 (role) | Live mkcert CA + entrypoint + extra_hosts conditional fix (3rd instance of the same regression class) + `files/anatomy/plugins/vaultwarden-base/` draft (FIRST `data_subjects: end_users` pilot — `contract` legal basis, `retention=-1`, DSAR endpoint, blank-vault preservation) | mkcert regression |
| 6 | **Mkcert CA regression sweep** | cross-cutting | After 3 instances of the same bug (Open WebUI / Grafana / Vaultwarden) it was clearly a class. Live conditional gate applied to **11 more roles**: bookstack, code_server, freescout, gitlab, hedgedoc, miniflux, n8n, nodered, outline, paperclip, wordpress. Both volume mounts and `NODE_EXTRA_CA_CERTS` env vars now require `install_authentik AND tenant_domain_is_local`. Regression class CLOSED across the entire fleet (14 roles total). | mkcert regression class CLOSED |

**Doctrine status post-pilots:** workflow proven on both Tier-1 (role +
plugin draft) and Tier-2 (app manifest + plugin draft). Plugin manifest
shape stable across grafana-base / woodpecker-base / qdrant-base. Each
draft includes a "harvest map" comment block listing today's-surface →
this-manifest-block — gives Track Q a pre-built checklist per role
instead of re-doing inventory on each pass.

## Phase A/B/C — DONE this session

| Phase | Status | What landed |
|---|---|---|
| A — quick CVE pins | ✅ DONE | Traefik `encodedCharacters` deny (slash/backslash/null), uptime_kuma `1` → `1.23.13`, DB reconcile (4 pre-applied items: ollama 0.22.1, nginx 1.29.8, metabase v0.60.1.4, uptime_kuma 1.x covered REM-037) |
| B — mem_limit/cpus sweep | ✅ DONE (was already done) | 41/51 roles already use `docker_mem_limit_*` convention; remaining 10 confirmed full-coverage on inspection (gaps were volumes / CLI helpers, not services). REM-006 reconciled. |
| C — hardening (partial) | ✅ partial | Open WebUI prompt-injection mitigation (`CODE_INTERPRETER_ENGINE: pyodide` + `CHAT_RESPONSE_MAX_TOOL_CALL_RETRIES: 5`). REM-054 + REM-055 resolved. |

## Operator wet-test verification — Qdrant pilot (2026-05-04 morning)

Operator's full-blank run completed `ok=880 changed=276 failed=0` then a
follow-up `--tags apps` run completed `ok=137 changed=16 failed=0`. Two
inline fixes were committed during verification:

| Commit | Fix |
|---|---|
| `a917885` | Drop `QDRANT__STORAGE__OPTIMIZERS__MEMMAP_THRESHOLD=20000` env override — collided with image's default `config.yaml`, producing `duplicate field memmap_threshold` parse error and tight restart-loop |
| `7a29ad3` | Replace `wget --spider` healthcheck with `bash -c ':>/dev/tcp/127.0.0.1/6333'` — `qdrant/qdrant:v1.13.4` image strips curl/wget; previous probe logged 955× `wget: not found` over 8h and gated apps post-hooks off |

**Verified end-to-end on the second run** (post `7a29ad3`):

| Surface | State |
|---|---|
| Qdrant container | ✅ healthy via `bash /dev/tcp` probe |
| Wing `/systems` row | ✅ `app_qdrant` → `qdrant.apps.pazny.eu` |
| GDPR row in `gdpr_processing` | ✅ `legitimate_interests`, retention 365d |
| Bone `/api/v1/events` HMAC POSTs | ✅ 4× `app.deployed` accepted (HTTP 200) |
| `~/.nos/events/playbook.jsonl` mirror | ✅ 4 entries appended |
| Authentik proxy gate | auto-derived from `nginx.auth: proxy` (apps_runner) |
| Apps stack rc | ✅ 0 (was 1 before healthcheck fix) |

**Total session deliverable:** 5 tune-and-thin pilots (Woodpecker /
Qdrant / Portainer / Grafana / Vaultwarden) + cross-cutting mkcert CA
regression sweep across 14 roles + REM-001 + REM-002 closed + Qdrant
end-to-end live wiring (Bone client, Wing client, Grafana dashboard,
Prometheus scrape).

## 12 pending remediation items (post-session)

Three groups:

### Group D — Architectural (decision-required, schedule when operator has bandwidth)

| ID | Severity | What | Effort | Status |
|---|---|---|---|---|
| ~~REM-001~~ | ~~CRITICAL~~ | ~~Portainer docker-socket-proxy sidecar~~ | ~~1-2 d~~ | ✅ **CLOSED** 2026-05-03 (commit `cfca6a0`): trim Swarm/SYSTEM/DISTRIBUTION/EXEC flags + 2 toggles for security-sensitive operators; bundled with portainer-base draft (272-LOC harvest) |
| ~~REM-002~~ | ~~CRITICAL~~ | ~~Woodpecker trusted repos feature (config + test)~~ | ~~0.5 d~~ | ✅ **CLOSED** 2026-05-03 (commit `9b6544d`): `WOODPECKER_PLUGINS_PRIVILEGED=""` + `WOODPECKER_AUTHENTICATE_PUBLIC_REPOS=false`; bundled with woodpecker-base draft |
| REM-073 | HIGH | Uptime Kuma v1 → v2.2.1 major migration (breaking config schema) | 1-2 d | pending |
| REM-014/046 | CRITICAL | FreePBX upstream tag mapping research + pin | 0.5 d | pending |
| REM-044 | HIGH | Uptime Kuma admin SSRF — protocol-level mitigation (URL deny-list, no version) | 0.5 d | pending |

### Group C-real — Hardening (real work, dedicated session)

| ID | Severity | What | Effort |
|---|---|---|---|
| REM-008 | MEDIUM | ERPNext dedicated MariaDB user (least-privilege grants) | 0.5 d |
| REM-009 | MEDIUM | PostgreSQL SSL enable + `PGSSLMODE=require` across ~10 client roles | 1 d |
| REM-004 | HIGH | Pin 23 Docker images per `version-pins-proposal.json` (templates default fallback hardening) | 0.5 d |

### Group V — Vendor-blocked / mitigated by SSO gate (monitor + accept)

| ID | Severity | What | Why we wait |
|---|---|---|---|
| REM-064 | HIGH | Open WebUI ZDI CVE-2026-0765/0766 RCE | No vendor patch (Jan 2026 disclosure); admin-only access lowers risk |
| REM-074 | HIGH | Calibre-Web ReDoS (CVE-2025-6998) | Upstream unmaintained; Authentik proxy-auth gate makes login form unreachable; nginx rate-limit a future option |
| REM-059 | MEDIUM | RustFS gRPC non-constant-time sigverify | Pentest finding, vendor not yet patched |
| REM-036 | MEDIUM | Tempo /status/config exposure | Local storage (no S3), low impact for our deployment |
| REM-043 | CRITICAL | n8n unauthenticated SSRF via webhook | No specific fix_version; mitigated by Authentik forward-auth + Docker network isolation |

---

## After security batch: **bones & wings PoC continuation**

Phase status (per `docs/bones-and-wings-refactor.md` §8):

| Phase | What | Status |
|---|---|---|
| A0–A4, A6 | skeleton + anatomize-move + bone host launchd + pulse + plugin loader | ✅ DONE |
| **A3.5** | **wing host-revert via FrankenPHP** | ✅ DONE 2026-05-04 |
| A5 | wing OpenAPI/DDL exports | not started |
| A6.5 | Grafana thin-role pilot — doctrine proof | ✅ DONE 2026-05-04 (Track Q unblocked) |
| A7 | gitleaks plugin (first real plugin via loader) | not started |
| A8 | conductor agent + agent runner | not started |
| A9 | notification fanout | not started |
| A10 | audit trail (per-actor identity) | not started |

Plus **Track Q** (autowiring debt — 30 of 71 roles carry post.yml
cross-service wiring totalling ~3000 LOC; consolidation in 7 batches,
4-6 weeks). Begins with Q1 (observability) once A6.5 Grafana thin-role
pilot proves the doctrine. Plan in `docs/bones-and-wings-refactor.md`
§13.1 + `files/anatomy/docs/role-thinning-recipe.md`.

For the planned larger parallel implementation batch, use
`docs/bones-and-wings-bulk-plan.md`. It defines lane ownership, merge order,
shared-file locks, and wave gates for A3.5/A5/A6.5/A7-A10.

---

## Quick state-of-the-world snapshot

| Surface | State |
|---|---|
| `git status` | clean; **9 commits ahead of `origin/master`** awaiting push (`eac1892..7a29ad3`): Qdrant pilot, live wiring, Portainer REM-001, Grafana mkcert, Vaultwarden first-end_users pilot, mkcert sweep across 11 roles, Qdrant MEMMAP fix, Qdrant healthcheck fix |
| Last green blank | `ok=920 changed=282 failed=0` (2026-05-03 18:08, full blank) |
| Last partial green | `ok=151 changed=12 failed=0` (2026-05-03 19:32, `--tags apps,wing,nginx,traefik`) |
| Tier-1 services | all healthy; 51 systems registered in Wing /hub with clean IDs |
| Tier-2 stack | 4 healthy containers (twofauth, roundcube, documenso, documenso-db) |
| Bone /api/v1/events | HMAC pipeline functional, accepts `app.deployed` + standard callback types |
| Pulse | running on 30s tick, idle-tolerant (302/404 on unfinished Wing endpoints) |
| Tests | `tests/anatomy tests/wet tests/apps -q` → 151 passed; 14 wet tests cover sections 6/7/9 (skip pre-blank, fail under `NOS_WET=1`) |
| ansible-lint | 0 failures, production profile |
| ansible-core | 2.20.5 floor; verified forward-compat under 2.21.0rc1 |
| Decision log | O1-O18 in roadmap-2026q2.md |
| Remediation queue | **66 resolved / 14 pending** (was 26/54 at session start; +40 cleared) |
| Commits ahead | **0** — pushed; CI on GitHub Actions still failing per known-debt |
| Next gate | GitHub Actions green CI pass (separate session work) + tune-and-thin pilot on first Group D / C-real fix |

---

## How to update this file

This file rots in days, not weeks. After every meaningful work session:

1. Update **Current track / sub-step** if you advanced
2. Update the snapshot table at the bottom (last blank/partial result, anything that flipped state)
3. If a track-level decision was made, log it in the **Decision log** in `roadmap-2026q2.md` — that file is the long-form record
4. Commit `docs(roadmap): refresh active-work pointer`

If you finish a track entirely:
- Mark the track DONE in `roadmap-2026q2.md`
- Flip "Current track" here to the next one
- Reset "Current sub-step" to the next track's first sub-step
