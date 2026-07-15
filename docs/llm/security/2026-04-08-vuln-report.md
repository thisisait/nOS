# nOS Vulnerability Scan Addendum — 2026-07-15 (Cycle 16, batch-28)

**Batch:** uptime_kuma, calibreweb, traefik, kiwix, puter · **Probe:** unauthenticated_endpoint_scan
**Outcome:** 1 queue item added (REM-127 traefik **HIGH**); 4 components clean/re-verified (uptime_kuma, calibreweb, kiwix, puter). This ~10-day re-check **overturns Traefik's 2026-07-05 "no advisory after v3.6.21" disposition**: the July-8-2026 release wave (v3.6.22 + v3.6.23) carries an *incomplete-fix* follow-up to CVE-2026-33433 that spoofs identity headers through Traefik's **ForwardAuth** middleware — the exact mechanism nOS's platform-wide Authentik SSO gate relies on.

### ⚠ HIGH — [CVE-2026-54763 + CVE-2026-54764] Traefik — ForwardAuth Underscore-Header Identity Spoofing (incomplete fix of CVE-2026-33433) — MITIGATED (authenticated-insider escalation)
- **Component:** traefik (infra stack, `traefik:v3.6.21`; `default.config.yml` `traefik_image_version` + `roles/pazny.traefik/defaults/main.yml` in sync; edge proxy, always-on)
- **Why this overturns batch-21's "clean":** the 2026-07-05 scan predated the v3.6.22/v3.6.23 wave (released 2026-07-08). CVE-2026-54763's affected range is **v3 ≤ v3.6.21** — the pin sits exactly at the top of the vulnerable range.
- **CVE-2026-54763** (GHSA-x677-9fxg-v5c5, **HIGH** — ForwardAuth base **CVSS 9.1**, BasicAuth/DigestAuth 7.5; fixed **v3.6.22** / v3.7.6 / v2.11.51) — an **incomplete fix** for CVE-2026-33433 (REM-025, resolved). The strip uses Go's `Header.Del` → `textproto.CanonicalMIMEHeaderKey`, which treats `-` as a word separator but **NOT `_`** — so **underscore-variant header names** (`X_authentik_groups`, `X_authentik_username`) survive Traefik's strip and reach the backend, exploitable where the backend normalizes `_`==`-` (**PHP/CGI/WSGI `$_SERVER` → `HTTP_X_AUTHENTIK_*`**, nginx `underscores_in_headers on`, Tomcat, ASGI). nOS **is** in the applicable surface: `roles/pazny.traefik/templates/dynamic/middlewares.yml.j2` defines the `authentik` `forwardAuth` middleware with `trustForwardHeader: true` + `authResponseHeaders` including `X-authentik-username/uid/email/name/groups` — and **`X-authentik-groups` drives the RBAC tier mapping**, so an underscore-spoof is an identity/authorization forgery on the core SSO gate.
- **CVE-2026-54764** (companion, MEDIUM **CVSS 5.8**, fixed v3.6.22) — ForwardAuth `X-Forwarded-Proto: https` injection over plain HTTP → Traefik forwards `X-Forwarded-Port: 443` to the auth service, bypassing port-based authorization checks. Same `trustForwardHeader: true` surface.
- **N/A (recorded for lineage):**
  - **GHSA-cxjq-mrr5-89rv** (HIGH **7.8**, ReplacePathRegex auth-bypass via post-replacement path traversal, no CVE, fixed v3.6.23) — **grep-confirmed nOS uses NO `ReplacePathRegex`/`replacePath` middleware anywhere** (Traefik middlewares are `authentik` forwardAuth + `security-headers` + `https-redirect` + `compress` + `wing-edge` + optional `miniflux` `redirectRegex`).
  - **GHSA-42cj-m3vj-89wv** (CRD IngressRouteTCP ServersTransport cross-provider bypass) + **GHSA-qq9q-x9w4-chhj / GHSA-6p8f-p8j2-rqmv** (Gateway API HTTPRoute namespace confusion) — **Kubernetes CRD/Gateway-provider ONLY**, N/A to nOS (Docker provider + file provider, no K8s Gateway/CRD).
- **PROBE result (unauth_endpoint_scan):** the forwardAuth flow only **adds** `authResponseHeaders` **after** Authentik auth passes and does **not** forward to the backend on auth failure → the underscore-spoof is **not a pure-unauth bypass**; a session must first clear the Authentik wall. **Residual:** (a) the forward_auth pure-gate services (Uptime Kuma, Calibre-Web, Kiwix, Puter, code-server, ntfy, Metabase, …) read **no** `X-authentik-*` identity header → spoof is inert; (b) the **header_oidc** services that **do** consume per-user headers — **Firefly III** (PHP, `HTTP_X_AUTHENTIK_USERNAME` → underscore collides) + **KEAP** (`X-Authentik-uid`) — are the genuine target: an **authenticated low-priv Tier user** could inject `X_authentik_groups: nos-admins` / `X_authentik_username: <victim>` to escalate or impersonate. SEC-02 network isolation does **not** cover this (edge path, not peer-container). **MITIGATED** to authenticated-insider escalation, not internet-anon.
- **Remediation:** bump `traefik_image_version` **v3.6.21 → v3.6.23** in `default.config.yml` **and** `roles/pazny.traefik/defaults/main.yml` together (version-pin-shadow rule). v3.6.23 is the latest 3.6 patch and clears CVE-2026-54763 + CVE-2026-54764 (at v3.6.22) plus the N/A ReplacePathRegex GHSA-cxjq (at v3.6.23), **no config change**. → **REM-127**
- **Source:** https://github.com/traefik/traefik/security/advisories/GHSA-x677-9fxg-v5c5 · https://www.tenable.com/cve/CVE-2026-54764 · https://github.com/traefik/traefik/security/advisories/GHSA-cxjq-mrr5-89rv · https://github.com/traefik/traefik/security

### Covered / not-applicable / re-verified this batch (no item)
- **uptime_kuma** (`louislam/uptime-kuma:1.23.13`, 1.x line): **CLEAN/re-verified.** No CVE affecting the 1.x line published after the 2026-06-24 baseline. REM-073 (CVE-2026-33130 SSTI arbitrary file read, fix only in breaking 2.2.1), REM-037, REM-044 remain the open items; the 2026 unauth advisories (CVE-2026-32230 ping-badge / GHSA-5px6 file-read / GHSA-2qgm LFI) stay **2.x-only** → N/A. `127.0.0.1:3001` loopback + `traefik_auth_modes.uptime_kuma='proxy'` forward-auth + internal login disabled → nothing anonymously reachable. Reads no `X-authentik-*` identity header → the REM-127 underscore-spoof is inert here.
- **calibreweb** (`lscr.io/linuxserver/calibre-web:0.6.26`): **CLEAN of new.** REM-120 (CVE-2026-7709 Kobo-token IDOR) + REM-074 (CVE-2025-6998 login ReDoS) stay pending/mitigated. Ruled out as non-calibre-web: **CVE-2026-11645** (Google Chrome V8) + CVE-2026-7713 (the Calibre-Web-Automated **fork**, already the noted fix path v4.0.7). `traefik_auth_modes.calibre_web='proxy'` forward-auth + `127.0.0.1:8083` loopback + `gated_net` only (SEC-02) + Tier 3. Forward_auth pure-gate → REM-127 inert.
- **kiwix** (`ghcr.io/kiwix/kiwix-serve:3.8.2`): **CLEAN/re-verified.** No HIGH/CRITICAL CVE in the 12-mo window — kiwix-tools/overview/desktop advisories empty; the surfaced `CVE-2026-58402` carries no product detail on cve.org and does not map to Kiwix. `traefik_auth_modes.kiwix='proxy'` forward-auth + `127.0.0.1:8888` loopback + Tier 4. Reads no identity header → REM-127 inert.
- **puter** (local build `nos/puter` FROM `ghcr.io/heyputer/puter:latest`): **REM-108 (LOW) stays pending, re-verified.** Still CVE-clean (HeyPuter/puter advisories empty; no OSV/NVD hit). Floating upstream base tag = supply-chain hygiene (same class as woodpecker `v3`/paperclip sha/tileserver `latest`); fix = pin `FROM` to an immutable `tag@sha256`. `traefik_auth_modes.puter='proxy'` forward-auth + `127.0.0.1:5050` loopback + Tier 3; `/healthcheck` public but loopback/behind-Authentik only. Reads no identity header → REM-127 inert.

---

# nOS Vulnerability Scan Addendum — 2026-07-04 (Cycle 16, batch-16)

**Batch:** freescout, woodpecker, jellyfin, uptime_kuma, calibreweb · **Probe:** unauthenticated_endpoint_scan
**Outcome:** 3 queue items added (REM-118 freescout **CRITICAL**, REM-119 jellyfin HIGH, REM-120 calibreweb MEDIUM); 2 components clean/re-verified (woodpecker, uptime_kuma). This ~10-day re-check of the batch-4/batch-5 components **overturns two prior "clean" dispositions**: FreeScout's four-CVE June cluster (CVE IDs assigned *after* the app version the pin bundles) and a coverage gap on Calibre-Web. FreeScout is the standout — an **unauthenticated CRITICAL admin takeover** that hits nOS's exact MariaDB backend and is reachable through the edge route.

### 🔴 CRITICAL — [CVE-2026-53595 + 53593 + 53591 + 48812] FreeScout — June-2026 Four-CVE Cluster → Unauthenticated Admin Takeover on MariaDB — EXPLOITABLE (edge-routed)
- **Component:** freescout (b2b stack, `tiredofit/freescout` build `php8.3-1.17.159` bundling **FreeScout app 1.8.219**; `default.config.yml` + `roles/pazny.freescout/defaults/main.yml` in sync; `install_freescout` default-on)
- **Why this overturns batch-4's "clean":** the prior scan (2026-06-23) predated these advisories' CVE assignments. All four are fixed in versions **above** the 1.8.219 the pin bundles.
- **Cluster:**
  - **CVE-2026-53595** (GHSA-jqj5-r72v-v29g, **CRITICAL CVSS 9.4**) — **UNAUTHENTICATED** account takeover on MySQL/MariaDB: a `%20`/empty-string `invite_hash` collision at `/user-setup` plus a graceful-fail expiry check lets an anonymous attacker reset **any** agent/admin email+password → full mailbox + customer-data access. **nOS runs MariaDB — the exact vulnerable configuration.** Fix **1.8.224**.
  - **CVE-2026-53593** (GHSA-27vp-fpg8-j8wv, HIGH **8.8**) — authenticated RCE via `.pht` upload; an incomplete denylist bypasses the CVE-2025-48471 fix and executes as PHP on the image's Apache mod_php. Any low-priv agent. Fix **1.8.224**.
  - **CVE-2026-53591** (GHSA-8vm3-wwq4-ggfx, HIGH **8.6**) — **UNAUTHENTICATED** conversation-thread injection: HMAC verified only when the hash is exactly 16 chars, so any other length bypasses → forge customer replies + reopen closed tickets via crafted `In-Reply-To` + guessed sequential thread ID. Fix **1.8.223**.
  - **CVE-2026-48812** (GHSA-wg74-ww4w-2qpc, HIGH **7.5**) — **UNAUTHENTICATED** legacy-attachment access in `routes/open.php` (broken AND-condition token check) → enumerate/download any legacy attachment by sequential ID. Fix **1.8.221**.
  - (Subsumed by the bump: GHSA-6r38-6mcf-2ww3 agent-impersonation HMAC, HIGH, fix 1.8.220.)
- **PROBE result (unauth_endpoint_scan):** **three of the four legs are unauthenticated** and hit `/user-setup`, the inbound-email/thread path, and `routes/open.php` — all anonymously reachable at the `helpdesk.<tld>` route because `traefik_auth_modes.freescout='oidc'` (native OIDC, **200 at edge, NOT forward-auth gated**). `127.0.0.1:8090` loopback blocks direct host access but not the edge route; `services_lan_access=false` by default. **EXPLOITABLE** for any operator with the b2b stack enabled.
- **Remediation:** bump `freescout_version` to a tiredofit build bundling **FreeScout ≥ 1.8.224** (confirmed builds: `2.1.1`→1.8.224 … `2.1.3`→1.8.226) in `default.config.yml` **and** the role default together (version-pin-shadow rule). **Not a plain tag swap** — the upstream image renamed `php8.3-1.17.x`→`2.x.x` and `2.1.1` deprecates `SITE_URL`→`APP_URL`, which the compose template (`roles/pazny.freescout/templates/compose.yml.j2`) still sets; verify the arm64 manifest + build→app map via the nfrastack CHANGELOG (same method as REM-069). Strongly consider flipping `traefik_auth_modes.freescout`→`'proxy'` (forward-auth) as defense-in-depth. → **REM-118**
- **Source:** https://github.com/freescout-help-desk/freescout/security/advisories/GHSA-jqj5-r72v-v29g · https://github.com/freescout-help-desk/freescout/security/advisories/GHSA-27vp-fpg8-j8wv · https://github.com/freescout-help-desk/freescout/security/advisories/GHSA-8vm3-wwq4-ggfx · https://github.com/freescout-help-desk/freescout/security/advisories/GHSA-wg74-ww4w-2qpc · https://github.com/tiredofit/docker-freescout/releases

### ⚠ HIGH — [CVE-2026-48793] Jellyfin — Unauthenticated FFmpeg Argument-Injection in Subtitle Path
- **Component:** jellyfin (iiab stack, `jellyfin/jellyfin:10.11.8`, `install_jellyfin=false` default; `default.config.yml` + role default in sync)
- **CVE-2026-48793** (GHSA-wwwm-px48-fpvq, HIGH **8.8**, CWE-88) — FFmpeg **argument-injection** in `SubtitleEncoder.ConvertTextSubtitleToSrtInternal`; subtitle file paths are interpolated into the FFmpeg command line unsanitized, and on Linux a double-quote in a filename injects arguments → arbitrary file write + info disclosure. Reachable **without authentication** via `SubtitleController.GetSubtitle` (no `Authorize` attribute). Advisory: **all releases prior to 10.11.10 are vulnerable.** **Distinct** from the already-covered CVE-2026-35031 (subtitle *path-traversal* RCE, fix 10.11.7) — same subsystem, different flaw, three patches later.
- **Companion (fix 10.11.10, no CVE):** a jellyfin-web list-view XSS (PR #7955) ships in the client bundled at 10.11.8 (MEDIUM confidence).
- **Already covered by 10.11.8 (no action):** CVE-2026-35033 (CRITICAL 9.3, unauth arbitrary file read via `StreamOptions` FFmpeg arg-injection, fix 10.11.7).
- **PROBE result:** the role default `jellyfin_lan_access=true` → binds `0.0.0.0:8096` (LAN-exposed, **not** loopback) when enabled; `install_jellyfin=false` keeps the fleet baseline off, but any tenant that enables it exposes a LAN-reachable **unauthenticated** FFmpeg arg-injection endpoint on a vulnerable pin — `traefik_auth_modes.jellyfin='oidc'` (9p4 SSO-Auth plugin) does **not** protect the raw `:8096` port. **EXPLOITABLE-when-enabled.**
- **Remediation:** bump `jellyfin_version` **10.11.8 → 10.11.10** (or 10.11.11) in `default.config.yml:~1529` **and** `roles/pazny.jellyfin/defaults/main.yml:~10` (version-pin-shadow); SSO-Auth plugin `4.0.0.4` stays ABI-compatible within 10.11.x. → **REM-119**
- **Source:** https://github.com/jellyfin/jellyfin/security/advisories/GHSA-wwwm-px48-fpvq · https://nvd.nist.gov/vuln/detail/CVE-2026-48793 · https://nvd.nist.gov/vuln/detail/CVE-2026-35033

### Covered / not-applicable / gap-fill this batch
- **calibreweb** (`lscr.io/linuxserver/calibre-web:0.6.26`): **+REM-120 (MEDIUM), coverage-gap fill.** **CVE-2026-7709** (NVD 6.3; VulDB mislabels "critical") — Kobo-token IDOR (CWE-285) in `generate_auth_token` (`cps/kobo_auth.py`): an authenticated low-priv user requests another user's Kobo sync auth-token by changing `user_id` → account impersonation. Affects janeczku 0.6.0–0.6.26 (pin 0.6.26 in-window, high confidence). This is the janeczku **web app**, NOT desktop Calibre (CVE-2026-26064/25635/27810 = the Kovid-Goyal product, correctly excluded). **No janeczku fix** (upstream dormant); the fix path is migration to the Calibre-Web-Automated fork (v4.0.7). Published 2026-05-03 but never tracked = prior-scan gap, now closed. **Mitigated:** `traefik_auth_modes.calibre_web='proxy'` forward-auth wall + `127.0.0.1:8083` loopback + `gated_net` only (SEC-02) + Tier 3 → the IDOR requires an authenticated session behind the Authentik SSO wall (insider-scoped). REM-074 re-verified.
- **woodpecker** (effective floating `v3` → latest **3.16.0**): **CLEAN/re-verified.** The only new HIGH, **GHSA-qf34-295c-26v8** (unrestricted `serviceAccountName` → pipeline-pod priv-esc/secret-exfil, published 2026-07-01, fix 3.16.0) is **Kubernetes-backend-ONLY** → N/A to nOS's `WOODPECKER_BACKEND=docker`. REM-105 (CVE-2026-50141 gRPC agent_id, fix 3.14.1) stays covered; 3.15/3.16 add follow-on hardening on that path. REM-002 unchanged. Both ports `127.0.0.1` loopback + forward_auth + Gitea OAuth2; `/metrics` bearer-gated. Standing (not new): anchor the floating `v3`→explicit `v3.16.0`.
- **uptime_kuma** (`louislam/uptime-kuma:1.23.13`, 1.x line): **CLEAN/re-verified.** No CVE affecting the 1.x line published after 2026-06-24 (newest advisory is 2026-04-02). REM-073 (CVE-2026-33130 SSTI, fix only in breaking 2.2.1), REM-037, REM-044 remain the open items; the 2026 unauth advisories (CVE-2026-32230 ping-badge / GHSA-5px6 file-read) stay 2.x-only → N/A. `127.0.0.1:3001` loopback + `traefik_auth_modes.uptime_kuma='proxy'` forward-auth (gates all routes incl. badges) + internal login disabled → nothing anonymously reachable.

---

# nOS Vulnerability Scan Addendum — 2026-07-01 (Cycle 16, batch-11)

**Batch:** rustfs, qgis_server, nginx, vaultwarden, ollama · **Probe:** unauthenticated_endpoint_scan
**Outcome:** 1 queue item added (REM-116, rustfs) + REM-093 fix target advanced (alpha.98 → beta.9, superseded). **4 of 5 components are CLEAN/covered or already-tracked** (qgis_server clean; nginx REM-098 unchanged; vaultwarden REM-095 resolved; ollama REM-096 resolved). The one new item carries a **CRITICAL** advisory leg (an *incomplete-fix* stored XSS) whose reach is amplified because the RustFS console is `auth: none` — but the S3/admin API is loopback-only and the FTP/replication legs are unconfigured by default.

### ⚠ [CVE-2026-55188 / 55189 / 49991 / 55838 + GHSA-7gcx-wg4x-q9x6] RustFS — June-2026 Beta-Line Cluster (CRITICAL in cluster) — REM-093 target now stale, real fix is 1.0.0-beta.9
- **Component:** rustfs (iiab stack, `rustfs/rustfs:1.0.0-alpha.93`, S3+admin API 127.0.0.1:9010 loopback, console 9001 Traefik-routed at `traefik_auth_modes['rustfs']='none'`, **`install_rustfs=true` — default ON**)
- **Timing:** the cluster was **published 2026-06-27 / 2026-06-29**, *after* the 2026-06-20 REM-093 scan, and is fixed **only in the new `1.0.0-beta` release line** — so the pinned **alpha.93 *and* REM-093's alpha.98 target are both affected**. REM-093's `fix_version` is advanced **alpha.98 → 1.0.0-beta.9** (superseded-note added); **REM-116** carries the detail.
- **Cluster:**
  - **CVE-2026-55188** (HIGH **8.2**, GHSA-796f-j7xp-hwf4) — `ListRemoteTargetHandler` checks only that credentials *exist*, not that the caller has replication/admin permission → any authenticated no-permission user lists a bucket's remote replication targets, and the returned `BucketTarget` objects **include the remote access + secret keys** (credential disclosure). Fix beta.9.
  - **CVE-2026-49991** (HIGH **8.6**, GHSA-f4vq-9ffr-m8m3) — Snowball auto-extract **path traversal**: an authed user with only `PutObject` on their own bucket injects objects **across bucket boundaries** (multi-tenant isolation break). Fix beta line (>beta.4).
  - **CVE-2026-55189** (HIGH **7.7**, GHSA-3g29-xff2-92vp) — FTP frontend `RETR/SIZE/MDTM/CWD` skip the IAM authorization call → any FTP-authenticated user (even with an explicit `Deny` on `s3:GetObject`) reads/stats/probes **any object in any bucket**. Fix beta.9. **Latent** — nOS does not enable the FTP frontend by default.
  - **CVE-2026-55838** (MEDIUM **4.3**, GHSA-f5cv-v44x-2xgf) — `/rustfs/admin/v3/metrics` skips `validate_admin_request` → any IAM user reads server-wide operational metrics. Fix beta.7/beta.9.
  - **GHSA-7gcx-wg4x-q9x6** (**CRITICAL**) — *"Incomplete fix: Critical Stored XSS in Preview Modal"*: the earlier **CVE-2026-27822** console preview-modal stored XSS (nominally covered at its alpha.83 fix) had an **incomplete fix**; the complete fix is only in the beta line.
- **PROBE result (unauth_endpoint_scan):** the genuinely-**unauthenticated** leg remains **CVE-2026-40937** (REM-093, notification-target webhook config). The rest of the June cluster is **authenticated** (FTP/IAM) — **except** the **stored XSS**, which is **probe-relevant**: the console (9001) is the *only* Traefik-routed RustFS surface and its router is `auth: none` (no `authentik@file`), so it leans entirely on RustFS's own beta-grade login. A stored XSS firing in the console context steals the S3 admin keys from `localStorage` → **full console/account takeover** — sharpened by `install_rustfs=true`.
- **Mitigated:** the S3 + admin API (`RUSTFS_ACCESS_KEY/SECRET`) binds **127.0.0.1:9010** loopback / Docker `shared_net` only (not external); only the console is edge-routed; **FTP frontend + bucket replication are unconfigured by default** (55189 + 55188 latent).
- **Remediation:** bump `rustfs_version` **1.0.0-alpha.93 → 1.0.0-beta.9** (`default.config.yml` source-of-truth + mirror `roles/pazny.rustfs/defaults/main.yml`, version-pin-shadow rule) — clears the whole June cluster and supersedes the alpha.98 target with margin; **also** flip `traefik_auth_modes['rustfs']` → `'proxy'` (authentik@file forward-auth in front of the console) as defense-in-depth against the console-XSS class. → **REM-116** (supersedes/extends REM-093)
- **Recorded for lineage** (already covered by alpha.93 at their alpha.83 fix): **CVE-2026-27822** (Critical console stored XSS — but the *complete* fix needs beta.9) + **CVE-2026-27607** (presigned POST-policy validation bypass → arbitrary object write + content-length/content-type-constraint bypass).
- **Source:** https://github.com/rustfs/rustfs/security/advisories/GHSA-796f-j7xp-hwf4 · https://github.com/rustfs/rustfs/security/advisories/GHSA-f4vq-9ffr-m8m3 · https://cve.threatint.eu/CVE/CVE-2026-55189 · https://cve.threatint.eu/CVE/CVE-2026-55838 · https://github.com/rustfs/rustfs/security · https://app.opencve.io/cve/?vendor=rustfs

### Covered / not-applicable this batch (no item)
- **qgis_server** (`kartoza/qgis-server`, 127.0.0.1:8071, `install_qgis_server=false`): **CLEAN, re-verified** — no HIGH/CRITICAL **QGIS Server** CVE in the 12-mo window. The 2026 **GeoServer** cluster (**CVE-2025-58360** unauth WMS-GetMap XXE — actively exploited, CISA-KEV Dec-2025; **CVE-2024-36401** OGC RCE) is a **different product** → N/A; **CVE-2025-11183** (XSS) is the **QWC2 web client** (not deployed; nOS runs the kartoza qgis-server OGC backend only). Probe: `traefik_auth_modes['qgis_server']='proxy'` (authentik@file forward-auth gates WMS/WFS) + 127.0.0.1:8071 loopback + `install_qgis_server=false`.
- **nginx** (HOST package, `install_nginx=false` default): **REM-098 stays pending** — the 2026 rewrite-module / HTTP-3 cluster (**CVE-2026-42945** "NGINX Rift" CVSSv4 9.2 actively exploited + **CVE-2026-42530 / 42055 / 9256**), operator-side `brew`/`apt upgrade nginx` to **≥ 1.31.2**. **NEW this batch, N/A:** **CVE-2026-8711** (njs `ngx_http_js_module` heap overflow via `js_fetch_proxy` + `ngx.fetch()`, unauth, fix njs 0.9.9) — grep-confirmed nOS nginx loads **no `njs`/`js_module`/`load_module`** and uses no `js_fetch_proxy`/`ngx.fetch` (module not compiled/enabled; same disposition class as the REM-063 DAV/MP4 modules). HTTP/3 not enabled; `server_tokens off`.
- **vaultwarden** (`vaultwarden/server:1.35.8`, 127.0.0.1:8062, native_oidc Tier-3): **REM-095 stays resolved** — 1.35.8 covers CVE-2026-27802/27898/43911 **and** the additionally-surfaced **CVE-2026-26012** (org-cipher read, fix 1.35.3) + **CVE-2026-27801** (2FA/OTP brute-force bypass, post-password) + **CVE-2026-27803** (manager priv-esc, fix 1.35.4) — all ≤ 1.35.5, all authenticated/cross-user (not unauth-relevant). `SIGNUPS_ALLOWED=false`. No CVE past 1.35.8 in the window.
- **ollama** (host Homebrew, 127.0.0.1:11434): **REM-096 stays resolved** — **CVE-2026-7482** "Bleeding Llama" (CVSS 9.1, unauth GGUF OOB-read via `/api/create`, fix 0.17.1) mitigated by host `state=latest` floating past 0.17.1 + loopback bind (no `OLLAMA_HOST=0.0.0.0`). No newer Ollama CVE in the window. **REM-024** (host-install brew-currency + `OLLAMA_HOST` hardening) remains the standing pending host-side item.

---

# nOS Vulnerability Scan Addendum — 2026-06-30 (Cycle 16, batch-10)

**Batch:** postgresql, postgres, erpnext, homeassistant, bluesky_pds · **Probe:** unauthenticated_endpoint_scan
**Outcome:** 1 queue item added (REM-115, erpnext). **2 of 5 components are CLEAN/covered (postgresql/postgres, bluesky_pds), 1 already-tracked (homeassistant/REM-094).** The probe found **no new anonymously-reachable surface** — the one new finding is *authenticated-only* and the two databases expose no HTTP endpoint.

### ⚠ [CVE-2026-44446 / CVE-2026-44442 / CVE-2026-44447] ERPNext — May-2026 SQLi + Authz-Bypass Cluster (CRIT 9.9 in cluster) — version-flagged, authenticated-only, hard-blocked
- **Component:** erpnext (b2b stack, `frappe/erpnext:v15.98.1`, 127.0.0.1:8082, native-OIDC route, `install_erpnext=false` **and** hard-blocked at role-load behind `erpnext_experimental_override=true`)
- **Confirmed v15-affecting headline:** **CVE-2026-44446** (HIGH, CWE-89 SQL injection via missing input validation) has a **dual-line fix in ERPNext 15.104.3 *and* 16.14.0** — the pinned **v15.98.1 < 15.104.3**, so the pin is squarely in the affected window (**high** confidence).
- **Broader cluster** (github.com/frappe/erpnext/security/advisories): **CVE-2026-44442** (GHSA-cg5w-7g26-p3w9, **CRITICAL CVSS 9.9** — authorization bypass; a low-priv authenticated user modifies data outside their assigned role because certain API endpoints skip permission checks; advisory cites fix **16.9.1**) + **CVE-2026-44447** (GHSA-q65v-fm9p-9vh3, HIGH **8.8** SQLi, fix **16.9.0**) + the HIGH SQLi/XSS set (GHSA-6fm9-g88m-hxr7 / GHSA-j669-ghv2-gmqg / GHSA-wj7p-g62h-jh38 SQLi; GHSA-r99h-h44m-89m2 stored XSS in Dashboards/Tools/Portals) and the MODERATE set (GHSA-mhm9-75w7-423r EDI-module XXE → authed local file read, GHSA-6ffr-92hr-3394 path-traversal, GHSA-m4m4-j2m2-7fcw authed SSRF, GHSA-444j-g95x-5pqv doc-modification). The 44442/44447 advisory metadata cites only **v16** fix versions, so their exact v15 backport release is **medium** confidence — but the dual-line CVE-2026-44446 already proves the pin is vulnerable.
- **PROBE result (unauth_endpoint_scan):** **every** item in the cluster requires **authentication (low-priv)** — **none is unauthenticated**, so this is *not* a new unauth-endpoint exposure. The prior *unauthenticated* ERPNext item **CVE-2026-27471** (CVSS 9.3 unauth doc access) stays **resolved** at v15.98.1 via REM-017; ERPNext's only intentionally-public surface remains its own login + `/api/method/frappe.ping` health.
- **Mitigated beyond auth:** `install_erpnext=false` **and** hard-blocked at role-load (requires `erpnext_experimental_override=true` — the strongest perimeter gate in the fleet) → **zero live exposure**; 127.0.0.1:8082 loopback; native-OIDC.
- **Remediation:** bump `erpnext_version` **v15.98.1 → v15.104.3** (latest v15.x stable; clears the confirmed v15 SQLi backport) in `default.config.yml` **and** `roles/pazny.erpnext/defaults/main.yml` together (version-pin-shadow rule). Lands as an acceptance criterion of the deferred ERPNext rework (REM-008). → **REM-115**
- **Source:** https://github.com/frappe/erpnext/security/advisories/GHSA-cg5w-7g26-p3w9 (CVE-2026-44442) · https://github.com/frappe/erpnext/security/advisories/GHSA-q65v-fm9p-9vh3 (CVE-2026-44447) · https://www.thehackerwire.com/erpnext-critical-authorization-bypass-cve-2026-44442/ · https://www.thehackerwire.com/erpnext-sql-injection-cve-2026-44447/ · https://app.opencve.io/cve/?vendor=frappe

### Covered / not-applicable this batch (no item)
- **postgresql / postgres** (`postgres:16.14-alpine`): **COVERED/CLEAN** — the pin has **advanced 16.13 → 16.14**, satisfying the orphaned phantom `REM-088` (16.13→16.14 bump) debt structurally (no queue item needed). The **entire May-14-2026 PostgreSQL release** is fixed in 16.14: CVE-2026-6472 (5.4), **CVE-2026-6473** (8.8 integer-wraparound OOB write, authed), CVE-2026-6474 (4.3 timeofday mem-disclosure), CVE-2026-6475 (8.8 pg_basebackup symlink-follow), CVE-2026-6477 (8.8 libpq lo_* client-stack overwrite), CVE-2026-6478 (6.5 MD5 timing — *N/A*, nOS uses scram-sha-256), **CVE-2026-6479** (7.5 SSL/GSS-negotiation DoS — the **only unauthenticated/network-reachable** leg, **fixed**), CVE-2026-6637 (8.8 refint overflow+SQLi), CVE-2026-6638 (3.7). 127.0.0.1:5432 loopback + internal `infra_net`, password auth, **no HTTP endpoint** → no external unauth surface regardless. 16.14 is the latest 16.x (PG 18.4/17.10/16.14/15.18/14.23 cohort); next release Aug 2026.
- **homeassistant** (`ghcr.io/home-assistant/home-assistant:2026.4`): **REM-094 stays pending** — **CVE-2026-54317** (HIGH 7.6, Konnected alarm-panel state/topology disclosed to **unauthenticated LAN** actors, fix Core **2026.6.0**; pin 2026.4 affected). Re-verified: **no Core CVE newer than 2026.6.0**, bump target unchanged. The two new June-2026 advisories are **mobile-app only → N/A to the Core server image**: CVE-2026-55844 (HIGH 7.5, iOS Companion SSID-allowlist bypass, fix iOS 2026.5.0) + CVE-2026-54318 (HIGH 7.1, Android BroadcastReceiver spoofing, fix Android 2026.5.3). `install_homeassistant=false` + 127.0.0.1:8123 + native-OIDC.
- **bluesky_pds** (`ghcr.io/bluesky-social/pds`, atproto PDS): **no verified CVE** in the 12-mo window — no GitHub/NVD/OSV advisory; the qwell/bsky-exploits researcher disclosures carry no CVE; the 2026-04-15 Bluesky outage was a **DDoS incident**, not a code CVE in the PDS image. Probe: **no Traefik router** (manifest has no `domain_var`, so no edge route), 127.0.0.1:2583 loopback, `PDS_INVITE_REQUIRED=true`; `/xrpc/_health` + `com.atproto.server.describeServer` are intentionally-public AT Protocol endpoints. Mitigated at the perimeter.

---

# nOS Vulnerability Scan Addendum — 2026-06-29 (Cycle 16, batch-9)

**Batch:** mailpit, spacetimedb, gitlab, wordpress, freepbx · **Probe:** unauthenticated_endpoint_scan
**Outcome:** 4 queue items added (REM-111…114). **1 of 5 components is fully clean (spacetimedb).** No new item is anonymously edge-reachable *right now* — every live leg is gated by `install=false` + loopback + forward-auth/native-OIDC — but three carry an *unauthenticated-by-design* surface, and one CRITICAL (vendor-blocked) is re-recorded.

> **Data-integrity note:** the prior-batch `scan-state.json` notes for these components referenced **REM-088…092**, which were **never persisted** to `remediation-queue.json` (a gap between REM-087 and REM-093). This batch re-persists the gitlab / wordpress / freepbx findings at fresh monotonic IDs (the append-only convention every batch since REM-093 has followed) — **REM-111 supersedes phantom REM-091**, **REM-114 supersedes phantom REM-090 + REM-092**, **REM-113 supersedes phantom REM-089** — and the rewritten component notes now point to the real IDs. The orphaned postgresql `REM-088` ref (16.14 bump, out of this batch's scope) is left untouched.

### ⚠ CRITICAL — [CVE-2026-46376] FreePBX — Hard-Coded `userman` Credentials → Unauthenticated UCP Access — VENDOR-BLOCKED
- **Component:** freepbx (voip stack, `tiredofit/freepbx:latest` — abandoned image, `roles/pazny.freepbx`)
- **Impact:** CVSS **9.3**. The FreePBX `userman` module ships **static sample credentials** with the optional generic-template setup; if not manually changed they stay active, letting an **unauthenticated remote attacker** log into the User Control Panel (UCP) to read/modify communication settings. Fixed by updating `userman` to **16.0.45 / 17.0.7** (introduces password randomization).
- **Why VENDOR-BLOCKED:** the `tiredofit/freepbx` image's last published tag is **5.2.0 (2022-04-30, upstream abandoned)** — there is no path to `userman` 16.0.45/17.0.7 in this image, and no maintained ARM64 FOSS alternative. Joins **REM-014** (CVE-2025-57819 pre-auth RCE) + REM-046 as structurally unfixable here.
- **Mitigated at the nOS perimeter:** `install_freepbx=false` (off by default), the manifest entry carries `port_var` but **no `domain_var`** → FreePBX is **not Traefik-routed** (no edge route), and the web UI host-maps to **127.0.0.1:8088 loopback** (SIP/IAX/RTP bind beyond loopback only when `freepbx_lan_access=true`). Operators who enable freepbx accept the documented risk. → **REM-113**
- **Source:** https://ccb.belgium.be/advisories/warning-critical-vulnerability-freepbx-allows-unauthenticated-attacker-gain-access · https://github.com/FreePBX/security-reporting/security/advisories · https://app.opencve.io/cve/?vendor=freepbx

### ⚠ UNAUTH — [CVE-2026-10712] GitLab CE — Web IDE Asset-Handler Path-Validation XSS (HIGH) — version-flagged, mitigated
- **Component:** gitlab (devops stack, `gitlab/gitlab-ce:18.10.8-ce.0`, 127.0.0.1:8929, native_oidc Traefik route)
- **Impact:** the **June-24-2026** GitLab release (19.1.1 / 19.0.3 / **18.11.6**) version-flags our pin. The CE-affecting + **unauthenticated** headline is **CVE-2026-10712** (HIGH **8.0**) — stored XSS in the Web IDE workbench asset handler via improper path validation; affects **CE/EE 18.10+ before 18.11.6**, and the fix was **not backported to the 18.10 line** (no 18.10.x patch issued) so **18.10.8-ce.0 is exposed**.
- **Companion CE-affecting cluster (also fix-only-in-18.11.6):** CVE-2026-2238 (MED 5.3, Rapid Diffs improper-authz → confidential issue references, unauth), CVE-2026-8330 (MED 4.4, CI/CD API log leak), CVE-2026-1606 (MED 4.3, Snippets), CVE-2026-5952 (MED 4.3, Maven registry protection-rule bypass), CVE-2026-5796 (MED 4.3, group packages API), CVE-2026-12635 (LOW 3.1, repo-mirror SSRF).
- **Not applicable (Enterprise/Premium/Ultimate-only, CE unaffected):** CVE-2026-10086 (8.7), CVE-2026-12053 (7.7 Duo Workflows), CVE-2026-5309 (5.4), CVE-2026-11379 (5.3), CVE-2026-0934 (3.8), CVE-2026-3176 (3.1).
- **Mitigated:** `install_gitlab=false` (off by default), `traefik_auth_modes.gitlab=oidc` (native OIDC — GitLab owns its login, the Web IDE is behind app auth), signup disabled, 127.0.0.1:8929 loopback.
- **Remediation:** bump `gitlab_version` **18.10.8-ce.0 → 18.11.6-ce.0** (min safe; 19.1.1 is latest, larger migration) in `default.config.yml` **and** `roles/pazny.gitlab/defaults/main.yml` together (version-pin-shadow rule). → **REM-111**
- **Source:** https://docs.gitlab.com/releases/patches/patch-release-gitlab-19-1-1-released/ · https://about.gitlab.com/releases/categories/releases/

### [CVE-2026-55187] Mailpit — Incomplete IPv6 SSRF Protection + JSON-DoS (MEDIUM) — mitigated by forward-auth + loopback
- **Component:** mailpit (iiab stack, `axllent/mailpit:v1.30.0`, **`install_mailpit=true` — default ON**, `proxy` forward-auth route, 127.0.0.1:8025/1025)
- **Impact:** the pinned **v1.30.0** is version-flagged by a *post-v1.30.0* cluster: **CVE-2026-55187** (GHSA-w4mc-hhc6-xp28, Moderate) — incomplete SSRF protection in `tools.IsInternalIP()` that misses IPv6 transition/mapped forms, so Link Check / HTML Check can still be steered at internal services (affected v1.29.2…≤1.30.1, **fix 1.30.2**); plus **GHSA-28pq-6qxg-wg5r** (unbounded-JSON memory-exhaustion DoS, **fix 1.30.1**) and the **v1.30.3** (2026-06-27) link-check rate-limit hardening.
- **Already covered (no exposure):** the **HIGH unauthenticated** **CVE-2026-45713** (GHSA-fpxj-m5q8-fphw — OOM via arbitrarily large emails over SMTP/HTTP, affected `<1.29.8`) is **fixed in v1.30.0**. REM-081…085 (Jan/Feb SSRF/CSWSH/header-injection) remain resolved.
- **Why mitigated despite default-on:** `traefik_auth_modes.mailpit=proxy` (authentik@file forward-auth gates the UI + Link/HTML Check + JSON API at `mail.<tld>`) + the container host-maps only to **127.0.0.1:8025** (UI/REST) and **127.0.0.1:1025** (SMTP) loopback → the SSRF and JSON-DoS HTTP endpoints are **not anonymously edge-reachable**; residual is the loopback SMTP ingestion path (already DoS-fixed in 1.30.0).
- **Remediation:** bump `mailpit_version` **v1.30.0 → v1.30.3** (latest) in `roles/pazny.mailpit/defaults/main.yml`. → **REM-112**
- **Source:** https://github.com/axllent/mailpit/security/advisories/GHSA-w4mc-hhc6-xp28 · https://github.com/axllent/mailpit/security/advisories/GHSA-28pq-6qxg-wg5r · https://github.com/axllent/mailpit/releases

### [PROBE] WordPress — Unhardened Public Unauth Endpoints (MEDIUM) — core CVE-clean, defense-in-depth pending
- **Component:** wordpress (iiab stack, `wordpress:6.9.4-php8.3-apache`, 127.0.0.1:8084, native_oidc route, `install_wordpress=false`)
- **Core is CVE-clean at 6.9.4:** CVE-2026-3906 (Notes-feature REST authz bypass, Subscriber-auth) and the full emergency March-2026 cluster (6.9.2/6.9.3/6.9.4 — PclZip path traversal, getID3 XXE, nav-menu stored XSS, AJAX authz bypass, CVE-2026-3901 blind SSRF) are **all fixed in 6.9.4**, all require authentication, and **6.9.4 is the latest core security release** (no 6.9.5/6.10 core CVE in the window).
- **Standing finding (not a core CVE):** the intentionally-public CMS surface is unhardened — `xmlrpc.php` (brute-force amplification via `system.multicall` + pingback SSRF/DDoS), REST user enumeration `GET /wp-json/wp/v2/users`, author-archive enumeration `/?author=N`, `wp-login.php` brute-force — anonymously reachable because `traefik_auth_modes.wordpress=oidc` (200 at edge, WP serves its own login + OIDC button, **not** forward-auth gated).
- **Mitigated:** `install_wordpress=false` + 127.0.0.1:8084 loopback. **Harden when enabled:** deny `/xmlrpc.php`, block anonymous `/wp-json/wp/v2/users`, disable author-archive enumeration, rate-limit / forward-auth `wp-login.php`. → **REM-114**
- **Source:** https://github.com/advisories/GHSA-6x83-fcf5-r65g (CVE-2026-3906, fixed 6.9.4) · https://www.searchenginejournal.com/wordpress-security-release-6-9-4/

### Clean this batch (no item)
- **spacetimedb** (`clockworklabs/spacetimedb:latest`): **no HIGH/CRITICAL CVE** in the 12-mo window — no GHSA on the repo Security tab, no OSV/NVD/CISA hit. BSL-1.1 internal-SaaS, `install_spacetimedb=false`. Probe: `traefik_auth_modes.spacetimedb=none` (binary protocol) but the container's internal `--listen-addr 0.0.0.0:3000` host-maps **only** to **127.0.0.1:3030 loopback** (binds the LAN interface only when `services_lan_access=true`) → no external unauth surface over the Traefik edge.

---

# nOS Vulnerability Scan Addendum — 2026-06-24 (Cycle 16, batch-5)

**Batch:** jellyfin, uptime_kuma, calibreweb, loki, dnsmasq · **Probe:** unauthenticated_endpoint_scan
**Outcome:** 1 queue item added (REM-106). **4 of 5 components are covered / N-A at their pins.** The one new finding is a *genuine, unauthenticated, network-reachable* HIGH on the host DNS resolver.

### ⚠ UNAUTH — [CVE-2026-2291 + CVE-2026-5172] dnsmasq — DNS-Response Heap Overflow → Cache Poisoning / DoS (HIGH)
- **Component:** dnsmasq (host Homebrew package, `2.91`, `tasks/dnsmasq.yml`)
- **Impact:** the May-2026 CERT/CC cluster (VU#471747, six CVEs, fixed in **2.92rel2** / upcoming 2.93). Our **2.91 is affected**. The subset that applies to nOS's config:
  - **CVE-2026-2291** — CVSS **7.3 HIGH** (`AV:N/AC:L/PR:N/UI:N/C:L/I:L/A:L`): heap buffer overflow in `extract_name()` while parsing **DNS responses** → inject false DNS-cache entries (redirect lookups to an attacker IP) or DoS. **Unauthenticated, remote.**
  - **CVE-2026-5172** — heap OOB read in `extract_addresses()` on a malformed DNS response → crash / DoS.
- **Why it is a real, unauthenticated perimeter hit:** `tasks/dnsmasq.yml` defaults **`dnsmasq_lan_access: true`** → `listen-address=127.0.0.1,<en0 LAN IP>` + `bind-interfaces`, and dnsmasq **forwards** every non-`dev.local` query upstream. So a LAN / Tailscale client that makes it resolve an attacker-controlled domain feeds malformed responses straight into the vulnerable parsers — no credentials, no UI.
- **Config-gated-OFF legs (N/A to nOS):** CVE-2026-4890 / 4891 (DNSSEC-validation infinite-loop DoS + heap OOB read — nOS sets **no `dnssec` directive**, validation disabled); CVE-2026-4892 (DHCPv6 heap OOB write → **local root RCE** — nOS is **DNS-only**, no `dhcp-range`/DHCP server); CVE-2026-4893 (RFC-7871 client-subnet source-check bypass — `add-subnet` not configured).
- **Remediation:** host package, **no pinnable image** (the `dnsmasq_version: "2.91"` var is documentation only; install is `state: present`) — same shape as REM-035 (nginx) / REM-024 (ollama). (1) operator-side `brew upgrade dnsmasq` to **≥ 2.92rel2** once the formula ships it (Homebrew may still carry 2.91); (2) defence-in-depth — set **`dnsmasq_lan_access: false`** to bind `127.0.0.1` only and drop all LAN reach if LAN-wide `*.dev.local` resolution is not needed. → **REM-106**
- **Source:** https://nvd.nist.gov/vuln/detail/CVE-2026-2291 · https://kb.cert.org/vuls/id/471747 · https://www.helpnetsecurity.com/2026/05/12/dnsmasq-vulnerabilities-cve/ · https://thekelleys.org.uk/dnsmasq/CHANGELOG

### Covered / not-applicable this batch (no item)
- **jellyfin** (`jellyfin/jellyfin:10.11.8`): **CVE-2026-35031** (CVSS **9.9** — subtitle-upload `Format`-field path-traversal → arbitrary file write → **RCE as root via LD_PRELOAD**) + **CVE-2026-35032** (LiveTV M3U tuner SSRF) are both fixed in **10.11.7** — these are the now-disclosed CVE IDs of the REM-072 embargoed batch (confirms REM-033/072 fully resolved). `oidc` (SSO-Auth plugin) + 127.0.0.1:8096 loopback + `install_jellyfin=false`.
- **loki** (`grafana/loki:3.7.2`): **CVE-2026-21726** (CVSS 5.3 — Ruler API `/loki/api/v1/rules/{namespace}` path-traversal via **double**-URL-encoding, a bypass of the CVE-2021-36156 fix) is fixed in **3.6.4**; our 3.7.2 is past it. 127.0.0.1:3100 loopback, **no Traefik router** (internal observability) — loopback-only even if it were vulnerable.
- **calibreweb** (`lscr.io/linuxserver/calibre-web:0.6.26-ls384`): **CVE-2025-6998** (unauth ReDoS, REM-074) + **CVE-2025-7404** (authed HIGH-priv OS-command-injection, CVSS 5.9) both cap at **OSV `last_affected: 0.6.24`** → 0.6.26 ('Ismara') is version-flagged clean (**medium** confidence — janeczku shipped no security-fix commit; the real fix is the Autocaliweb 0.7.1 fork). Mitigated regardless by `proxy` forward-auth in front of `/login` + 127.0.0.1:8083 loopback + Tier 3. *(The recent CVE-2026-26064 / 25635 / 27810 are **desktop Calibre** — calibre-ebook, a different product — N/A.)* REM-074 note refreshed.
- **uptime_kuma** (`louislam/uptime-kuma:1.23.13`): the 2026 **unauthenticated** advisories are **2.x-only** → N/A to our 1.x line — **CVE-2026-32230** (ping-badge missing-authz info-leak; affected ≥ 2.0.0–2.1.3, fix 2.2.0) and **GHSA-5px6-fx2w-459r** (unauth `getPushExample` path-traversal file read; affected 2.0.0-beta.0..beta.2). Forward-auth (`proxy`) gates **all** endpoints incl. badges + 127.0.0.1:3001 loopback. The 1.x-applicable SSTI **CVE-2026-33130** stays tracked as **REM-073** (fix only in 2.2.1 = breaking 1→2 migration, deferred to Phase D).

---

# nOS Vulnerability Scan Addendum — 2026-06-23 (Cycle 16, batch-4)

**Batch:** infisical, superset, outline, freescout, woodpecker · **Probe:** unauthenticated_endpoint_scan
**Outcome:** 2 queue items added (REM-104, REM-105). **3 of 5 components are CLEAN at their pins.** One *live, unauthenticated* perimeter finding (LOW) on Outline; one HIGH CVE on Woodpecker that is multiply-mitigated.

### ⚠ UNAUTH — [GHSA-wgqc-257g-78v3] Outline — Timing-Unsafe Token Comparison on Unauthenticated Unsubscribe Endpoints (LOW)
- **Component:** outline (b2b stack, `outlinewiki/outline:1.8.0-1`, 127.0.0.1:3005, native_oidc Traefik route, Tier 3)
- **Impact:** the **intentionally-unauthenticated**, token-gated endpoints `notifications.unsubscribe` and `subscriptions.delete` verify the security token with JS strict-equality (`!==`) instead of constant-time `safeEqual()` (CWE-208). A statistical timing oracle over HTTP response times could forge a valid unsubscribe/delete token. Impact is genuinely LOW (forge an unsubscribe / delete-a-subscription token; no document read/write).
- **Why it is a real perimeter hit (not loopback-only):** Outline's Traefik route is **native_oidc** (`traefik_auth_modes.outline = oidc` → 200 at the edge; Outline serves its own login page), and these two endpoints are **unauthenticated by design**, so an anonymous client on the LAN/Tailscale Traefik route reaches them.
- **Affected:** 0.69.0–1.8.0 (our pin `1.8.0-1` = app 1.8.0). **Fixed: 1.8.1** (latest, 2026-06-06).
- **Bundled clears:** the same 1.8.1 bump also closes the June moderate cluster GHSA-33jq-x32c-3ccw (webhook subscription survives creator account deletion) + GHSA-pp65-6cc2-4mx9 (MCP `list_documents` exact-match metadata leak).
- **Already covered by the pinned 1.8.0** (no action): GHSA-7732-6qrg-wjf4 (HIGH OAuth-scope priv-esc, fix 1.7.0), GHSA-hw32-2v7j-mgqc (HIGH zip extraction path-escape, fix 1.7.0), GHSA-5x79-rj4g-qrh8 (HIGH OAuth/API-key scope path-parsing authz bypass, fix 1.8.0).
- **Remediation:** bump `outline_version` **1.8.0-1 → 1.8.1**. → **REM-104**
- **Source:** https://github.com/outline/outline/security/advisories/GHSA-wgqc-257g-78v3 · https://github.com/outline/outline/releases

### [CVE-2026-50141] Woodpecker CI — gRPC `agent_id` Spoofing / Cross-Tenant Agent Impersonation (HIGH) — MITIGATED
- **Component:** woodpecker (devops stack, gRPC 127.0.0.1:9060, web 127.0.0.1:8060, Tier 2)
- **Impact:** an **authenticated** agent injects a forged `agent_id` into gRPC metadata; the server validates the agent JWT but then discards the verified identity and trusts the client-supplied value (CWE-290 + CWE-639) → cross-tenant agent impersonation.
- **Affected:** 3.0.0–3.14.0. **Fixed: 3.14.1** (workaround `WOODPECKER_DISABLE_USER_AGENT_REGISTRATION=true`).
- **Why mitigated (three axes):** gRPC binds **127.0.0.1:9060 loopback** (not LAN-exposed); exploitation requires a **valid authenticated agent JWT** (pre-auth surface nil) and nOS typically runs a single agent on the same host (no second tenant to cross); and the running image **floats past the fix** — the role default is already `v3.14.1` and `default.config.yml` pins the floating major tag `v3` (resolves to latest 3.x ≥ 3.14.1).
- **Version-pin shadow caveat:** config-wins means the *effective* pin is the floating `v3`, **not** the explicit role default `v3.14.1` — the fix is present only because `v3` currently floats ≥ 3.14.1, and the exact build is non-deterministic. **Recommend** pinning `default.config.yml` `woodpecker_version` to explicit `v3.14.1` for determinism + supply-chain reproducibility. (Distinct from REM-002, the still-pending docker-socket pipeline-escape.) → **REM-105**
- **Source:** https://github.com/woodpecker-ci/woodpecker/security/advisories/GHSA-g7mm-9vx7-jm7h · https://nvd.nist.gov/vuln/detail/CVE-2026-50141

### Clean this batch (no item)
- **infisical** (`infisical/infisical:v0.160.4`): no verified HIGH/CRITICAL CVE in the 12-mo window — Infisical's own GitHub Security Advisories page publishes none; no OSV/GHSA-global/NVD hit. Perimeter: authentik@file forward-auth gate (`traefik_auth_modes.infisical=proxy`, the real Tier-1 control since CE org-OIDC is enterprise-locked/inert) + 127.0.0.1:8075 loopback.
- **superset** (`apache/superset:6.0.0-dev`): CVE-2026-23980 / 23982 / 23983 + CVE-2025-48912 all fixed ≤ 6.0.0 and present in the `-dev` build (REM-030/068 resolved). 6.1.0 is now latest = hygiene-only. `6.0.0-dev` is a floating pre-release tag (reproducibility note, not a CVE).
- **freescout** (`tiredofit/freescout:php8.3-1.17.159` → app 1.8.219): past CVE-2026-28289 (unauth zero-click email RCE, fix 1.8.207) + CVE-2026-27636 + the 1.8.212 cluster (REM-029/069/070/071 resolved). No FreeScout CVE published after 1.8.219 in the window.

---

# nOS Vulnerability Scan Addendum — 2026-06-22 (Cycle 16, batch-3)

**Batch:** portainer, gitea, openwebui, mariadb, redis · **Probe:** unauthenticated_endpoint_scan
**Outcome:** 5 queue items added (REM-099…103) + REM-064 re-checked. **Unlike batch-2, this batch found GENUINE actionable exposure — three end-of-life release lines.** One finding carries a *live, unauthenticated* perimeter reach: **Gitea CVE-2026-27771**.

### ⚠️ CRITICAL — [CVE-2026-27771] Gitea — Unauthenticated Private-Package / Container-Registry Disclosure
- **Component:** gitea (devops stack, `gitea/gitea:1.25.5`, 127.0.0.1:3003, native_oidc Traefik route)
- **Impact:** Gitea's built-in container/OCI **and** Composer package registry serves **private** packages and container images in response to **anonymous, unauthenticated** pull requests. ~4-year-old flaw; ~31k internet-facing instances at disclosure.
- **Why this one is live (not mitigated-by-perimeter like the rest):** the Gitea package registry is **enabled by default** (no `[packages] ENABLED=false` in `roles/pazny.gitea`), and Gitea's Traefik route is **`native_oidc`** (`traefik_auth_modes.gitea = oidc`) — i.e. it is **NOT** wrapped in Authentik forward-auth (200 OK at the edge; Gitea owns its own login page). So the registry endpoints are reachable by anonymous clients over the LAN/Tailscale Traefik route. Exposure is *latent* only insofar as no private packages are stored yet — but the surface is open and the release line is dead.
- **EOL amplifier:** **1.25.5 is the last 1.25.x release (no 1.25.6).** Every fix from 2026-04 onward shipped only on the 1.26.x line with **no backport**. CVE-2026-27771 is fixed in **1.26.2**.
- **Companion cluster (also fix-only-in-1.26.x, AFFECTED on 1.25.5):** CVE-2026-22874 (CRIT 9.6 webhook SSRF, authed), CVE-2026-28699/28744 (HIGH OAuth2/Bearer token-scope bypass), CVE-2026-28737 (HIGH glTF stored XSS), CVE-2026-22555 / 26231 / 24791 (HIGH authz bypasses), CVE-2026-20779 (HIGH 2FA TOTP replay).
- **Not applicable in nOS:** CVE-2026-20896 (CRIT 9.8 `X-WEBAUTH-USER` impersonation via the image default `REVERSE_PROXY_TRUSTED_PROXIES=*`) requires Gitea's reverse-proxy header auth (`ENABLE_REVERSE_PROXY_AUTHENTICATION`) to be enabled — nOS does **not** enable it (Gitea uses native_oidc, no header-trust block), so the precondition fails. Lock `REVERSE_PROXY_TRUSTED_PROXIES` to loopback anyway as defense-in-depth.
- **Remediation:** bump `gitea_version` **1.25.5 → 1.26.4** (latest stable; 1.26.2 still misses the three 1.26.3 criticals; skip 1.26.3 itself — repo-code-page regression). Interim: require authentication for all package/registry reads. → **REM-099**
- **Source:** https://orca.security/resources/blog/gitea-container-registry-vulnerability/ · https://horizon3.ai/attack-research/vulnerabilities/cve-2026-27771/ · https://github.com/go-gitea/gitea/security/advisories/GHSA-2r5c-gw76-rh3w

### Also logged this batch
- **REM-100 (portainer, HIGH, pending — confidence medium):** pin **2.27.3 is EOL since Nov 2025**. 2026 container-escape cluster CVE-2026-44848/44849 (CRIT 9.4 authenticated host-RCE) formally ranges from 2.33.0 (scanner-clean on 2.27.3) but the advisory says the validation logic was *"never"* present; base-image OpenSSL **CVE-2025-15467** (8.8 pre-auth) likely in the un-rebuilt 2.27.x image. Mitigated by Tier-1 admin-only + native_oidc + loopback + docker-socket-proxy. → migrate to LTS **2.33.8+**.
- **REM-101 (openwebui, HIGH, pending):** pin **0.8.12** predates the 0.9.x disclosure batch (OSV: 1 CRIT + 27 HIGH). The CRIT **CVE-2026-44551** (LDAP empty-password bypass, unauth) is **N/A** — nOS uses OAuth/OIDC, no LDAP. The 27 HIGH are mostly authenticated cross-user/SSRF/XSS/IDOR behind the Authentik wall. → bump **0.8.12 → 0.9.6**.
- **REM-102 (mariadb, HIGH, pending — MITIGATED):** CVE-2026-49261 (10.0) / 48165 / 48163 / 44168 version-flag 11.8.6 but are **Galera-cluster-only** (`wsrep_*`); nOS runs standalone non-Galera, loopback + password auth → not exploitable. Hygiene bump **11.8.6 → 11.8.8** to clear image-tag scanners.
- **REM-103 (redis, HIGH, pending — MITIGATED):** floating pin `8.0` resolves to **EOL 8.0.6**; DarkReplica **CVE-2026-23479 / 25243** (HIGH 7.7 RCE-class) are unpatched on the 8.0 branch (OSS fix only on 8.2.6/8.4.3/8.6.3). Both **require auth**; `--requirepass` + loopback + internal-net ⇒ pre-auth surface nil. → re-pin **8.0 → 8.6.3**.
- **REM-064 re-checked (openwebui ZDI-26-031/032, CVE-2026-0765/0766):** confirmed **no upstream fix version exists** — vendor treats admin tool/function authoring as by-design code-exec; **not closable by any version bump** (neither 0.8.12 nor 0.9.6). Mitigate operationally (restrict who may author tools/functions).

---

# nOS Vulnerability Scan Addendum — 2026-06-21 (Cycle 16, batch-2)

**Batch:** vaultwarden, ollama, paperclip, tileserver, nginx · **Probe:** unauthenticated_endpoint_scan
**Outcome:** 4 queue items added (REM-095…098). **Two CRITICAL-rated CVEs surfaced — both verified MITIGATED.** Zero new live unauthenticated exposure.

### [CVE-2026-41679 + CVE-2026-41208] Paperclip — Unauth RCE + Agent-key RCE (CVSS 9.8 / 8.8) — MITIGATED
- **Component:** paperclip (devops stack, `ghcr.io/paperclipai/paperclip`, 127.0.0.1:3006, forward_auth Tier-2)
- **CVE-2026-41679 (9.8):** unauthenticated RCE via Import Authorization Bypass — a 6-call, no-credential / no-invite chain runs against a default deployment (GHSA-68qg-g8mg-6pr7).
- **CVE-2026-41208 (8.8):** agent holding an Agent API key sets `adapterConfig.workspaceStrategy.provisionCommand` via `PATCH /agents/:id`; the server executes it during workspace provisioning (CWE-78, GHSA-265w-rf2w-cjh4).
- **Fix:** both fixed in release **v2026.416.0** (commit `b8725c5`, 2026-04-16).
- **Why mitigated:** nOS pins `paperclip_version: sha-b9a80dc`, which resolves to upstream commit `b9a80dc` dated **2026-04-17** (PR #3784) — a descendant of the v2026.416.0 fix, so both patches are present. Defense-in-depth: loopback bind + Traefik `authentik@file` forward-auth.
- **Recommendation:** repin off the floating post-release feature SHA to a tagged release (≥ v2026.416.0) for supply-chain reproducibility. → **REM-097**
- **Source:** https://github.com/paperclipai/paperclip/security/advisories/GHSA-68qg-g8mg-6pr7 · https://nvd.nist.gov/vuln/detail/CVE-2026-41679

### [CVE-2026-7482] Ollama — "Bleeding Llama" Unauth Memory Leak (CVSS 9.1) — MITIGATED
- **Component:** ollama (host Homebrew, 127.0.0.1:11434)
- **Impact:** unauthenticated heap OOB read in the GGUF loader via `/api/create` with an oversized tensor shape; leaks process memory (env vars, API keys, system prompts, other users' conversations). ~300k servers globally.
- **Fix:** Ollama **0.17.1** (2026-02-25).
- **Why mitigated:** host brew `state=latest` floats past 0.17.1 (no `ollama_version` var to pin) **and** the API binds loopback-only. Windows auto-updater RCEs (CVE-2026-42248/42249) are N/A to the macOS/Linux brew build. → **REM-096**
- **Source:** https://thehackernews.com/2026/05/ollama-out-of-bounds-read-vulnerability.html · https://www.suse.com/security/cve/CVE-2026-7482.html

### Also logged this batch
- **REM-095 (vaultwarden, HIGH, resolved):** CVE-2026-27802 / 27898 / 43911 — pinned **1.35.8** is past all three fixes (≤ 1.35.5); all authenticated/cross-user, not unauth-relevant.
- **REM-098 (nginx, HIGH, pending):** 2026 cluster CVE-2026-42945 (rewrite-module, actively exploited) / 42530 (HTTP/3 UAF) / 42055 (proxy_v2/grpc) / 9256 — clears at nginx ≥ 1.31.2. Host package, `install_nginx=false` default (Traefik primary) → operator-side `brew/apt upgrade`, no repo pin possible (same disposition as REM-035/063).
- **tileserver (no item):** `maptiler/tileserver-gl:v5.6.0` is past CVE-2025-46653; the Tileserver-**PHP** CVEs (2025-44137/44136) are a different product. `install_offline_maps=false`.

---

# nOS Vulnerability Report — 2026-04-08

## Executive Summary

- **Total components scanned:** 46 (36 Docker, 4 Homebrew, 3 runtimes, 2 binaries)
- **Known CVEs found:** 40+ (14 CRITICAL, 20+ HIGH) across 19 components
- **Misconfiguration findings:** 21 (4 CRITICAL, 9 HIGH, 7 MEDIUM, 2 LOW)
- **Attack surface vectors:** 4 container escape paths, 5 lateral movement paths, 8 SSRF-capable services
- **Version pinning:** 23 of 36 Docker images use `:latest` — no reproducibility
- **Components needing IMMEDIATE action:** n8n (CVSS 10.0 unauth RCE), Redis (CVSS 10.0 RCE + no auth), FreePBX (CVSS 10.0 zero-day), Authentik 2025.2 (EOL, CVSS 9.1 code injection)

## CVE Findings — CRITICAL (CVSS 9.0+)

### [CVE-2026-21858] n8n — Unauthenticated RCE "Ni8mare" (CVSS 10.0)
- **Component:** n8n (iiab stack, port 5678)
- **Affected:** >= 1.65.0, < 1.121.0
- **Fix:** n8n >= 1.121.3 (or 2.0.0 for full N8scape fix)
- **Impact:** Unauthenticated remote code execution via content-type confusion in webhook/form handling. Read arbitrary files, forge admin sessions, execute OS commands. ~100,000 servers globally affected.
- **Chain:** CVE-2026-21877 (CVSS 10.0, auth RCE via file write) + CVE-2025-68613 (CVSS 9.9, expression injection) + CVE-2025-68668 (CVSS 9.9, Python sandbox escape)
- **Remediation:** `n8n_version: "2.0.0"` in default.config.yml
- **Source:** https://www.cyera.com/research/ni8mare-unauthenticated-remote-code-execution-in-n8n-cve-2026-21858

### [CVE-2025-49844] Redis — RediShell RCE via Lua (CVSS 10.0)
- **Component:** redis (infra stack, port 6379, **NO AUTHENTICATION**)
- **Affected:** All Redis through 7.4.5
- **Fix:** redis >= 7.4.6
- **Impact:** Use-after-free in Lua scripting engine. 13-year-old bug discovered at Pwn2Own Berlin 2025. In nOS, Redis has NO requirepass — any container on shared_net can exploit without credentials. ~60,000 servers globally affected.
- **Remediation:** `redis_version: "7.4.6-alpine"` + add `--requirepass` to command
- **Source:** https://redis.io/blog/security-advisory-cve-2025-49844/

### [CVE-2025-57819] FreePBX — Zero-Day Unauth RCE (CVSS 10.0)
- **Component:** freepbx (voip stack, SIP ports on 0.0.0.0)
- **Affected:** FreePBX <= 16.0.88
- **Fix:** FreePBX >= 16.0.89
- **Impact:** Actively exploited since August 2025. Unauthenticated auth bypass + SQL injection → cron job insertion → persistent RCE. 900+ instances compromised in the wild.
- **Chain:** CVE-2025-66039 (CVSS 9.3, auth bypass) + CVE-2025-61675/61678 (SQLi + file upload)
- **Remediation:** Verify tiredofit/freepbx image patch level. Restrict admin panel to localhost.
- **Source:** https://securityonline.info/critical-zero-day-cve-2025-57819-in-freepbx-is-under-active-attack-cvss-10-0/

### [CVE-2026-25227] Authentik — Code Injection (CVSS 9.1)
- **Component:** authentik (infra stack, **pinned 2025.2 — EOL, NO BACKPORT**)
- **Affected:** All versions before 2025.8.6 / 2025.10.4 / 2025.12.4
- **Fix:** authentik >= 2025.12.4
- **Impact:** Users with "Can view Property Mapping" permission can execute arbitrary code on the server. Full database + env var access → complete instance takeover.
- **Additional CVEs:** CVE-2026-25922 (CVSS 8.8, SAML assertion injection), CVE-2025-29928 (session revocation failure), CVE-2025-52553 (RAC session hijack)
- **Remediation:** **URGENT: Upgrade authentik_version from "2025.2" to "2025.12.4"** — 2025.2 is end-of-life for security fixes
- **Source:** https://docs.goauthentik.io/security/cves/CVE-2026-25227/

### [CVE-2025-63389] Ollama — Missing Auth on ALL API Endpoints (CVSS 9.8)
- **Component:** ollama (Homebrew, port 11434)
- **Affected:** Ollama <= 0.12.3
- **Impact:** Zero authentication on /api/tags, /api/copy, /api/delete, /api/create, /api/generate. Remote attackers can pull, delete, create models and generate content.
- **Remediation:** `brew upgrade ollama`. Ensure OLLAMA_HOST=127.0.0.1:11434.
- **Source:** https://github.com/advisories/GHSA-f6mr-38g8-39rg

### [CVE-2026-33186] Traefik — gRPC Auth Bypass (CVSS 9.1)
- **Component:** traefik (infra stack, network edge)
- **Affected:** All versions < 2.11.41 and < 3.6.11
- **Fix:** traefik >= 3.6.11
- **Impact:** Authorization bypass via gRPC-Go path canonicalization. Unauthenticated attackers bypass deny rules via malformed gRPC requests.
- **Additional:** CVE-2025-54386 (CVSS 9.8, path traversal in WASM plugins)
- **Remediation:** `traefik_image_version: "3.6.11"`
- **Source:** https://github.com/traefik/traefik/security/advisories/GHSA-46wh-3698-f2cx

### [CVE-2026-27876] Grafana — Arbitrary File Write → RCE (CVSS 9.1)
- **Component:** grafana (observability stack, port 3000)
- **Affected:** 11.6.0–12.4.1
- **Fix:** grafana >= 12.4.2
- **Impact:** SQL expressions feature allows arbitrary file write → RCE. Requires Viewer+ permissions AND sqlExpressions feature toggle.
- **Additional:** CVE-2025-4123 (CVSS 7.6, XSS + open redirect, actively exploited in wild)
- **Remediation:** `grafana_version: "12.4.2"`
- **Source:** https://nvd.nist.gov/vuln/detail/CVE-2026-27876

### [CVE-2026-27471] ERPNext — Unauth Document Access (CVSS 9.3)
- **Component:** erpnext (b2b stack, port 8082)
- **Affected:** ERPNext <= 15.98.0
- **Fix:** ERPNext >= 15.98.1
- **Impact:** Missing authorization on API endpoints → unauthenticated access to financial records, customer data, operational documents.
- **Additional:** CVE-2025-52039 (CVSS 8.2, SQLi), CVE-2025-66439 (SQLi), CVE-2025-65267 (XSS → account takeover)
- **Remediation:** `erpnext_version: "v15.98.1"` (pin exactly, not just "v15")
- **Source:** https://radar.offseq.com/threat/cve-2026-27471-cwe-862-missing-authorization-in-fr-0d95cb60

## CVE Findings — HIGH (CVSS 7.0–8.9)

### GitLab CE — 9 HIGH CVEs (Auth Bypass, XSS, DoS, 2FA Bypass)
- CVE-2025-25291/25292 (CVSS 8.8): SAML SSO auth bypass via ruby-saml
- CVE-2026-0723 (CVSS 7.4): 2FA bypass via forged WebAuthn
- CVE-2025-12716/8405/12029 (CVSS 8.7): Stored XSS (Wiki, vulnerability reports, Swagger)
- CVE-2025-12562/13927/13928 (CVSS 7.5): Unauthenticated DoS (GraphQL, Jira, Releases API)
- **Fix:** `gitlab_version: "18.8.2-ce.0"`

### Vaultwarden — 5 HIGH CVEs (Privilege Escalation, Auth Bypass, RCE)
- CVE-2025-24364 (CVSS 7.2): Admin panel RCE via sendmail + favicon
- CVE-2025-24365 (CVSS 8.1): Privilege escalation (org owner takeover)
- CVE-2026-27802/27803 (CVSS 8.3): Manager permission bypass
- CVE-2026-26012 (CVSS 6.5): Cipher enumeration bypass
- **Fix:** `vaultwarden_version: "1.35.4"`

### PostgreSQL — 3 HIGH CVEs
- CVE-2025-1094 (CVSS 8.1): SQL injection in libpq
- CVE-2025-8714/8715 (CVSS 8.8): pg_dump code injection → RCE on restore
- **Fix:** `postgresql_version: "16.10-alpine"`

### MariaDB — 2 HIGH CVEs
- CVE-2026-32710 (CVSS 8.6): Heap buffer overflow in JSON_SCHEMA_VALID → RCE
- CVE-2025-13699 (CVSS 7.0): mariadb-dump RCE
- **Fix:** Ensure `mariadb:lts` resolves to >= 11.8.6

### Open WebUI — 2 HIGH CVEs
- CVE-2025-64495 (CVSS 8.7): Stored DOM XSS → account takeover + RCE
- CVE-2025-64496 (CVSS 7.3): SSE code injection → JWT theft
- **Fix:** `openwebui_version: "0.6.35"` (switch from :main!)

### Gitea — 1 HIGH CVE
- CVE-2025-68939 (CVSS 8.2): File extension bypass via API → potential RCE
- **Fix:** `gitea_version: "1.23.0"`

### Redis — 1 HIGH CVE (+ CRITICAL above)
- CVE-2025-21605 (CVSS 7.5): Unauthenticated DoS via output buffer exhaustion
- **Fix:** Covered by redis >= 7.4.6

---

## Misconfiguration Findings — CRITICAL

### [MISCONFIG-001] Portainer — Docker Socket Mount = Host Root
- **Severity:** CRITICAL
- **Component:** portainer (infra stack)
- **Impact:** Portainer mounts `/var/run/docker.sock` without read-only flag. Any Portainer RCE or admin credential theft gives full Docker API access = root on host machine.
- **File:** `templates/stacks/infra/docker-compose.yml.j2:108`
- **Remediation:**
  ```yaml
  # Add docker-socket-proxy service to infra stack
  docker-socket-proxy:
    image: tecnativa/docker-socket-proxy:latest
    environment:
      CONTAINERS: 1
      IMAGES: 1
      NETWORKS: 1
      VOLUMES: 1
      POST: 0  # read-only
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - infra_net

  # Update Portainer to use proxy
  portainer:
    environment:
      - DOCKER_HOST=tcp://docker-socket-proxy:2375
    # Remove: - /var/run/docker.sock:/var/run/docker.sock
  ```

### [MISCONFIG-002] Woodpecker CI — Docker Socket = Pipeline Escape
- **Severity:** CRITICAL
- **Component:** woodpecker (devops stack)
- **Impact:** Woodpecker agent mounts Docker socket for pipeline execution. Any user with push access to a Woodpecker-enabled Gitea repo can execute arbitrary Docker commands on the host.
- **File:** `templates/stacks/devops/docker-compose.yml.j2:87`
- **Remediation:**
  ```yaml
  # Option 1: Enable trusted repos in Woodpecker
  WOODPECKER_REPO_OWNERS: "admin"  # Only admin repos can run pipelines

  # Option 2: Use rootless Docker backend
  WOODPECKER_BACKEND: "docker"
  # + run agent with rootless Docker
  ```

### [MISCONFIG-004] Redis — NO Authentication on Shared Network
- **Severity:** CRITICAL
- **Component:** redis (infra stack)
- **Impact:** Redis runs without `requirepass`. Accessible to ALL containers on `shared_net`. A compromised container (e.g., WordPress plugin RCE) can read/write session tokens for Authentik, ERPNext queues, Outline cache, Superset cache.
- **File:** `templates/stacks/infra/docker-compose.yml.j2:75`
- **Remediation:**
  ```yaml
  # Add to redis command:
  command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru --requirepass {{ redis_password }}

  # Update clients:
  # Authentik: AUTHENTIK_REDIS__PASSWORD: "{{ redis_password }}"
  # ERPNext: REDIS_CACHE: "redis://:{{ redis_password }}@redis:6379/0"
  # Outline: REDIS_URL: "redis://:{{ redis_password }}@redis:6379"
  # Superset: REDIS_URL with password
  ```

### [MISCONFIG-003] Traefik — Docker Socket Read = Secret Leakage
- **Severity:** CRITICAL
- **Component:** traefik (infra stack)
- **Impact:** Traefik mounts Docker socket as `:ro`. While read-only, Docker API GET requests can read all container environment variables — including every password and secret key in the stack.
- **File:** `templates/stacks/infra/docker-compose.yml.j2:132`
- **Remediation:** Same docker-socket-proxy approach as Portainer.

## High Findings

### [MISCONFIG-006] No Resource Limits on Any Docker Service
- **Severity:** HIGH
- **Impact:** None of 35+ Docker services have `mem_limit` or `cpus`. GitLab alone can consume 4GB+ RAM. ERPNext runs 6 containers without constraints. A single service OOM can cascade-crash the entire platform.
- **Remediation:** Add resource limits to docker-compose templates. Start with GitLab (4GB), ERPNext (1GB each), observability stack (1GB each).

### [MISCONFIG-010] 23 Docker Images on :latest Tag
- **Severity:** HIGH
- **Impact:** No version reproducibility. `docker compose pull` can silently introduce breaking changes or supply chain compromises. No way to audit "what version are we running?"
- **Remediation:** Apply `version-pins-proposal.json` — pin all critical+high services to specific semver tags.

### [MISCONFIG-012] Open WebUI on :main Branch Tag
- **Severity:** HIGH
- **Impact:** Open WebUI tracks development branch. Unreviewed code, potential regressions, unpatched vulnerabilities. This is the AI chat interface with Ollama access.
- **Remediation:** Change `openwebui_version: "main"` to `openwebui_version: "0.6.6"` (or latest release tag) in default.config.yml.

### [MISCONFIG-009] FreePBX SIP/RTP Ports on All Interfaces
- **Severity:** HIGH
- **Impact:** SIP (5060/udp+tcp), IAX (4569/udp), RTP (10000-10100/udp) exposed on 0.0.0.0. SIP brute-force and toll fraud are commodity attacks.
- **Remediation:** Bind to 127.0.0.1 unless LAN VoIP is required.

### [MISCONFIG-011] Unofficial Docker Images (tiredofit/*)
- **Severity:** HIGH
- **Impact:** FreeScout and FreePBX use single-maintainer images from tiredofit/*. Supply chain risk: account compromise = malicious image push.
- **Remediation:** Pin to specific version tags + image digest. Monitor repos for unusual activity.

### [MISCONFIG-007] Predictable Default Passwords (changeme_pw_*)
- **Severity:** HIGH
- **Impact:** All 34 passwords follow `changeme_pw_{service}`. While overridden in production, a `blank=true` reinstall with missing `credentials.yml` creates a fully guessable password environment.
- **Remediation:** Verify auto-generation covers ALL secret_key/auth_secret variables in main.yml.

### [MISCONFIG-008] Calibre-Web Default admin/admin123
- **Severity:** HIGH
- **Impact:** Default credentials remain after deployment. Even behind Authentik proxy auth, direct service access uses default password.
- **Remediation:** Add post-provisioning password change task.

## Attack Surface Summary

### Container Escape Paths (4 vectors)
1. **Portainer docker.sock** → Full host control (CRITICAL)
2. **Woodpecker docker.sock** → Pipeline-triggered host escape (CRITICAL)
3. **Traefik docker.sock :ro** → All container secrets readable (HIGH)
4. **Home Assistant privileged** → Full host access when enabled (HIGH, default off)

### Lateral Movement Paths (5 paths)
1. **Any container → Redis** (no auth) → Session hijacking
2. **ERPNext → MariaDB root** → All databases
3. **Containers with host-gateway → Host services** (Ollama, SSH, etc.)
4. **n8n Code Node → Any internal service** via SSRF
5. **Metabase/Superset → All databases** via SQL execution

### SSRF-Capable Services (8 services)
n8n (HIGH), Metabase (HIGH), Superset (HIGH), Grafana (MEDIUM), Uptime Kuma (MEDIUM), Open WebUI (MEDIUM), GitLab (MEDIUM), Nextcloud (LOW)

## Positive Security Controls (Already In Place)

- Nginx: `server_tokens off`, security headers, rate limiting, TLS 1.2/1.3
- Authentik SSO: Centralized identity, RBAC with 4 tiers, cookie domain isolation
- mkcert CA: Self-signed cert distribution to containers
- Localhost binding: Most services bound to 127.0.0.1 by default
- Docker network isolation: Per-stack networks (infra_net, iiab_net, devops_net, etc.)
- Log rotation: json-file driver with max-size/max-file on all services
- Healthchecks: All services have Docker healthcheck configured

## Recommendations

### Immediate (This Week)
1. Add Redis authentication (MISCONFIG-004) — highest impact, auto-fixable
2. Pin Open WebUI to release tag (MISCONFIG-012) — 1-line config change
3. Pin remaining critical services to specific versions (version-pins-proposal.json)

### Short Term (This Month)
4. Deploy docker-socket-proxy for Portainer and Traefik
5. Add resource limits to all Docker services
6. Bind FreePBX SIP/RTP to localhost
7. Enable PostgreSQL SSL

### Medium Term (This Quarter)
8. Implement Docker network micro-segmentation
9. Add Content-Security-Policy headers per vhost
10. Create dedicated MariaDB user for ERPNext runtime

## Scheduled Scan Configuration

The NOS Vulnerability Scanner is configured for iterative scanning:
- **Schedule:** 2x daily (06:00, 18:00) via launchd
- **Batch size:** 5 components per run
- **Strategy:** oldest_first — always scans least-recently-checked components
- **Attack probe rotation:** 8 different probe types cycling through scan cycles
- **State tracking:** `scan-state.json` with per-component timestamps
- **CVE sources:** OSV.dev, GitHub Advisory DB, NVD

Enable with: `configure_vulnerability_scan: true` in config.yml, then `ansible-playbook main.yml -K --tags vulnscan`

## Scan Metadata

- **Scanner:** NOS Vulnerability Scanner v1 (Claude Code)
- **Date:** 2026-04-08
- **Components scanned:** 46
- **Scan types:** Misconfiguration analysis, attack surface mapping, supply chain review, CVE research (in progress)
- **Data sources:** Static template analysis, OSV.dev, GitHub Advisory DB, NVD
- **Files generated:** versions.json, audit-manifest.json, scan-state.json, misconfig-findings.json, attack-surface.json, remediation-queue.json, version-pins-proposal.json
