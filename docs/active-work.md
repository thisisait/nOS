# Active work — what to do right now

> **Always-current pointer for the next session.** Read this BEFORE
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md) — that file is the
> long-form plan, this one is just the next-step finger-pointer.
>
> Last updated: 2026-05-01 • commit: e4e877f post-Track-F-implementation • by: pazny+claude

---

## Current track: **F — Dynamic instance_tld + per-host alias**

[Section in roadmap →](roadmap-2026q2.md#track-f--dynamic-instance_tld--per-host-alias-after-e-d10)

## Current sub-step: **F5 — operator wet-verify blank**

Track F implementation **complete in 7 commits** `8e8a038..e4e877f` (incl. deep
review eliminating hardcoded `dev.local` across 174+ files). Phases 1-4, 6, 7
all done dry. Phase 5 = operator runs blank (default config + `host_alias=lab`
smoke) to wet-verify.

```bash
# 1. Default-config blank (gate F4 wet-verify)
ansible-playbook main.yml -K -e blank=true
# Expected: ok=891+ changed=267+ failed=0, 39/39 smoke OK, byte-identical
#           shape to 2026-05-01 16:37 baseline.

# 2. host_alias smoke (Phase F5 proper)
ansible-playbook main.yml -K -e blank=true -e host_alias=lab
# Expected: smoke endpoints respond on *.lab.dev.local; Authentik OIDC
#           redirect_uris list lab.dev.local hosts; mkcert generates a
#           wildcard with *.lab.dev.local + *.lab.apps.dev.local SANs.
```

If both green → Track F **DONE**, advance to Track G.

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

After G — **bones & wings refactor (planned, full plan written 2026-05-01):**

The former K/L/M arc was consolidated into one comprehensive plan with all 7 architectural
decisions resolved with operator on 2026-05-01. **Authoritative document:
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
| `git status` | clean (or pending commits — check before any write) |
| Last green blank | `ok=891 changed=267 failed=0 skipped=375` (2026-05-01 16:37) — **Track-E/J/H end-to-end gate ✅** Tier-2 pilots 3/3 healthy (documenso/roundcube/twofauth), 39/39 smoke OK |
| Last partial recovery | `ok=130 changed=10 failed=0 skipped=36` (2026-04-30 13:59) — Tier-2 stack 4/4 healthy, post-hooks all fired |
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
