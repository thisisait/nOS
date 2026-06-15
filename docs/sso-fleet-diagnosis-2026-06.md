# SSO Fleet Diagnosis — 2026-06

**Tenant:** `pazny.eu` (public TLD, real Let's Encrypt cert — CN=`pazny.eu`, issuer *Let's Encrypt YR2*)
**Authentik:** `auth.pazny.eu` (internal API `http://127.0.0.1:9003/api/v3`)
**Scope:** live read-only probe of the SSO fleet (edge vs origin, OIDC backend reachability, forward_auth gating, Authentik provider/outpost state).
**Mode:** READ-ONLY. Nothing was edited, restarted, recreated, or committed. All "fix" content below is a *proposal*, not an applied change.

---

## 0. Executive summary (read this first)

- **The SSO layer is healthy.** Every native_oidc backend that was reported as "Could not reach the OpenID Connect provider" is in fact **reachable and authenticating correctly** on this tenant. Every forward_auth gate **302-redirects to Authentik at both edge and origin**, and every proxy provider is **attached to the embedded outpost** (the tofu PK-churn self-reconcile is holding).
- **There is exactly ONE real bug in the fleet: Hermes.** And it is **not an SSO bug** — the forward_auth gate works perfectly; the *upstream host daemon* is dead in a launchd crash-loop because its Python venv lives on a TCC-blocked external SSD and a content-changed plist was never re-bootstrapped.
- **Most reported "symptoms" are working-as-designed**, chiefly *"forward_auth service has no Sign-in-with-Authentik button."* That is the **intended** UX for a pure access gate. Operator should **stop chasing these.**
- **One fleet-wide latent fragility worth pre-empting:** native_oidc backends point their *server-to-server* discovery/token URL at the **public** `https://auth.pazny.eu/...` instead of the internal `http://authentik-server:9000/...`. Harmless on this public-LE tenant; it would **break on a `.dev.local` / mkcert tenant**. This is the Portainer anti-pattern — Portainer already does it right (`roles/pazny.portainer/tasks/post.yml:349-350`).

**Highest-leverage action:** fix Hermes (one real bug). Then, as portability hardening, swap the native_oidc discovery/token URLs to internal. Everything else is documentation/expectation-setting, not engineering.

---

## 1. Per-service findings table

| Slug | Declared mode | Verdict | One-line root cause |
|------|---------------|---------|---------------------|
| nextcloud | native_oidc (user_oidc) | ✅ working | Public discovery URL configured (anti-pattern) but reachable + TLS-trusted on this public-LE tenant; full OIDC flow verified live. |
| gitea | native_oidc | ✅ working | Same latent public-discovery pattern; functional on this tenant. |
| grafana | native_oidc | ✅ working | Same latent public-discovery pattern; functional on this tenant. |
| bookstack | native_oidc | ✅ working | Same latent public-discovery pattern; functional on this tenant. |
| open-webui | native_oidc | ✅ working | Same latent public-discovery pattern; functional on this tenant. |
| miniflux | native_oidc | ✅ working | Same latent public-discovery pattern; functional on this tenant. |
| vaultwarden | native_oidc | ✅ working | Same latent public-discovery pattern; functional on this tenant. |
| portainer | native_oidc | ✅ working (reference) | Already uses internal `http://authentik-server:9000/...` for token/userinfo — the proven fix the others should adopt. |
| infisical | forward_auth | ✅ working-as-designed | No in-app SSO button by design; gate 302s to Authentik; provider pk=125 attached to outpost. CE org-OIDC enterprise-lock ⇒ gate-only is the ceiling, not a bug. |
| snappymail | forward_auth | ✅ working-as-designed | No SSO button by design; gate 302s correctly; provider pk=112 attached. Inner IMAP login is the inner identity (expected). |
| roundcube | forward_auth | ✅ working-as-designed | No SSO button by design; gate 302s correctly; provider pk=47 attached. Inner IMAP login is the inner identity (expected). |
| uptime-kuma | forward_auth | ✅ working-as-designed | No SSO button by design; gate 302s correctly; provider pk=42 attached. |
| onlyoffice | forward_auth (carve-out) | ✅ working-as-designed | Intentionally NOT forward-auth-gated on the embed surface (JWT-secured); `/example` 502 is the disabled demo harness, not a fault. |
| **hermes** | **forward_auth** | ❌ **BROKEN** | **Gate is healthy; the gated host daemon is dead** — launchd crash-loop, venv on TCC-blocked `/Volumes/SSD1TB`, stale plist never re-bootstrapped. Nothing listens on `127.0.0.1:18790`. |

---

## 2. Recurring root-cause classes

### Class A — `native-oidc-public-discovery-url-latent` (latent, NOT a current bug)
**Affected:** nextcloud, gitea, grafana, bookstack, open-webui, miniflux, vaultwarden
**Severity:** low (portability only) · **is_real_bug: false**

These native_oidc services aim their **server-to-server** OIDC discovery/token/userinfo at the **public** `https://auth.pazny.eu/...` rather than the internal Docker URL `http://authentik-server:9000/...` that Portainer uses (`roles/pazny.portainer/tasks/post.yml:349-350`).

- On a **local/mkcert TLD** this is the exact failure that breaks Portainer: the container can't validate the mkcert CA and must round-trip the public edge → *"Could not reach the OpenID Connect provider."*
- It **does NOT break here** because `tenant_domain=pazny.eu` is a public TLD with a real LE cert the container CA bundles already trust, and most containers carry `extra_hosts: auth.pazny.eu:host-gateway` so the backend call resolves to the **local** host Traefik, not Cloudflare.
- Live-verified in every case: discovery `200`, token endpoint alive, `client_secret` matches the Authentik provider, `redirect_uri` strict-matches.

**Worked example — nextcloud (the reported case):** `occ user_oidc:provider` → discovery `https://auth.pazny.eu/application/o/nextcloud/.well-known/openid-configuration`, client_id `nos-nextcloud`. From *inside* the container: `curl` with TLS verify ON → `200`; PHP `file_get_contents` (`verify_peer=true`) → OK (len 2038); Nextcloud's **own** Guzzle `IClientService` (the exact path `user_oidc` uses) → `200`. Real token exchange with the live secret → `invalid_grant` (NOT `invalid_client`) ⇒ client authenticated, secret correct. Authentik provider pk=34 `Nextcloud`, strict redirect `https://cloud.pazny.eu/apps/user_oidc/code` = MATCH. No OIDC errors in `nextcloud.log`. **SSO works.**

### Class B — `forward-auth-no-button-by-design` (working-as-designed, NOT a bug)
**Affected:** infisical, snappymail, roundcube, uptime-kuma
**Severity:** none · **is_real_bug: false**

All four are forward_auth pure access gates. There is intentionally **no** in-app "Sign in with Authentik" button — the embedded outpost intercepts at the Traefik `authentik@file` middleware **before** the service renders. Live-verified: both edge and origin `curl` 302-redirect to `https://auth.pazny.eu/application/o/authorize/`; the Traefik router carries `authentik@file`; the proxy provider exists **and** is attached to the embedded outpost (infisical pk=125, snappymail pk=112, roundcube pk=47, uptime-kuma pk=42). After the Authentik gate, services with their own login (snappymail/roundcube IMAP, infisical email form) present it as the **inner identity** — also by design. infisical additionally hits the CE org-OIDC enterprise-lock ceiling (no native button possible on CE) — same verdict.

### Class C — `forward-auth-ungated-by-design-jwt` (working-as-designed carve-out)
**Affected:** onlyoffice
**Severity:** none · **is_real_bug: false**

OnlyOffice's document-server embed surface is intentionally **not** forward-auth-gated — it is JWT-secured for the iframe-embedding host (Nextcloud/BookStack/Outline). The `/example` `502` is the **disabled demo harness**, not a broken route.

### Class D — `hermes-host-daemon-crashloop` (the ONE real bug)
**Affected:** hermes · **Severity:** high · **is_real_bug: true**
**This is a host-runtime fault, not an SSO/Traefik/Authentik fault.** See §4 (priority 1) for the full evidence chain and fix.

---

## 3. Working-as-designed vs real bugs — stop chasing these

| Reported symptom | Verdict | Why |
|------------------|---------|-----|
| "infisical/snappymail/roundcube/uptime-kuma have no Sign-in-with-Authentik button" | ✅ **WORKING-AS-DESIGNED** | forward_auth is a *pure access gate* — no in-app button **by design** (`docs/sso-and-attribution.md`). The Authentik outpost gates *before* the app. Live gates 302 correctly. |
| "infisical won't show a native OIDC button" | ✅ **WORKING-AS-DESIGNED (ceiling)** | Infisical **CE** locks org-OIDC behind the enterprise tier. forward_auth gate + own email form is the documented ceiling, not a regression. |
| "snappymail/roundcube still ask for a password after Authentik" | ✅ **WORKING-AS-DESIGNED** | The inner IMAP credential is the *inner identity*. Authentik gates access; IMAP auth is a separate, expected layer. |
| "onlyoffice `/example` returns 502" | ✅ **WORKING-AS-DESIGNED** | `/example` is the disabled demo harness. The embed surface is JWT-secured, intentionally un-gated. |
| "nextcloud (and the other native_oidc apps) say 'Could not reach the OIDC provider'" | ⚠️ **NOT REPRODUCIBLE / not broken here** | Public discovery URL is the latent anti-pattern, but on this public-LE tenant it is fully reachable + TLS-trusted. Full flow verified live. Real risk only on a mkcert TLD. |
| "hermes shows a Cloudflare error page after login" | ❌ **REAL BUG** | The **gate works** — the *upstream daemon is dead* (launchd crash-loop). Authenticated user hits a dead Traefik upstream → bad-gateway. |

**Bottom line for the operator:** the only thing actually broken is Hermes, and it is broken *behind* a working SSO gate. Do not touch Traefik routes, Authentik providers, outpost attachments, or any OIDC env for any of the green rows above.

---

## 4. Prioritised action list (highest leverage first)

### Priority 1 — Fix Hermes (the only real bug) · effort: ~30 min runtime + ~1 h repo
**Symptom:** authenticated users hit a Cloudflare/bad-gateway page after the Authentik gate.
**Root cause (evidence chain):**
- Edge AND origin both return `HTTP 302 → https://auth.pazny.eu/application/o/authorize/?client_id=...` → **gate fires correctly at both layers.**
- `GET /providers/proxy/?search=Hermes` → pk=121, `external_host=https://hermes.pazny.eu`, `mode=forward_single`. `GET /outposts/instances/` → embedded outpost providers list **includes 121** (attachment present).
- Traefik `conf.d/services.yml`: router `hermes@file` → `Host(\`hermes.pazny.eu\`)`, middleware `authentik@file`, upstream `http://192.168.65.254:18790`.
- **Backend dead:** `lsof -iTCP:18790` empty; `curl http://127.0.0.1:18790/` → `HTTP 000`.
- `launchctl print gui/$UID/eu.thisisait.nos.hermes` → program `/Volumes/SSD1TB/hermes/.venv/bin/hermes`, **last exit code 1, runs=85+**, respawn loop.
- `~/agents/log/launchd.err.log`: `PermissionError: [Errno 1] Operation not permitted: '/Volumes/SSD1TB/hermes/.venv/pyvenv.cfg'` → `Fatal Python error: init_import_site`. **macOS TCC denies launchd-spawned reads of the external removable volume.** The interpreter dies before any Hermes code runs.
- On-disk plist (`~/Library/LaunchAgents/eu.thisisait.nos.hermes.plist`, mtime 15 Jun 14:10) already points at the host-local `/Users/pazny/agents/hermes/.venv/bin/hermes` — **but the loaded job still carries the stale `/Volumes/SSD1TB` path.** The plist was corrected on disk and never re-bootstrapped.

**Fix — three coordinated parts (none touch SSO/Traefik/Authentik/Hermes code):**

1. **Operator-runtime one-off (un-sticks the live box NOW, no playbook needed):**
   ```
   launchctl bootout   gui/$(id -u)/eu.thisisait.nos.hermes
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/eu.thisisait.nos.hermes.plist
   ```
   The on-disk plist already points at the readable host-local venv, so a single bootout+bootstrap converges the live job and the daemon binds `127.0.0.1:18790`.

2. **Repo FIX B — `tasks/stacks/external-paths.yml:119-122` (the TCC root cause):** stop moving `hermes_venv` onto `{{ external_storage_root }}` (=`/Volumes/SSD1TB`). A venv a launchd-spawned interpreter must read at startup (`pyvenv.cfg`, site module) **cannot** live on the external removable volume — TCC denies launchd's reads there. Keep `hermes_venv` under `$HOME` (the role default `~/agents/hermes/.venv` is provably readable). If blank-speed matters, keep only large model/source caches on the SSD, never the venv. The comment at `:117-118` ("Only venv + sources on SSD for fast --blank") is the buggy intent — invert it. *(Confirmed live: lines 120-122 set both `hermes_home` and `hermes_venv` under `external_storage_root`.)*

3. **Repo FIX A — `roles/pazny.hermes/tasks/main.yml` + `handlers/main.yml` (the structural gap that let the corrected plist sit un-applied):** the Restart-hermes handler runs `launchctl kickstart -k` which **re-runs the existing definition** — it does NOT re-read a changed `ProgramArguments`. And the "Bootstrap launchd job (idempotent)" task short-circuits to `already-loaded` whenever the unit exists, so a content-changed plist never reconciles. Replace the bare `kickstart -k` with a **bootout-then-bootstrap reload** (the same pattern Bone/Pulse/Wing already use), driven off `register: _hermes_plist` / `_hermes_plist is changed` so steady-state stays `changed=0`.

**Suggested gate:** `tests/anatomy/test_hermes_venv_not_on_external_ssd.py` (offline) — assert `external-paths.yml` does NOT `set_fact` any `*_venv` under `external_storage_root`, and that the Hermes restart handler does a real `bootout`+`bootstrap` (not a bare `kickstart -k`). Extend the existing Bone/Pulse/Wing reload-on-render parity check to cover Hermes.

**Risk:** low. SSO layer untouched and provably correct.

### Priority 2 — Native_oidc internal-discovery hardening (portability) · effort: ~2 h
Swap the **server-to-server** discovery/token/userinfo URLs from public `https://auth.pazny.eu/...` to internal `http://authentik-server:9000/application/o/<slug>/...` for the Class-A services, **keeping browser-facing authorize/redirect/logout on the public URL** — mirroring `roles/pazny.portainer/tasks/post.yml:349-350`. For Nextcloud specifically: `user_oidc` `discoveryuri` in `tasks/stacks/authentik_service_post.yml` and `files/anatomy/plugins/nextcloud-base/hooks/post_compose.yml` (both currently template `https://{{ authentik_domain }}/...`). **Not required on this public-LE tenant**; it removes the only thing that would break the same fleet on a `.dev.local`/mkcert tenant. Do **not** rush — there is no live breakage. Add a gate asserting native_oidc backends use the internal discovery host.

### Priority 3 — Documentation / expectation-setting · effort: ~30 min
Add a short "forward_auth has no in-app button BY DESIGN" callout to the operator-facing SSO docs (or pin it in `docs/sso-and-attribution.md`'s summary) and link this report, so the no-button symptom stops generating diagnostic cycles. List the CE/OSS SSO ceilings (infisical CE org-OIDC enterprise-lock, the IMAP inner-identity for snappymail/roundcube, the OnlyOffice JWT carve-out) in one place.

### Priority 4 — Secrets-domain consolidation decision · effort: decision only (see §5)
No engineering needed now. Decide whether to keep Infisical CE as the infra-secrets vault (recommended) and, if a Vault-class HA store is ever wanted, adopt **OpenBao** — never HashiCorp Vault (BSL).

---

## 5. Secrets-domain consolidation recommendation

**Verdict: do NOT consolidate Infisical and Vaultwarden — they are orthogonal, not duplicative.**

- **Infisical CE** (`vault.pazny.eu`, REST/CLI) — the **infra-secrets** vault: machine secrets (DB root passwords, OIDC `client_secret`s, API tokens, encryption keys), managed via REST/CLI, written by the playbook as a *derived projection*.
- **Vaultwarden** (`pass.pazny.eu`) — a Bitwarden-compatible **personal** password manager for human tenants: browser-extension/mobile autofill, per-user master-password-encrypted vaults.
- Different consumers (machines/agents vs humans), different access model (bearer-JWT/CLI vs end-to-end-encrypted user vaults), different threat model. **No overlap.** Both live: `infra-infisical-1` Up, `iiab-vaultwarden-1` Up (healthy).

**How load-bearing is Infisical, really?** It is **mostly a write-only projection**; the runtime *read* path exists but is **dormant**:
- The playbook is a **producer**, not a consumer — `roles/pazny.infisical/files/seed.py` only bootstraps + upserts (PATCH-then-POST), writing Ansible's canonical values **into** Infisical so the dashboard mirrors them. The real source of truth stays `~/.nos/secrets.yml` + `default.credentials.yml`. No playbook task *reads* a runtime secret from Infisical to feed another service.
- Two real runtime consumers exist, neither load-bearing: (a) Wing's `App\Model\InfisicalClient` writes per-user mailbox passwords during the A18 invite flow — a hand-off *share* surface, not a dependency any service reads; `listUserSecrets()` returns key **names** only. (b) AgentKit's `CredentialResolver` resolves `infisical:/path` secret_refs read-only via the CLI — but **every committed `agent.yml` declares bare scopes with no `infisical:` ref**, there is zero seeding into `agent_credentials`/`agent_vaults`, and `pulse-run-agent.sh` injects tokens via process env — so `resolve()` always falls through to the env-var fallback.
- **Net:** removing Infisical would break the *optional* A18 per-user-credential share and disable a *wired-but-unused* agent vault path — it would **not** break any service's boot or any agent's actual runtime auth.

**License caveat — reject HashiCorp Vault, prefer OpenBao:**
- **HashiCorp Vault is BSL-1.1** (since Aug 2023) — **REJECT.** This is the exact precedent nOS already codified for Terraform: ADR-0001 (`docs/adr/0001-opentofu-for-autowiring.md`) and `docs/roadmap-2026q2.md` both state verbatim *"OpenTofu, never Terraform (BSL conflicts)."* CLAUDE.md's vision is explicit: *"Every service is FOSS"* / *"All logic and data run on replicable self-hosted FOSS technologies."* BSL fails that bar (source-available, not OSI-FOSS; converts to MPL only 4 years per-version).
- The FOSS analog is **OpenBao** (MPL-2.0, Linux Foundation) — the Vault fork. If a Vault-class HA secrets engine is ever needed beyond Infisical CE, OpenBao is the FOSS-compliant choice. For now, **Infisical CE is sufficient and recommended** — no migration warranted.

---

## Appendix — probe method (reproducibility)

- **Edge vs origin:** `curl -sk --max-time 10 --resolve <domain>:443:127.0.0.1 https://<domain>/` (origin, bypasses Cloudflare) vs a plain `curl https://<domain>/` (edge). edge-fails-but-origin-OK ⇒ Cloudflare tunnel/DNS/route; both-fail ⇒ origin/app.
- **native_oidc reachability:** probed discovery/token from *inside* the service container (curl TLS-verify-ON, PHP `file_get_contents`, and the service's own HTTP client), plus a real token exchange (`invalid_grant` vs `invalid_client` distinguishes "secret correct" from "secret wrong").
- **forward_auth gating:** a gated route 302-redirects to `auth.pazny.eu`; a 200 with the service's own login page = not gated. Cross-checked against `GET /providers/proxy/` + `GET /outposts/instances/` for provider existence + embedded-outpost attachment.
- **Domains** resolved from `state/tofu-authentik-services.yml` (`external_host`) / role defaults, never guessed.
