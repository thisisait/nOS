# Active work — what to do right now

> **Always-current pointer for the next session.** Read this BEFORE
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md) — that file is the
> long-form plan, this one is just the next-step finger-pointer.
>
> Last updated: 2026-05-03 evening • by: pazny+claude
> • status: P0–P3 batch landed, security hardening Phase A/B/C ahead

---

## Current track: **Security hardening — Phase A/B/C** (post-P0/P3 cleanup)

> **P0–P3 batch DONE 2026-05-03 evening.** 5 production blockers + 5
> chained Bone HMAC bugs all fixed; Wing /hub clean (51/51 systems
> with proper ids); Tier-2 wet-test pipeline complete (post-blank.sh,
> tests/wet/, Cowork prompt); 30 stale remediation_items reconciled
> (was 54 pending, now 24).

### Last verified state (2026-05-03 19:32)

`--tags apps,wing,nginx,traefik` re-run: `ok=151 changed=12 failed=0`.
Earlier full blank: `ok=920 changed=282 failed=0`.

- Wing /hub: 51 systems with clean IDs (was 51 with `install_*` prefix orphans)
- Bone /api/services: 51/51 with derived `id` field (was 0/51)
- Bone events DB: HMAC pipeline functional (HTTP 200 accepted=true)
- Pulse: idle-tolerant, healthy, ready for 24/7 (warns on 302 from
  unfinished Wing API endpoints; no crash)
- code-server, Open WebUI, Puter all reachable + SSO works on pazny.eu
- Tier-2 (twofauth/roundcube/documenso) green
- 56 remediation_items resolved / 24 pending

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

## Current sub-step: **Phase A — quick CVE pins** (1 batch, ~45 min)

24 pending remediation_items remain. Phase A clears 7 of them via
mechanical config-only changes. See full plan in `docs/security-remediation-plan.md`
(written next session) or in this session's transcript.

**Phase A items (auto_fixable=1, low risk):**

1. `metabase_version` pin (currently `latest`)
2. `ollama` Homebrew bump (CVE-2026-34940 OS Command Injection via Model URL)
3. `nginx` Homebrew bump → 1.29.7+ (4 CVEs in April 2026)
4. `tempo_version` pin (currently `latest`)
5. `uptime_kuma_version`: `1` → `1.23.x` (defer v2 major bump to Phase D)
6. `traefik` static config — add `encodedCharacters` deny list (`%2F %5C %00`)
7. Reconcile DB after pins (Python script tail of this session)

**Risk:** very low. All upstream tags reachable in our cache or via brew.

**After A:** ~17 pending remediation_items.

## Next sub-steps queued

### Phase B — Resource limits sweep (~1 day, 1 commit)

`mem_limit` + `cpus` on every docker service per the recommended matrix:

| Tier | Memory | CPUs |
|---|---|---|
| GitLab | 4 GB | 2 |
| ERPNext (3 containers) | 1 GB | 1 each |
| Critical (postgres, mariadb, authentik, traefik, infisical) | 2 GB | 2 |
| Medium (grafana, n8n, nextcloud, etc.) | 1 GB | 1 |
| Low (utility/sidecar) | 512 MB | 0.5 |

Pattern: introduce a Jinja macro `mem_limits(class)` in
`templates/_shared/limits.j2` (NEW), include from each role's
`compose.yml.j2`. Less boilerplate than copy-paste.

### Phase C — Hardening (~2 days, 3 commits)

| C.1 | Postgres SSL enable + propagate `PGSSLMODE=require` to all clients (~10 compose-override updates) |
| C.2 | ERPNext dedicated MariaDB user with least-privilege grants |
| C.3 | Open WebUI prompt-injection mitigation + `version-pins-proposal.json` 23 image pins |

### Phase D — Architectural (decision-required, defer)

| D.1 | Portainer docker-socket-proxy sidecar (1-2 d) |
| D.2 | Uptime Kuma v1 → v2 major migration (1-2 d, breaking config) |
| D.3 | FreePBX tag pinning — upstream `tiredofit/freepbx` version mapping research |
| D.4 | Woodpecker trusted repos feature (config + test) |

### Vendor-blocked (wait, no action)

- Open WebUI ZDI CVEs (no vendor patch yet)
- RustFS gRPC non-constant-time signature (vendor)
- Calibre-Web ReDoS (need version probe to confirm impact)

---

## After security batch: **bones & wings PoC continuation**

Phase status (per `docs/bones-and-wings-refactor.md` §8):

| Phase | What | Status |
|---|---|---|
| A0–A4, A6 | skeleton + anatomize-move + bone host launchd + pulse + plugin loader | ✅ DONE |
| **A3.5** | **wing host-revert via FrankenPHP** | NEXT after security batch |
| A5 | wing OpenAPI/DDL exports | not started |
| A6.5 | Grafana thin-role pilot — doctrine proof | NEXT (post-A3.5) |
| A7 | gitleaks plugin (first real plugin via loader) | not started |
| A8 | conductor agent + agent runner | not started |
| A9 | notification fanout | not started |
| A10 | audit trail (per-actor identity) | not started |

Plus **Track Q** (autowiring debt — 30 of 71 roles carry post.yml
cross-service wiring totalling ~3000 LOC; consolidation in 7 batches,
4-6 weeks). Begins with Q1 (observability) once A6.5 Grafana thin-role
pilot proves the doctrine. Plan in `docs/bones-and-wings-refactor.md`
§13.1 + `files/anatomy/docs/role-thinning-recipe.md`.

---

## Quick state-of-the-world snapshot

| Surface | State |
|---|---|
| `git status` | dirty (P0–P3 batch staged for commit; 7 logical commits planned) |
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
| Remediation queue | 56 resolved / 24 pending (was 26/54 at session start) |
| Next gate | Phase A commit + autonomous batch |

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
