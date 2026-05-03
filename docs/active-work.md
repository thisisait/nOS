# Active work — what to do right now

> **Always-current pointer for the next session.** Read this BEFORE
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md) — that file is the
> long-form plan, this one is just the next-step finger-pointer.
>
> Last updated: 2026-05-03 evening • commit: post-A6 plugin-loader landing (`717c446`) • by: pazny+claude

---

## Current track: **Bones & Wings refactor — PoC mid-flight** (A0..A6 landed, blank-verification next)

> **Tracks F + G + bones&wings seed work all DONE.** Track G fully wet on `pazny.eu` (49/49 smoke green incl. Tier-2 + Wave A/B + Stalwart v0.11.8). Bones&wings PoC is **6 phases ahead of last week's plan** — A0+A1+A2+A3a+A4+A6 all landed since 2026-05-03 morning. Next gate: blank verifying A3a (bone host launchd) + A6 (plugin loader empty-set no-op) wet.

### Phase status (per `docs/bones-and-wings-refactor.md` §8)

| Phase | What | Status | Commit |
|---|---|---|---|
| A0 | files/anatomy/ skeleton + dual-path ansible.cfg | ✅ | `c09fc52` |
| A1 | migrations/library/module_utils/patches → files/anatomy/ | ✅ | `2abbb5d` |
| A2 | files/project-wing/ → files/anatomy/wing/ | ✅ | `4202f40` |
| A3a | bone container → host launchd (track-A reversal) + files/bone/ → files/anatomy/bone/ | ✅ | `717c446` |
| **A3.5** | **wing host-revert via FrankenPHP** | ⏳ NEXT after blank | — |
| A4 | pulse skeleton (host launchd, non-agentic only) | ✅ | `b101a0d` |
| A5 | wing OpenAPI/DDL exports | not started | — |
| A6 | plugin loader (4 hooks + DAG + aggregator + 25 tests) | ✅ | `717c446` |
| A6.5 | **Grafana thin-role pilot — doctrine proof** | NEXT (post-blank) | — |
| A7 | gitleaks plugin (first real plugin via loader) | not started | — |
| A8 | conductor agent + agent runner | not started | — |
| A9 | notification fanout | not started | — |
| A10 | audit trail (per-actor identity) | not started | — |

### Last green blank (2026-05-03 13:28)

`ok=849 changed=199 failed=0 skipped=412` — Track G wet on `pazny.eu`, 65 containers up, smoke 49/49 OK. Pre-anatomy state. Next blank verifies anatomy A3a + A6 + watchtower fix.

### Production blank survivors (six fixes during 2026-05-02 prod cutover)

| Commit | Fix |
|---|---|
| `5598342` | bluesky_pds_bridge: filter returns list not string (Jinja `>-` → `from_json` round-trip) |
| `dbde538` | acme: apex-first `acme_domains` order + tolerant cert-dir detection (legacy `*.zone/` shape) |
| `25998b9` | bluesky-pds: adopt new goat CLI shape (no `--invite-code` on `account create`) |
| `f97e22d` | acme: tolerate evolved skip-message formats (`'Skipping'` + `'Domains not changed'`) |
| `32489b4` | acme: copy cert files into bind-mount instead of symlinking host `$HOME` path (containers can't follow) |
| `84cc69a` | nos-smoke: redirect-loop detector + `docs/operator-domain-switch.md` Step 3.5 (CF Full-strict requirement) |

## Previous track: **F — Dynamic instance_tld + per-host alias** ✅

[Section in roadmap →](roadmap-2026q2.md#track-f--dynamic-instance_tld--per-host-alias-after-e-d10)

## Current sub-step: **operator blank verifies A3a + A6** (next 30-60min)

Pre-flight before next operator blank:

```bash
git log origin/master..HEAD --oneline | wc -l   # ~16 commits ahead
ansible-playbook main.yml --syntax-check         # clean
python3 -m pytest tests/ -q --ignore=tests/php   # 475 passed (+25 plugin loader, +16 pulse)
```

Operator runs:

```bash
ansible-playbook main.yml -K -e blank=true
```

**Watch for:**

1. **Bone host launchd** — `tail -f ~/bone/log/launchd.err.log` should show uvicorn binding 127.0.0.1:8099. `curl -s http://127.0.0.1:8099/api/health` returns 200 once warmed (≤60s). Track-A reversal cleanup task should remove any leftover bone container without complaints.
2. **Plugin loader hooks** — `grep "Plugin loader.*hook" ~/.nos/ansible.log` shows pre_render / pre_compose / post_compose all called; empty plugin set → all `ok no-op`.
3. **Watchtower** — `docker ps | grep watchtower` shows healthy (not "Restarting"); `nickfedor/watchtower:1.16.1` image instead of dead `containrrr/watchtower:1.7.1`.
4. **Smoke** — 49/49 OK retained.

**If blank green:** move to A3.5 (Wing FrankenPHP) — design has been chosen by operator 2026-05-03. Then A6.5 (Grafana thin-role pilot using new plugin loader).

## Previous sub-step: ~~Track G kickoff — Phase 1~~ DONE 2026-05-03 morning blank

Track F **DONE 2026-05-01** in 16 commits `8e8a038..69f021b`. All seven
phases (F1 survey → F7 docs) verified, plus deep-review covering
174-file hardcoded `dev.local` cleanup, plus edge-case input
normalization, plus smoke-pipeline fixes for nos-smoke subprocess.

**Track F final verification (both wet-blanks 2026-05-01 evening):**
- **F4 default-config**: `ok=892 changed=267 failed=0`, 38/39 smoke OK
  (1 wordpress 500 cold-start flake — 302 on retry, pre-existing not
  Track-F regression).
- **F5 host_alias=lab**: `ok=892 changed=268 failed=0`, **39/39 smoke
  OK** after passing host_alias to nos-smoke subprocess. Traefik
  reports 40 routers on `*.lab.dev.local`. All 3 Tier-2 piloti healthy
  on `*.lab.apps.dev.local`.

### What's done already (going into F)

- **Track E** (Tier-2 wet test) — DONE 2026-04-30, 3 piloti zelení end-to-end
- **Track J** (tech-debt cleanup) — DONE 2026-05-01, 6 commits `0a6a960..f321b6e`
- **Track H** (ansible-core 2.20+ tightening + 2.24 readiness) — DONE 2026-05-01, 7 commits `6767e56..72c021d`. Re-scoped per O17 because 2.24 not yet released; current state ships `ansible-core 2.20.5` floor + verified forward-compat under 2.21.0rc1 + ansible-lint production profile clean.
- **89 apps tests + 431 total tests** collecting clean (12 skipped on optional deps).
- **0 ansible-lint failures**, production profile.
- **`apps_subdomain` token already wired** in 4 places (parser + render + role) — Track F reuses this precedent for the 108 `instance_tld` occurrences.

### How to enter the work

**Operator gate first:** `ansible-playbook main.yml -K -e blank=true` on a clean
host. Expected: same `ok=N changed=M failed=0` shape, smoke 36+/36+, all 4
Tier-2 containers healthy, all 8 post-hooks fire, Authentik proxy providers
materialize, Wing /hub lists `app_*` rows. If any line red → triage as Track-E
recovery, no Track F until it's clean.

Once blank green:

1. **Phase F1 — survey** (~2h): inventory all 108 `instance_tld` occurrences.
   `grep -rn 'instance_tld' --include='*.yml' --include='*.j2' --include='*.py'`
   Categorize: (a) FQDN composition, (b) cookie domain, (c) cert SAN list,
   (d) DNS suffix (dnsmasq), (e) Authentik OIDC redirect_uris.
2. **Phase F2 — decompose** (~3h): introduce in `default.config.yml`:
   - `tenant_domain` (replaces today's `instance_tld`; default `dev.local`)
   - `host_alias` (default `""` — empty drops the segment)
   - `apps_subdomain` (already exists; default `apps`)
   - Resolved FQDN: `<svc>[.<host_alias>][.<apps_subdomain>].<tenant_domain>`
3. **Phase F3 — refactor consumers** (~6h): touch the 108 occurrences.
   Order: `pazny.acme` cert SAN → `pazny.traefik` static + dynamic config
   → `library/nos_apps_render._fqdn_for` (already accepts apps_subdomain
   kwarg) → `templates/service-registry.json.j2` → `roles/pazny.dnsmasq`
   → `tasks/nginx.yml` (legacy fallback path)
4. **Phase F4 — backwards-compat tests** (~1h): blank with default config
   produces byte-identical FQDNs to today's deploy. Operator's existing
   credentials.yml and config.yml survive without manual edits.
5. **Phase F5 — `host_alias` smoke test** (~2h): blank with `host_alias: "lab"`
   produces working `*.lab.dev.local` services, Authentik OIDC redirects work,
   Tier-2 still healthy.
6. **Phase F6 — migration recipe** (~1h): `migrations/2026-05-XX-instance-tld-decomposition.yml`
   migrates old config.yml `instance_tld: foo` to new `tenant_domain: foo`.
7. **Phase F7 — docs** (~1h): `docs/operator-domain-naming.md` explaining
   the three-segment composition + when to set `host_alias`.

### Where to look for diagnostics if something fails

| Symptom | Where to look |
|---|---|
| FQDN mismatch in Traefik | `curl -s http://127.0.0.1:8082/api/http/routers \| jq` |
| Cert SAN doesn't cover new hostname | `mkcert -CAROOT && openssl x509 -in $TLS_CERT -text \| grep DNS:` |
| Authentik OIDC redirect_uri rejected | Authentik admin → Applications → check redirect URI match |
| Wing /hub wrong URL | `sqlite3 ~/wing/wing.db "SELECT id, url FROM systems"` |
| dnsmasq doesn't resolve new FQDN | `dig @127.0.0.1 -p 5353 <fqdn>` |
| Cookie not shared cross-subdomain | DevTools → Cookies → check Domain=... |

---

## Tracks coming next (don't start until F is DONE)

- **G — Cloudflare proxy + LE production exposure (bsky / Stalwart SMTP / maybe Mastodon)** ([roadmap section](roadmap-2026q2.md#track-g--cloudflare-proxy--le-production-exposure-after-f-d11))
  — `pazny.acme` Cloudflare DNS-01 already exists; `pazny.smtp_stalwart` is a NEW role; Bluesky exposure flag flip. ~4-5 days.

After G — **bones & wings refactor (planned, full plan written 2026-05-01, doctrine elevated 2026-05-03):**

The former K/L/M arc was consolidated into one comprehensive plan with all 7 architectural
decisions resolved with operator on 2026-05-01; expanded 2026-05-03 with **§1.1 "tendons & vessels"
doctrine** (operator framing) and **first-class Track Q follow-on** (§13.1) for thin-role +
modular-wiring rollout across all Tier-1 roles. **Authoritative document:
[`docs/bones-and-wings-refactor.md`](bones-and-wings-refactor.md).**

- **All-local architecture** — Wing PHP-FPM + Bone/Pulse Python via launchd (reverses Track A
  containerization for the platform-control plane; zero-trust between subsystems)
- **Repo reorg** — `files/anatomy/` umbrella; moves `migrations/`, `library/`, `module_utils/`,
  `patches/`, framework-internal `docs/` into anatomy
- **Plugin system** — drop-a-directory auto-wiring; gitleaks as PoC plugin
- **Conductor as primary agent** (PoC); inspektor/librarian/scout post-PoC, ~2-4h each
- **PoC estimate: ~12 days sequential.** Post-PoC expansion incremental.

Pre-implementation gates: Tracks F + G DONE + Stalwart SMTP shipped (from G).

Tracks A–E + J + H are DONE. If you find yourself there, stop and re-read this file.

---

## Quick state-of-the-world snapshot

| Surface | State |
|---|---|
| `git status` | clean; `master` 7 commits ahead of `origin/master` (2026-05-02/03 production fixes — push when ready) |
| Last green blank | `ok=842 changed=262 failed=0` (2026-05-02, `tenant_domain=pazny.eu` PRODUCTION) — Track G wet, real LE wildcard via CF DNS-01, all 4 Tier-2 healthy, Authentik users provisioned, PDS DIDs created, smoke OK after CF Full-strict flip on 2026-05-03 |
| Last green blank (dev.local) | `ok=892 changed=268 failed=0` (2026-05-01 22:58, host_alias=lab) — Track F end-to-end |
| Apps stack | 4 healthy containers (twofauth, roundcube, documenso, documenso-db); Authentik proxy providers live |
| Tier-1 services | all healthy |
| Tests | 431 collected, 0 collection errors. 89 apps + 25 schema + 25 importer + 4 pilot manifests + 71 PHP pass. 12 skipped (optional deps). |
| ansible-lint | 0 failures, 0 warnings, **production profile** |
| ansible-core | 2.20.5 (operator + CI matrix); forward-compat verified under 2.21.0rc1 |
| Pilots live | `apps/twofauth.yml`, `apps/roundcube.yml`, `apps/documenso.yml`. `apps/plane.yml.draft` deferred. |
| Decision log | O1-O18 in roadmap-2026q2.md |
| Next gate | **Cleared 2026-05-01 16:37** — fresh blank green (`ok=891 failed=0`, 39/39 smoke ✅). Track F unblocked. |

---

## How to update this file

This file rots in days, not weeks. After every meaningful work session:

1. Update **Current track / sub-step** if you advanced
2. Update the snapshot table at the bottom (last blank/partial result, anything that flipped state)
3. If a track-level decision was made (e.g. "documenso DB moved from embedded to shared infra-postgres"), log it in the **Decision log** in `roadmap-2026q2.md` — that file is the long-form record
4. Commit `docs(roadmap): refresh active-work pointer`

If you finish a track entirely:
- Mark the track DONE in `roadmap-2026q2.md`
- Flip "Current track" here to the next one
- Reset "Current sub-step" to the next track's first sub-step
- Update the "Where to look for diagnostics" table to match the new track's surfaces
