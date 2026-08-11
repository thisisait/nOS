# nOS Vulnerability Scan Addendum — 2026-08-11 (Cycle 26, batch-49)

**Batch:** superset, outline, freescout, paperclip, tileserver · **Probe:** `default_credentials_test` (**first-ever run** — `attack_probe_schedule` cycle_mod 2, `last_run` was `null`)
**Outcome:** 3 queue items added (**REM-191 HIGH**, **REM-192 HIGH** — the probe's finding of record, **REM-193 LOW**). outline / paperclip / tileserver clean at their pins. Pending HIGH goes **4 → 6**.

> **The finding of record, stated once.** A service marked `oidc` in `traefik_auth_modes` means **the edge is OPEN** — Traefik attaches *no* forward-auth middleware — and the service's own login is the only gate. This batch found two services where that gate is a **prefix-derived default credential**, reachable from the internet. This is the exact class the `default_credentials_test` probe exists to catch, and it took the probe's first run to see it because prior batches only ran unauthenticated-endpoint / version-leak probes that never exercised a login.

---

### 🟠 HIGH — [REM-191, no CVE] Superset's local `admin` bypasses OIDC at an open, internet-reachable edge

- **Component:** superset — `nos/superset:6.0.0-dev` (built from `apache/superset:6.0.0-dev`), live as `data-superset-1`
- **Status:** config-derived, **live-verified**, high confidence. Not anonymous — gated by knowing a prefix-derived password.

`superset fab create-admin --username admin --password {{ superset_admin_password }}` runs every converge (`roles/pazny.superset/tasks/post.yml:43-52`). `superset_admin_password` defaults to `{{ global_password_prefix }}_pw_superset` (`default.config.yml:2265`), is **not** overridden in the operator's `credentials.yml`, and is **not** in `main.yml`'s lazy-regenerate group — so unlike `outline_secret_key` / `paperclip_auth_secret` it stays concatenation-derived at runtime, inside the **REM-144** blast radius (one leaked sibling credential reveals the master prefix; the master yields this by construction).

**Why the intended OIDC-only gate does not hold.** `superset_config.py` sets `AUTH_TYPE=AUTH_OAUTH`, so the estate treats Superset as native-OIDC and `traefik_auth_modes.superset='oidc'` attaches **no** `authentik@file` forward-auth to the auto-derived edge router (`state/manifest.yml:746-756`). But Flask-AppBuilder's `POST /api/v1/security/login` accepts an explicit `{"provider":"db"}` and authenticates against the **local user table regardless of `AUTH_TYPE`** — so the OIDC front door is bypassed by the DB-auth API.

**Proven live (not inferred):**
```
curl -s -X POST http://127.0.0.1:8089/api/v1/security/login \
  -d '{"username":"admin","password":"<wrong>","provider":"db"}'
→ HTTP 401 {"message":"Not authorized"}
```
A 401 is credential *evaluation-and-rejection* — not a 404, not "provider disabled" — confirming the db-auth path is live under `AUTH_OAUTH`. (No attempt was made with the real derived password; account access would be exfiltration, and the wrong-password 401 already proves the vector.)

**Internet reach confirmed** to REM-190's forced-anycast standard (a plain local curl hits gunicorn directly via split-horizon dnsmasq — the REM-144/190 caveat — so the public Cloudflare address is forced):
```
curl --resolve superset.pazny.eu:443:188.114.96.9 https://superset.pazny.eu/
→ HTTP 302 → /superset/welcome/  ·  server: cloudflare  ·  cf-ray: a293af8efd7f58b7-PRG  ·  cf-cache-status: DYNAMIC
```

**Why HIGH.** Superset Admin ⇒ SQLLab arbitrary SQL against every connected database — a data-plane compromise, not a dashboard. **Action:** mint `superset_admin_password` random + persist (add to `main.yml` lazy-regenerate group), rotate the live account off the derived value, and confirm OIDC admin mapping (`nos-admins → Admin`) before demoting/removing the local admin.

---

### 🟠 HIGH — [REM-192, no CVE] FreeScout's edge is `oidc`-classified but the OIDC module is a 404 — only a local default-admin form stands

- **Component:** freescout — `nfrastack/freescout:2.1.5-php8.3` (app 1.8.231), live as `b2b-freescout-1`
- **Status:** config-derived, **live-verified**, high confidence.

`traefik_auth_modes.freescout='oidc'` leaves the auto-derived edge router un-gated (`state/manifest.yml:621-629`) on the premise that native OIDC handles login. **That premise is false here:** the `freescout-oauth` module never installs — both upstream sources are HTTP 404 (`freescout-help-desk/oauth`, `tiredofit/freescout-module-oauth`), documented at length in `roles/pazny.freescout/tasks/post.yml`. So `/login` renders **only** a local email+password form, and the admin is `admin@pazny.eu` (`freescout_admin_email = default_admin_email`) / `{{ global_password_prefix }}_pw_freescout` — again prefix-derived, not overridden, not lazy-regenerated.

**Proven live:** `/login` (via the 302→https) returns HTTP 200 carrying `name="email"` + `name="password"` inputs and **no** "Sign in with Authentik" marker. Internet reach confirmed:
```
curl --resolve helpdesk.pazny.eu:443:188.114.96.9 https://helpdesk.pazny.eu/
→ HTTP 302 → /login  ·  server: cloudflare  ·  cf-ray: a293af8e8be023fa-PRG  ·  cf-cache-status: DYNAMIC
```

**Why HIGH.** FreeScout admin ⇒ full read/write over a helpdesk holding customer PII and inbound mail. **Action:** the honest fix for the classification lie is to **flip `traefik_auth_modes.freescout` to `proxy`** so the edge forward-auth-gates it — FreeScout has no working native OIDC, so a browser SSO wall in front of the local form is *not* a double-login (there is no second login). Also mint `freescout_admin_password` random. Re-evaluate `oidc` only if a reachable `freescout-oauth` module source is ever supplied. **REM-193 (LOW)** is the CVE currency leg: pinned app 1.8.231 lags security release 1.8.232 (2026-07-31, [GHSA-jvmv-2qcp-7855](https://github.com/freescout-help-desk/freescout/security/advisories) forgot-password throttling); 1.8.233 is non-security.

---

# nOS Vulnerability Scan Addendum — 2026-08-01 (Cycle 19, batch-40)

**Batch:** dnsmasq, n8n, metabase, tempo, alloy · **Probe:** `ssrf_vector_analysis`
**Outcome:** 3 queue items added (**REM-153 CRITICAL**, **REM-152 HIGH** — the probe's finding of record, **REM-154 MEDIUM**); REM-106 reconciled and live-verified resolved; tempo and alloy clean. Pending CRITICAL goes **1 → 2**.

Two of the five components were declared **CLEAN on 2026-07-18**. Both statements were **false when written**. Neither was a judgement error — both were the same structural blind spot, and it is now the third batch in a row to hit it.

> **The methodology finding, stated once for the whole queue.** n8n and Metabase publish **repo-level advisories with no CVE IDs assigned**. Metabase's last ten advisories include six with `cve_id: null`; **all 25** n8n advisories below have `cve_id: null`. Batch-29 searched CVE-keyed sources (`community.n8n.io`, OpenCVE, CCCS, NVD) and truthfully found nothing — because there is nothing CVE-keyed to find. This is identical to the authentik finding in batch-39. **"No new CVE" is evidence of nothing.** Query `api.github.com/repos/<owner>/<repo>/security-advisories`; for npm/Go projects a version-aware OSV query is the cheapest single check (`n8n@2.28.1` → **29 vulns**).

---

### 🔴 CRITICAL — [REM-153, no CVE] Metabase ships an arbitrary file read/write primitive, enabled by default

- **Component:** metabase — `metabase/metabase:v0.61.2.6`, live as `data-metabase-1`
- **Advisory:** [GHSA-cwxq-fmxq-jv8h](https://github.com/metabase/metabase/security/advisories/GHSA-cwxq-fmxq-jv8h), published **2026-07-12** — *six days before the scan that called this component clean*
- **Status:** version-confirmed, **high confidence**. Authenticated, **not** anonymous.

Metabase left the H2 built-ins `FILE_READ`, `FILE_WRITE`, `CSVREAD`, `CSVWRITE` and `LINK_SCHEMA` unrestricted. Anyone who can run a native query or action against an H2 source can read arbitrary files off the container, write files to it, and open connections to other databases.

**Version mapping matters here.** Metabase numbers OSS as `v0.X.Y` and the Enterprise build as `v1.X.Y` from one source tree, and advisories are written against the 1.x numbers. The pin `v0.61.2.6` reads as **1.61.2.6**:

| Affected range | Patched | Our pin |
|---|---|---|
| `>= 1.55.0, < 1.58.16` | 1.58.16 | — |
| `>= 1.59.0, < 1.59.13` | 1.59.13 | — |
| `>= 1.60.0, < 1.60.9` | 1.60.9 | — |
| **`>= 1.61.0, < 1.61.4`** | **1.61.4** | **1.61.2.6 → AFFECTED** |

Upstream patched *"and matching 0.x releases"* — so the OSS line is in scope. This is **not** one of the Enterprise-only H2 items: `CVE-2026-33725`, correctly dismissed as EE-only in batch-29, is a different bug, and that dismissal must not be read across.

**Why CRITICAL.** The bundled **sample database is H2**. No operator has to attach an H2 source for the primitive to exist — it ships attached, so every principal with query permission holds it.

**Who holds that permission, stated plainly.** Metabase OSS has no OIDC, so per `docs/sso-and-attribution.md` it runs as a Traefik `forward_auth` gate (`traefik_auth_modes.metabase='proxy'`) in front of a **shared account**. Every tenant user who clears the Authentik wall lands on the *same* query-capable identity. There is no per-user Metabase authorization underneath the gate, and no per-user attribution in the audit trail either.

**The SSRF leg** — why this surfaced under this probe and not a version sweep: `LINK_SCHEMA` opens connections to attacker-named databases *from inside the container*. That is an outbound-connection primitive with no allow-list — an SSRF, though the advisory never uses the word. The container holds `data_net` **and** the flat `shared_net`, so it reaches `postgresql`, `redis`, `mariadb` and every peer by container name; `FILE_READ` additionally discloses the container's own `MB_DB_PASS` from the environment.

**Action.** Bump `v0.61.2.6 → v0.61.9` in `default.config.yml:2066` **and** `roles/pazny.metabase/defaults/main.yml:10` together (version-pin shadow: `default.config.yml` wins). v0.61.9 (2026-07-28) is ≥ the 0.61.4 floor and **stays on the 0.61 line** — a patch move, no Flyway major migration. Do *not* jump to v0.62.7 in the same step; that is a minor-line move on a service whose first boot already needs a 300s `start_period`.

**Re-checked and still covered at the pin** (each range checked, not assumed): CVE-2026-59827 (CRIT 9.9) fixes at 1.61.1.4 — `1.61.2.6 > 1.61.1.4`, not affected. CVE-2026-59826 (CRIT 9.1) fixes at 1.61.2 — not affected. CVE-2026-50148 (CRIT 10.0 Snowflake JDBC RCE), CVE-2026-50147 (HIGH 7.6) and the 2026-05-27 MEDIUM cluster (including the only unauthenticated one, GHSA-rxq7-9vqf-q9g8) declare **no 1.61 range at all** — not affected.

---

### 🟠 HIGH — [REM-152, no CVEs] n8n is two advisory waves behind, and four of them bypass the SSRF control we installed

- **Component:** n8n — `n8nio/n8n:2.28.1`, live as `iiab-n8n-1`
- **Status:** version-confirmed, **high confidence**. Authenticated (workflow seat).

**This is the probe's finding of record.** REM-043 closed n8n's SSRF by enabling the built-in guard `N8N_SSRF_PROTECTION_ENABLED="true"` via the `n8n-base` plugin. Upstream has since shipped nodes that **route around it**.

[GHSA-vhf8-cg2h-cg3p](https://github.com/n8n-io/n8n/security/advisories/GHSA-vhf8-cg2h-cg3p) is the direct hit — the MCP Client node *"sends requests to user-supplied endpoints without routing them through SSRF protection and without pinning the resolved address."*
`CVSS:4.0/AV:N/AC:L/AT:N/PR:L/UI:N/VC:L/VI:N/VA:N/SC:H/SI:H/SA:L` = **6.4**. `PR:L` = *"an authenticated user who could create or edit a workflow"* — the **default** `workflow:create` permission. The guard is simply not consulted.

Three more, independently:

| Advisory | Sev | What it bypasses |
|---|---|---|
| `GHSA-64xh-79j6-r5v8` | HIGH 7.1 | the "Allowed HTTP Request Domains" credential allow-list, across the AI/LLM nodes |
| `GHSA-2x35-3fw4-9jr4` | HIGH 8.2 | SSRF **+ arbitrary file read** via nodemailer content-object type confusion |
| `GHSA-9w78-79q7-r4fp` | MED 6.3 | internal network reach via the dynamic node-parameters endpoints |

**REM-043's full impact is restored.** n8n holds `iiab_net` **and** the flat `shared_net`, so the primitive reaches `postgresql`, `redis`, `mariadb`, `prometheus` and `portainer` by container name. **SEC-02 does not cover this** — SEC-02 moved the *header-trust* backends onto gated nets; n8n was never one of them.

**Do not reopen REM-043.** Its control is correct and still blocks the HTTP Request node. The durable lesson is different: **an in-app SSRF allow-list is a per-node property and regresses silently every time upstream ships a new node.** It cannot be the only layer.

**The two missed waves.** Wave A (2026-07-08, 11 advisories, fixed 2.29.8/2.30.1) — ceiling `GHSA-pm35-fqvh-cq5g` **8.9**, authenticated code execution via legacy-expression sanitizer bypass; also `GHSA-35q8-9mj6-wjmf` (7.7) SSO instance-role provisioning → privilege escalation to instance owner, directly relevant since nOS wires n8n to Authentik native OIDC. Wave B (2026-07-22, 15 advisories, fixed 2.31.5/2.32.1) — `GHSA-8342-988q-86cr` (8.9) account takeover via unverified email claim, `GHSA-gv7g-jm28-cr3m` (8.7) expression sandbox escape → command execution, `GHSA-rcv6-pvrj-4xcg` (8.7) code execution in the Git node. Only `GHSA-33q9-f52j-gc75` is already covered at 2.28.1.

**Filed HIGH, deliberately not CRITICAL.** The ceiling across all 25 is 8.9 and GitHub labels every one High or Moderate — none is a CRITICAL, none is unauthenticated RCE. Escalating the aggregate would misrepresent the sources. What makes it urgent is *breadth* — four independent sandbox-escape/code-execution paths and two 8.9 takeover-class items — plus the SSRF cluster above.

**Action.** Bump `2.28.1 → 2.32.7` (the current `stable` tag, 2026-07-31; ≥ the 2.32.1 floor, clears both waves) in `default.config.yml:1475` **and** `roles/pazny.n8n/defaults/main.yml:10` together. Same-major migrate-on-start, no coexistence track. Interim mitigation if the bump must wait: `NODES_EXCLUDE` the MCP Client node — upstream's own workaround, recommended precisely because the in-app guard is the thing that failed.

---

### 🟡 MEDIUM — [REM-154, no CVE — configuration] dnsmasq relays DNS-rebinding answers

- **Component:** dnsmasq — host Homebrew package **2.93**
- **Status:** **live-confirmed**, high confidence. Scoped — see below.

The Ansible-managed block in `tasks/dnsmasq.yml` emits `address=`, `listen-address=`, `bind-interfaces`, `local=/<tenant_domain>/` and `cache-size` — but **not `stop-dns-rebind`**, and dnsmasq's rebind filter is off by default. Because `local=` scopes authority to the tenant domain only, every other name is forwarded upstream and the answer returned verbatim, including answers pointing into `127.0.0.0/8` or RFC-1918.

```
$ dig +short @127.0.0.1 localtest.me A     → 127.0.0.1     # via dnsmasq: relayed, not filtered
$ dig +short @1.1.1.1   localtest.me A     → 127.0.0.1     # control: the answer is genuinely upstream's
```

`localtest.me` is a public name whose authoritative answer *is* `127.0.0.1` — a safe, non-destructive stand-in for an attacker-controlled rebinding domain. With `stop-dns-rebind` set, dnsmasq would have filtered it. The effective `dnsmasq.conf` contains no `stop-dns-rebind` / `rebind-domain-ok` / `rebind-localhost-ok` anywhere.

**Scope, stated honestly — the obvious over-claim is wrong.** dnsmasq binds `127.0.0.1` *and* the en0 LAN address (`dnsmasq_lan_access` defaults **true**), so it is an unauthenticated forwarding resolver for any LAN/Tailscale client pointed at it — the documented purpose of that flag. For that population the relay is real. It does **not** chain into this batch's container SSRF findings: containers resolve via Docker's embedded DNS (`127.0.0.11`) → Docker Desktop VM upstream, and on the host `/etc/resolver/<tenant_domain>` is **domain-scoped**, so mDNSResponder consults dnsmasq only for the tenant domain. dnsmasq is therefore *not* in the resolution path an n8n or Metabase rebinding attack would need. Rated **exploitable** for LAN-resolver clients, **theoretical** as a container-SSRF amplifier — filed because it becomes load-bearing the moment anything is pointed at dnsmasq as a general resolver.

**Action.** Add `stop-dns-rebind` — and **`rebind-localhost-ok` alongside it, which is required, not optional**: on a local-TLD install the tenant domain is itself answered as `127.0.0.1`, so a bare `stop-dns-rebind` would filter nOS's own `*.dev.local` answers and break the platform by name. Exempt any legitimate private-address domain with `rebind-domain-ok=/<domain>/` rather than dropping the guard.

---

### ✅ Resolved / clean

**REM-106 (dnsmasq) — reconciled and live-verified.** The queue had it resolved on **2026-07-16 with no justification recorded**, while `scan-state.json` still read *"REM-106 stays PENDING"* — and carried batch-21 (2026-07-05) prose under a 2026-07-16 timestamp, the same "timestamp advanced without a re-read" defect batch-39 named for authentik. Both files are reconciled; the original `resolved_at` was **preserved, not rewritten**. The resolution is correct on evidence: `brew list --versions dnsmasq` → **2.93**, upstream's full fix release for the May-2026 CERT/CC cluster (VU#471747), clearing CVE-2026-2291 and CVE-2026-5172. No repo change was needed — `state: present` tracked upstream on its own. *Housekeeping:* `default.config.yml:1720` still says `dnsmasq_version: "2.91"` — doc-only, but it is the repo's only dnsmasq version string and now under-reports the host by two releases.

**tempo — clean at 2.10.3.** Both OSV records are covered: `GO-2026-5359` (CVE-2026-28377) is fixed *at* 2.10.3, and `GO-2026-5528` is fixed at 2.10.2. **Correction to a standing note:** batch-29 recorded the OOM item as *"CVE-2026-27878 … fixed Tempo 2.8/2.9"*; OSV's authoritative alias is **CVE-2026-21728** and the real 2.10-line fix point is **2.10.2**. The conclusion was right, but the margin is one patch release, not a minor line. Also note `GO-2026-5359` carries an unmapped `SEMVER {introduced: 0}` range with no `fixed` event and is flagged `UNREVIEWED` — read the ECOSYSTEM `custom_ranges`, or it reads as a false positive forever. All three ports live-confirmed loopback-bound; no Traefik router.

**alloy — clean at 1.18.0**, exactly current with upstream (v1.18.0, 2026-07-20). Verified through *both* channels this batch proved necessary: OSV returns an empty result, and the repo advisory endpoint returns **zero** — so Alloy has no hidden CVE-less channel, and this "clean" is evidence-backed rather than an absence-of-CVE inference. REM-107 live-verified: 4317, 4318 and 12345 all bound `127.0.0.1`. *Disposed:* `CVE-2025-68156` appears against a `grafana-alloy 1.12.1-r1` package build, but the CVE is `expr-lang/expr` — a transitive Go dependency, not Alloy code, and a distro-packaging record rather than a Grafana advisory.

---

### Probe verdict — `ssrf_vector_analysis`

| Vector | Rating |
|---|---|
| n8n MCP Client node — bypasses `N8N_SSRF_PROTECTION_ENABLED` (GHSA-vhf8) | **exploitable** (auth, default perm) |
| n8n AI/LLM nodes — bypass "Allowed HTTP Request Domains" (GHSA-64xh) | **exploitable** (auth) |
| n8n Send Email node — SSRF + arbitrary file read (GHSA-2x35) | **exploitable** (auth) |
| n8n dynamic node parameters — internal network reach (GHSA-9w78) | **exploitable** (auth) |
| Metabase `LINK_SCHEMA` — attacker-directed outbound DB connection (GHSA-cwxq) | **exploitable** (auth, shared account) |
| dnsmasq rebinding relay — LAN-resolver clients | **exploitable** (unauth, scoped population) |
| dnsmasq rebinding — as a container-SSRF amplifier | **theoretical** (not in the resolution path) |
| Alloy OTLP receiver as SSRF target | **mitigated** (loopback, REM-107) |
| Tempo `/status/config` + TraceQL | **mitigated** (loopback, no router) |

**The structural result.** nOS's SSRF posture rests on **in-application allow-lists** — n8n's SSRF guard, Metabase's driver restrictions — which are *per-node* and *per-function* properties that regress silently whenever upstream ships a new node or forgets a builtin. Meanwhile the **blast radius** is set by flat `shared_net` membership, which both n8n and Metabase still hold and which SEC-02 never covered for them. Patching the two version pins closes today's instances; extending the SEC-02 gated-net treatment to the two SSRF-capable workload services is the durable fix.

---

# nOS Vulnerability Scan Addendum — 2026-07-31 (Cycle 18, batch-39)

**Batch:** kiwix, authentik, grafana, nextcloud, loki · **Probe:** `default_credentials_test` (**first run of this probe type**)
**Outcome:** 3 queue items added (**REM-151 HIGH** — the probe's finding of record, REM-150 HIGH, REM-149 MEDIUM); kiwix and loki clean/re-verified. **No CRITICAL this batch** — REM-137 (gitea 1.27.0) remains the only pending CRITICAL. All five components were **live on the host**, so versions below are `docker ps` / `occ status` facts rather than pin assumptions.

The probe went looking for vendor default logins. It found that **nOS ships its own**.

### 🟠 HIGH — [REM-151, no CVE — configuration] `global_password_prefix` defaults to `changeme`, and the guard that would catch it is switched off on the default tenant

- **Component:** authentik (+ grafana, nextcloud, mcp_gateway — anything prefix-derived)
- **Status:** config-derived, **high confidence**, reproducible from a clean clone. **This host is *not* affected** — see below.

Every nOS admin credential is a pure function of one shared string. That is documented and deliberate. What this probe establishes is that the string has a **committed default**, and that the assert meant to reject it **does not run on the default install**.

Four links, each verified independently:

| # | Link | Evidence |
|---|---|---|
| 1 | The default prefix is a committed literal | `default.config.yml:8` → `global_password_prefix: "changeme"` |
| 2 | A fresh clone has no override | `credentials.yml` is ignored at `.gitignore:12`, and `git ls-files` returns nothing → **not tracked** |
| 3 | The weak-prefix assert is skipped | `main.yml:1257` is gated `when: not (tenant_domain_is_local ...)`; `default.config.yml:131` derives that flag from a `.local/.lan/.test` suffix — and the default `tenant_domain` **is `dev.local`** |
| 4 | Nothing ever prompts | The prefix prompt (`main.yml:1058`) fires **only** on a confirmed removal; a plain first `ansible-playbook main.yml` never asks, and bare ENTER re-accepts the current value anyway |

So the default path is silent: no prompt, no assert, no warning. What a fresh install then stands up:

```
authentik   akadmin / changeme_pw_authentik_admin     <- IdP SUPERUSER
grafana     admin   / changeme_pw_grafana
nextcloud   admin   / changeme_pw_nextcloud_admin
mcpo        api-key   changeme_pw_mcpo
authentik   db pass   changeme_pw_authentik_db
```

The username halves are shipped literals too (`admin`, `akadmin`). `default.credentials.yml:65` even spells the Nextcloud pair out in a comment as the "Default login".

**Reachability.** Services bind `127.0.0.1` (`services_lan_access: false`), but **Traefik binds `0.0.0.0:443`** and routes all three. `traefik_auth_modes` is `oidc` for grafana and nextcloud and `none` for authentik (it *is* the auth provider), so each router answers `200` anonymously and serves **the service's own login form**. Native OIDC *adds* a "Sign in with Authentik" button — it does not remove local password auth. From LAN/Tailscale, the local-credential path is live for all three.

Second-order effect worth naming: a local admin login **bypasses the Authentik MFA posture entirely**, because MFA is enforced inside the Authentik flow that the local form never enters.

**Verified *not* affected — the one that is handled correctly.** `authentik_secret_key` is declared prefix-derived at `default.credentials.yml:313`, but `main.yml:1299` lazy-regenerates any value containing `_pw_` into `openssl rand -hex 50` and persists it to `~/.nos/secrets.yml`. The Django `SECRET_KEY` that signs authentik session cookies is therefore **not** derivable from the prefix, and the cookie-forgery path that would have made this unconditionally critical **does not exist**. Rated HIGH rather than CRITICAL for that reason plus the operator-inaction precondition; the *impact* if triggered is full-tenant compromise.

**This host is not exploitable.** The operator's untracked `credentials.yml:11` carries a non-default 13-character prefix. REM-151 is about what a **fresh install of this playbook provisions by default** — precisely the probe's remit.

**Relationship to REM-144** (resolved 2026-07-30): complementary, not duplicate. REM-144 was the prefix being *disclosed* through the Traefik API. REM-151 is the prefix being *guessable in the first place*. Both converge on the same root weakness: one shared string, no per-service entropy.

**Action**, in order of preference: (a) generate a random prefix on first run when none is supplied — mirrors the `main.yml:1299` pattern already proven for `secret_key`, and removes the failure mode instead of warning about it; (b) at minimum drop the `not tenant_domain_is_local` condition so the assert also fires on `dev.local`, keeping the documented `-e allow_weak_prefix=true` escape for throwaway boxes; (c) give admin passwords their own per-service generation. Pin with a `tests/anatomy/` gate so `changeme` cannot survive a default-tenant run.

### 🟠 HIGH — [REM-150 / CVE-2026-15583] Unauthenticated SSRF in the `mcp-grafana` sidecar exfiltrates its Grafana service-account token

- **Component:** mcp_gateway — `iiab-mcp-grafana-1`, `mcp/grafana:latest` @ `sha256:9362bcf…`, **built 2026-07-08**
- **Status:** version-confirmed by build date; **mitigated** to container-adjacent, *not* anonymous remote

**This corrects a standing note.** Previous grafana entries recorded "no separate Grafana component deployed", grep-confirmed against `grafana-image-renderer`. That check was aimed at the wrong sidecar — `docker ps` shows `mcp-grafana` running, rendered by `roles/pazny.mcp_gateway/templates/compose.yml.j2:66-81`.

CVE-2026-15583 (published 2026-07-15, **CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:N/A:N — 8.6**): a confused-deputy SSRF where the attacker-supplied `X-Grafana-URL` header overrides the configured Grafana base URL, so mcp-grafana issues its outbound call — **carrying its environment-configured service-account token** — to an attacker-chosen destination. `PR:N`: no authentication to mcp-grafana required. Fixed in **0.17.1**.

The token is real, not a placeholder: `compose.yml.j2:71` sets `GRAFANA_SERVICE_ACCOUNT_TOKEN`, populated by `tasks/post.yml:108`.

**Why the pin is the bug.** `mcp_grafana_version` defaults to `latest`. The resident image was built **2026-07-08 — seven days before the fix** — and has never been re-pulled. The binary self-reports `(devel)` with no semver, so neither a human nor a version-keyed scanner can read the version off the image; the build date is the only evidence, and it points the wrong way.

**Reachability — mitigated, stated honestly.** `docker port` returns `8000/tcp -> null` (no host publish); it is absent from `state/manifest.yml`, so no Traefik router is derived; the fronting `mcpo` is *both* forward-auth gated (`traefik_auth_modes.mcp_gateway: proxy`) and `--api-key` protected, and opens its own SSE session from static config rather than proxying client headers. I did **not** test mcpo's header handling, so treat edge→SSRF injection as *unverified* rather than ruled out. The realistic path is a foothold in any other container on `iiab_net` or the flat `shared_net` — lateral movement plus credential theft, which is why this is HIGH and not CRITICAL despite the `PR:N` 8.6.

**Action:** pin `mcp_grafana_version` to an explicit `>= 0.17.1` tag instead of `latest`, re-pull and recreate, then **rotate the Grafana service-account token** (a `--tags mcp_gateway` run re-provisions it).

### 🟡 MEDIUM — [REM-149] authentik `2026.5.2` sits inside the 2026-07-15 five-advisory wave's affected range

A five-advisory wave published **2026-07-15** declares affected `<= 2026.5.4` / `<= 2026.2.5`, fixed **2026.5.5 / 2026.2.6**. The pin `2026.5.2` is inside every range: CVE-2026-61574 (HIGH 8.8, RAC endpoints + stored credentials exposed to any authenticated user), CVE-2026-57580 (HIGH 8.7, SAML NameID XML-comment truncation → account takeover), CVE-2026-54730 (HIGH 8.6, Chrome device-trust stage advances without attestation), CVE-2026-55106 (MED 5.3, **unauthenticated** LDAP Source diagnostic endpoint), GHSA-hmrg-vpp4-gj88 (MED 5.4, SSF stream management).

**All five are N/A at today's configuration**, each checked rather than assumed: three are **enterprise-only** features (RAC, Chrome device trust, Shared Signals Framework) and nOS runs CE; the SAML leg needs an inbound SAML **Source** in non-default matching mode and nOS declares none (authentik is the *Provider*, explicitly exempted); the unauth LDAP leg needs a configured LDAP Source and nOS configures none.

So this is **version drift, not live exposure** — but the defence is *which features nOS declines to use*, and it expires silently the day an operator adds an LDAP or SAML Source. Bump `2026.5.2 → 2026.5.6` in `default.config.yml:2232` **and** `roles/pazny.authentik/defaults/main.yml:13`.

> **⚠ Methodology note — this wave was missed for 16 days, and would be missed again.** The authentik entry showed `last_checked: 2026-07-16` but its notes were verbatim the **2026-07-06** batch-22 text: the timestamp had been advanced without a re-read, and the wave landed in that gap. Compounding it, **authentik's advisories are repo-level only** — published at `api.github.com/repos/goauthentik/authentik/security-advisories`, **not** mirrored into GitHub's global advisory database (`GET /advisories/<ghsa>` → **404**), and **OSV has zero records** for the authentik package in any ecosystem. A version-keyed scanner querying OSV or the global GHSA API reports authentik CLEAN and is **wrong**. Query the repo endpoint or miss everything.

### Clean / re-verified

- **kiwix** — `3.8.2` live, and still upstream head (no 3.8.3/3.9.x); **zero** advisories in `kiwix/kiwix-tools` *and* `kiwix/libkiwix`. Probe: **no credential surface exists** — kiwix-serve ships no auth layer, no admin account, no login form, and the compose template passes no credential env at all. The only component in this batch the `changeme` chain does not reach.
- **loki** — `3.7.2` live. New in window: **CVE-2026-21729** (detected_fields unbounded memory allocation → OOM, CVSS 7.5) affects **all versions prior to 3.7.0**; the pin is above the fix floor → **not affected**. Worth recording because that phrasing would flag the 3.6.x line this deployment sat on before the 3.7 move. Probe: no credential surface (`auth_enabled` is a multi-tenancy header switch, not a login); loopback-only, no Traefik router. `3.7.4` available — bug fixes only, no security section.
- **grafana core** — `12.4.4` live, CVE-clean. The new **CVE-2026-21723** (< 12.3.3) and **CVE-2026-21724** (< 12.3.6) both fix on branches *below* the 12.4 line, which was never in range. `12.4.6` available as a freshness bump only.
- **nextcloud** — floating tag `33`; `occ status` reports **33.0.6** while upstream shipped **33.0.7** on 2026-07-23, so the tag has not re-pulled. No advisory published against 33.0.6 → freshness, not exposure. Same floating-tag defect class as REM-150: the resident image can sit arbitrarily far behind the tag with nothing in the repo to show it.

---

# nOS Vulnerability Scan Addendum — 2026-07-30 (Cycle 17, batch-38)

**Batch:** woodpecker, jellyfin, traefik, uptime_kuma, calibreweb · **Probe:** `version_header_leakage` (**first run of this probe type**)
**Outcome:** 5 queue items added (**REM-144 traefik CRITICAL**, REM-145 traefik HIGH, REM-146 woodpecker LOW, REM-147 jellyfin LOW, REM-148 uptime_kuma MEDIUM); calibreweb clean/re-verified. All five components were **live on the host**, so this batch is evidence-based rather than config-inferred — every claim below came from an actual unauthenticated HTTP request.

The probe went looking for leaked version strings. It found leaked **credentials**.

### 🔴 CRITICAL — [REM-144, no CVE — configuration] Traefik dashboard/API anonymously reachable at the edge, disclosing both SEC-6 edge-trust tokens and `global_password_prefix`

- **Component:** traefik (infra stack, `traefik:v3.6.23`; `roles/pazny.traefik/vars/main.yml`, `templates/traefik.yml.j2`, `state/manifest.yml:145-153`; `install_traefik` default-**on**)
- **Status:** live-confirmed, unauthenticated, **anonymous from LAN/Tailscale**. Internet reach *unverified* — see honesty note below.

**This overturns a disposition carried since batch-21.** Every prior traefik note recorded the API as safe because the dashboard is *"bound `127.0.0.1:8080` loopback"*. The bind is real. It is also irrelevant.

`state/manifest.yml` gives the `traefik` entry both `domain_var` and `port_var`, so `templates/dynamic/services.yml.j2` auto-derives a file-provider router for it — and `vars/main.yml` sets `traefik_auth_modes.traefik: none`, annotated with the now-false comment *"own dashboard (LAN-only via 127.0.0.1 bind)"*. The router as actually rendered:

```json
"traefik@file": {"entryPoints":["websecure"], "rule":"Host(`traefik.<tld>`)",
                 "middlewares":["security-headers@file","compress@file"],
                 "service":"traefik"}
"traefik@file" service -> {"url":"http://192.168.65.254:8082"}
```

No `authentik@file` in that chain, and the backend is the **Docker host-gateway address** — Traefik proxies *around* the loopback bind it was supposed to be protected by. Combined with `api.insecure: true` + `api.dashboard: true` in `traefik.yml.j2`, the entire Traefik API is anonymous over `:443`.

**Live evidence** (unauthenticated GET, Host header only, no cookie or token):

| Endpoint | Result |
|---|---|
| `/api/version` | `200` → `{"Version":"3.6.23","Codename":"ramequin"}` |
| `/dashboard/` | `200` |
| `/api/overview` | `200` — 54 routers / 52 services / 13 middlewares |
| `/api/rawdata` | `200`, **35 670 bytes** — complete edge topology: every router rule, internal backend URL, port, middleware |
| `/api/http/middlewares` | `200`, 4 971 bytes — **the credential leak** |

**The critical leg is secret disclosure, not version disclosure.** `/api/http/middlewares` serves rendered `headers.customRequestHeaders` maps *verbatim*, handing an anonymous client both SEC-6 edge-trust tokens:

```
face-edge@file  -> X-Face-Edge-Token: <global_password_prefix>_pw_face_edge
wing-edge@file  -> X-Wing-Edge-Token: <64-hex>
```

Both tokens exist solely on a premise stated in `middlewares.yml.j2` itself — *"only Traefik (which holds the token) can present it"*, and `customRequestHeaders` REPLACES any client-sent value so *"a peer on `gated_net` cannot pre-poison it."* That premise is now false at the **front** of the proxy rather than behind it:

- **`X-Face-Edge-Token`** is precisely the condition under which the nOS face BFF (`src/hooks.server.ts`) trusts attacker-supplied `X-Authentik-*` identity headers → forge the pair and impersonate **any user, including `nos-admins`**.
- **`X-Wing-Edge-Token`** defeats Wing's `BasePresenter::startup()` edge gate — the second half of the SEC-6 defence-in-depth pair whose first half (the `127.0.0.1` Caddyfile bind) is bypassable the same way.

**Worst leg — prefix disclosure.** `default.credentials.yml:421` defines `face_edge_token` as the literal template `{{ global_password_prefix }}_pw_face_edge`. The leaked header therefore discloses **`global_password_prefix` in cleartext** (recovered verbatim from the anonymous response on the live host). That single string seeds every unset credential in the `{global_password_prefix}_pw_{service}` family — `woodpecker_agent_secret`, the DB passwords, `mysqld_exporter_password`, `akadmin_password`, the `authentik_oidc_*_client_secret` seed twins. An anonymous reader can **derive** them with no further interaction. This converts an information-disclosure bug into tenant-wide credential compromise.

**Reachability — stated honestly, not overclaimed.** Confirmed anonymous over HTTPS from the **LAN/Tailscale** surface: Traefik binds `0.0.0.0:443` and the only precondition is reaching the host on 443 with the right `Host` header. The hostname *is* publicly resolvable (`dig @1.1.1.1` → Cloudflare `188.114.96.9/97.9`), but **internet reachability could not be verified from inside the LAN**: split-horizon dnsmasq resolves the name to the host's own LAN address, so this batch's "public" curl provably transited the LAN (`remote_ip` was the `192.168.x` host), *not* the Cloudflare edge. Whether CF proxies through to this origin must be checked from an off-net vantage point before rating internet exposure.

**Action** — any one closes the anonymous leg; do at least (1) and (3):

1. Set `traefik_auth_modes.traefik: 'proxy'` so `authentik@file` gates the router, or add `traefik` to `traefik_skip_ids` so no edge router is derived. This is a Tier-1 admin surface; `none` was never defensible for it.
2. Set `api.insecure: false` in `traefik.yml.j2` — defence in depth even after (1).
3. **Independently of the routing fix, treat the exposed values as burned:** rotate `global_password_prefix`, `wing_edge_token`, `face_edge_token`. Stop deriving edge tokens from the prefix — `default.credentials.yml:420-421` already carries an `openssl rand -hex 32` comment that `wing_edge_token` honours (it rendered as 64-hex) and `face_edge_token` does **not** (it rendered as the prefix template). Making it independently generated removes the prefix-disclosure leg even if a header leaks again.
4. Consider a repo gate asserting no manifest entry with a `domain_var` maps to auth mode `none` without an explicit allowlist.

**General lesson — the sharper mirror of batch-34's.** Batch-34 established that `traefik_auth_modes: 'oidc'` means *the edge is open and the app's own login is the only gate*. This batch establishes the harder form: **`'none'` means the edge is open and there is no gate at all** — which, for an infrastructure surface with no login of its own, is simply an anonymous admin API.

### 🟠 HIGH — [REM-145, GHSA-3ccp-42pg-hgv6, no CVE assigned] Traefik — unauthenticated cross-user response poisoning via proxied CONNECT

Published **2026-07-27**, twelve days after the last traefik look and three days after the fix releases. CVSS 4.0 **7.0** (`AV:N/AC:L/AT:P/PR:N/UI:N/VC:N/VI:N/VA:N/SC:H/SI:H/SA:N`), CWE-444. Affects v2.x ≤ 2.11.52 (fix 2.11.53), **v3.6 ≤ 3.6.23 (fix 3.6.24)**, v3.7 ≤ 3.7.8 (fix 3.7.9) — all shipped 2026-07-24. The pinned `v3.6.23` is the **top** of the affected v3.6 range.

`httputil.ReverseProxy` forwards a client `CONNECT` — with a live body stream — to an HTTP/1.1 upstream instead of rejecting it. If the upstream answers a keep-alive **non-2xx without draining the body**, the desynchronised socket returns to Traefik's **shared** connection pool, and the next client to draw it receives responses queued from the attacker's smuggled requests. With a bounded pool, one desync can poison an entire response queue.

Both preconditions were **verified live, not assumed**:
- **Frontend must be HTTP/2 or HTTP/3** — every edge probe in this batch returned literal `HTTP/2 200` (TLS on `websecure`, h2 via ALPN). HTTP/1.1 frontends are unaffected.
- **Backend must answer keep-alive non-2xx without draining** — the advisory names Go `net/http` and gunicorn/Flask as still exploitable, and nOS's upstream fleet is full of both: woodpecker-server is Go `net/http`, calibre-web is Flask/Werkzeug (live-confirmed `302 FOUND`).

The default `sanitizePath` is only an **incomplete** mitigation. Not provider-specific.

**Action:** bump `v3.6.23` → `v3.6.24` in `default.config.yml:1869` **and** `roles/pazny.traefik/defaults/main.yml:16` together. Patch-level, no config change. If deferred: `maxIdleConnsPerHost: -1` (disables backend pooling) or the experimental FastProxy implementation.

*N/A this batch:* GHSA-8rxv-jg7p-wvg3 (HIGH, 2026-07-16, Ingress-NGINX RewriteTarget auth bypass) is the **Kubernetes** Ingress-NGINX provider only; nOS runs the Docker + file providers.

### 🟡 MEDIUM — [REM-148, CVE-2026-45618] Uptime Kuma — LiquidJS RCE in notification templates *(and the REM-073 bump silently broke the service)*

The CVE is the smaller half. `CVE-2026-45618` / `GHSA-gf2q-c269-pqgc` is a LiquidJS RCE (`1|valueOf` → `this` filter escape) affecting `liquidjs < 10.26.0`; Uptime Kuma uses LiquidJS for notification templates and shipped the dependency fix in **2.4.0** under an explicit *"Security Fixes"* heading, qualified upstream as *(Admin only/Authenticated only)*. There is **no louislam/uptime-kuma GHSA** for it — release-note-only, invisible to version-keyed scanners, the same detection gap batch-37 recorded for freescout. The pin `2.2.1` predates 2.4.0.

**The operational finding is more urgent than the CVE.** REM-073's `1.23.13 → 2.2.1` major bump (applied 2026-07-24) did close the SSTI — and left the service dead. The container has sat in the 2.x first-run setup wizard for six days: `GET /` → `302 /setup-database`, log ending `2026-07-24T20:49:45Z` with *"db-config.json is not found or invalid: ENOENT … Waiting for user action…"*, and a **zero-byte `kuma.db`** in the data volume. The 1.x database did not survive the major bump.

1. **Uptime monitoring — itself a security control, and the substrate A9 notification fanout leans on — has been dark since 2026-07-24**, uncaught because the container reports *running* and *healthy*.
2. The instance sits in an **uninitialised setup window** — structurally the Portainer `CVE-2026-55761` class from batch-35, differing only in that Authentik gates the route. Not anonymous, but any authenticated Tier-3 SSO user who browses there can complete the wizard and take the instance as admin.

**Action:** restore the service first (complete/automate `setup-database`, re-provision monitors) and add a probe that **fails** on a `302 → /setup-database`, so a dark monitor stack cannot pass as healthy again. Then bump `2.2.1 → 2.4.0` and re-sync `roles/pazny.uptime_kuma/defaults/main.yml:16` off its stale `"1"` track.

### 🔵 LOW — [REM-146 woodpecker, REM-147 jellyfin] The probe's nominal quarry

Both are anonymous **version oracles at the edge**, and both are anonymous for the same structural reason: `traefik_auth_modes` `'oidc'` attaches no edge middleware.

- **woodpecker** — `GET https://ci.<tld>/version` → `200 {"version":"3.14.1"}`; `/` → `200` SPA shell. No version-bearing *header* (Go `net/http` emits none), so this is body-level. CVE leg clean: OSV for `woodpecker/v3@3.14.1` returns only GHSA-qf34-295c-26v8 (CVE-2026-61549), **Kubernetes-backend-only** and N/A since `WOODPECKER_BACKEND=docker`.
  **Disposition correction, worth more than the finding:** batch-16, batch-28 *and* the CLAUDE.md SSO trichotomy all record woodpecker as `forward_auth`/route-gated. It is not — `traefik_auth_modes.woodpecker: 'oidc'`, deliberately (a forward-auth gate would be the documented double-login anti-pattern and would 302 the playbook's own Woodpecker API post-wiring). The recorded mitigation was materially false.
- **jellyfin** — the clearest textbook case, leaking on **both** channels: header `Server: Kestrel`, and `GET /System/Info/Public` → `200` with exact `Version`, container hostname as `ServerName`, and a stable 32-hex server `Id`. Reachable by a **second independent path**: `jellyfin_lan_access` defaults `true`, so the container publishes `0.0.0.0:8096` and the SSO-Auth plugin does not gate the raw port. CVE leg clean at `10.11.10` — every repo advisory re-pulled with fix versions sits at or below the pin. *(v12.0 is at rc3 — pre-release, do not move to it.)*

Filed as LOW because both are pure information disclosure — but an exact-version oracle at an internet-facing edge is what makes the *next* unauth advisory instantly targetable. Note also that `security-headers@file` **strips nothing**: it only adds HSTS/nosniff/XSS/referrer, so any upstream `Server` or `X-Powered-By` passes through the edge untouched.

### ✅ Clean / re-verified — calibreweb

The best-behaved service in the batch, and the control case that makes the pattern legible. `0.6.26` is still the newest janeczku release (previous: 0.6.25, Aug-2025), the repo has **zero** published GitHub advisories, and OSV returns nothing for `calibreweb@0.6.26`. REM-074 and REM-120 stay resolved via the SEC-02 architectural mitigation. *(CVE-2026-25635 and CVE-2026-27810 are upstream **Calibre**, not calibre-web — ruled out again.)*

Probe result **fully mitigated**, both paths: anonymous edge `GET` → `HTTP/2 302` to Authentik (`authentik@file` fires before the app); on the direct loopback port the app leaks no version and **no `Server` header at all**, and sets CSP + `X-Content-Type-Options` + `X-Frame-Options` + HSTS unprompted. `127.0.0.1:8083` + `gated_net` only.

**Standing note, no queue item yet — it deserves one.** The compose template loads `DOCKER_MODS=linuxserver/mods:universal-calibre`, installing the upstream **Calibre binaries inside this image** for ebook conversion. That is an untracked version surface: upstream Calibre CVEs land in this container via the conversion path even though they are not calibre-web bugs, and neither `versions.json` nor any pin covers the mod.

---

# nOS Vulnerability Scan Addendum — 2026-07-29 (Cycle 16, batch-37)

**Batch:** paperclip, tileserver, superset, outline, freescout · **Probe:** unauthenticated_endpoint_scan
**Outcome:** 2 queue items added (REM-142 freescout MEDIUM, REM-143 paperclip LOW); 2 dispositions changed to resolved (**REM-104 outline**, **REM-117 tileserver**); superset clean/re-verified. The batch's only **CRITICAL is N/A** — a CVSS 9.6 *unpatched* drive-by RCE that explicitly defeats a `127.0.0.1` bind, ruled out by reading the pinned commit's own source rather than trusting the advisory prose. The batch's actionable finding is the opposite shape: a **MEDIUM with no CVE at all**, invisible to every version-keyed scanner.

### 🔴 CRITICAL — [GHSA-x8hx-rhr2-9rf7, no CVE] Paperclip — Unauthenticated Drive-By RCE via DNS Rebinding, UNPATCHED — **NOT APPLICABLE (config-verified)**
- **Component:** paperclip (devops stack, `ghcr.io/paperclipai/paperclip:sha-b9a80dc`; `default.config.yml:2206` + `roles/pazny.paperclip/defaults/main.yml:11`; `install_paperclip` default-on)
- **Why it appears here despite being N/A:** it is the first advisory in this scan series that **attacks the loopback bind itself**. Nearly every "mitigated" verdict in this queue leans on `127.0.0.1:<port>` + a Traefik forward-auth gate. This bug routes *around both* — so the N/A verdict had to be earned from source, not asserted from posture.
- **The advisory** (published **2026-07-22**, nine days after the batch-27 re-check; **CVSS 9.6** `AV:N/AC:L/PR:N/UI:R/S:C/C:H/I:H/A:H`; CWE-862 + CWE-1188; affected range `<0.3.1`; **`patched_versions` field is EMPTY — unpatched at publication**): the attacker registers a domain with **two A records** — their own IP and `127.0.0.1` — serves a page with exploit JS, then **shuts the server down**. The browser's next `fetch()` fails over to the second A record, reaching `127.0.0.1` **under the same origin**, so no CORS applies. The JS then `POST`s `/api/companies/import` to create a `process`-adapter agent and `POST`s `/api/agents/:id/wakeup` to spawn it → **arbitrary commands as the Paperclip OS user**. The victim only visited a webpage; no clicks, no credentials. The researcher verified it end-to-end on macOS/Firefox.
- **Three stated root causes:** (1) `local_trusted` mode auto-authenticates every request as instance admin; (2) no Host-header validation in `local_trusted` (the hostname guard is active only for `authenticated` + `private`); (3) the `process` adapter spawns commands unsandboxed. Upstream's own note: **"Fixing #2 alone kills this attack."**
- **PROBE result (unauth_endpoint_scan) — N/A, two independent controls, both verified at the pinned commit `ref=b9a80dc` (not against `main`):**
  1. **Root cause #1 is absent.** `roles/pazny.paperclip/templates/compose.yml.j2:32` sets `PAPERCLIP_DEPLOYMENT_MODE: "authenticated"`, and `server/src/middleware/auth.ts@b9a80dc:25` scopes the auto-admin actor (`{isInstanceAdmin: true, source: "local_implicit"}`) to `deploymentMode === "local_trusted"` **only**. A rebound request arrives as actor `{type: "none"}` — the import/wakeup chain needs credentials it does not have.
  2. **Root cause #2 is closed.** `server/src/config.ts@b9a80dc:179` defaults `deploymentExposure` to **`"private"`** when `PAPERCLIP_DEPLOYMENT_EXPOSURE` is unset (nOS does not set it), and `server/src/app.ts@b9a80dc:96-97` enables the guard for `exposure === "private" && (local_trusted || authenticated)` → **the Host-header guard is ACTIVE on the pinned build.** `private-hostname-guard.ts@b9a80dc` reads `x-forwarded-host` then `host` and **403s** any hostname outside `{localhost, 127.0.0.1, ::1}` ∪ the registered allowlist — which `roles/pazny.paperclip/tasks/post.yml:65-84` populates **narrowly**, via `pnpm paperclipai allowed-hostname {{ paperclip_domain }}` plus `service_extra_hosts`. An attacker's rebinding domain is never on that list.
- **⚠ Forward risk this bounds — the one thing to never do:** the hostname guard is **silently disabled** by setting `PAPERCLIP_DEPLOYMENT_EXPOSURE` to any non-`private` value. Treat that env var as security-relevant and **never introduce it as a route-debugging workaround**; the correct fix for a blocked hostname is to register it through the `post.yml` allowlist task. The guard is the only structural defense against this class, and root cause #3 (unsandboxed `spawn()`) is unfixed upstream.
- **Remediation:** **none required for the CRITICAL.** Separately, the standing "repin off the floating feature-SHA" advice is now concretely actionable — see below. → **REM-143** (LOW, currency leg only)
- **Source:** https://github.com/PaperclipAI/paperclip/security/advisories/GHSA-x8hx-rhr2-9rf7 · `gh api repos/paperclipai/paperclip/contents/server/src/{app.ts,config.ts,middleware/auth.ts,middleware/private-hostname-guard.ts}?ref=b9a80dc`

### ⚠ MEDIUM — [7 GHSA refs, **6 of them UNPUBLISHED**, no CVE] FreeScout 1.8.226 — Three Security Releases Behind, Invisible to Version-Keyed Scanning — PENDING
- **Component:** freescout (b2b stack, `nfrastack/freescout:2.1.3-php8.3` → app **1.8.226**; `default.config.yml:2008` + `roles/pazny.freescout/defaults/main.yml:9` in sync; `install_freescout` **default-on**)
- **Successor to REM-118, not a re-open:** that bump was correct and stays resolved — it closed CVE-2026-53595 (9.4 unauth account takeover) and three companions. But the image was published **2026-06-27**, and upstream has since shipped **five** app releases, **three** of them security releases: **1.8.227** (07-04, `GHSA-v8vc-cmf9-gg2c`), **1.8.230** (07-18, *"Improved remote URL sanitizing"* `GHSA-6w8v-qp43-vg2h` + *"Send CSP header in `/ajax-html/` URLs"* `GHSA-2g42-f97q-973x`), **1.8.231** (07-25, *"Check customer visibility in `load_customer_info` ajax action"* `GHSA-cr68-27qv-p5m4` + *"Restricted access to Assigned Conversations option in user profiles"* `GHSA-m4hc-rc98-38jc` + *"Change customer when received a reply to a conversation from completely new email address"* `GHSA-j49f-9g94-3wh4` + *"Tighten throttling in Forgot Password requests"* `GHSA-jvmv-2qcp-7855`).
- **Why this is filed despite having no CVE — the detection-evasion point:** **six of those seven GHSA IDs are UNPUBLISHED** in the GitHub global advisory database. `gh api advisories/<id>` returns **404** for `GHSA-v8vc-cmf9-gg2c`, `GHSA-6w8v-qp43-vg2h`, `GHSA-2g42-f97q-973x`, `GHSA-cr68-27qv-p5m4`, `GHSA-m4hc-rc98-38jc` and `GHSA-j49f-9g94-3wh4`, and none appears among the repo's **93 published** advisories. These are real security fixes, shipped in tagged releases, with **no CVE, no CVSS and no affected-range metadata** — so OSV, NVD and any version-keyed scanner report the pin **clean**. Only the release-note prose reveals them. **Confidence: HIGH on the version-lag fact, MEDIUM on severity** (there is no published vector to score). The single *published* ID, `GHSA-jvmv-2qcp-7855` / **CVE-2026-45294** (MODERATE 5.3, unauth agent-email enumeration via password-reset response differentiation), patches at **1.8.219** — already covered; 1.8.231 merely tightens its throttling.
- **Re-verified covered, no action (the pin is sufficient):** the whole **2026-07-15 published batch** patches at ≤ 1.8.226 — `GHSA-gh3r-jh6q-wrvj` / **CVE-2026-62856** (HIGH 7.7, cross-user notification disclosure via **LIKE-wildcard injection** in the polycast channel query; notable because the polycast routes **lack the auth middleware**, so any visitor holding a session + CSRF token reaches it — a probe-relevant near-unauth leg had the pin been older), `GHSA-jpq8-j69f-mj98` / **CVE-2026-62854** (HIGH 7.6, stored XSS in mailbox signature via same-origin JS upload, defeating `script-src 'self'`), `CVE-2026-62852` (MED 6.5), `CVE-2026-62851` (MED 4.3), `CVE-2026-62855` + `CVE-2026-62850` (≤ 1.8.225).
- **PROBE result (unauth_endpoint_scan):** `traefik_auth_modes.freescout = 'oidc'` → native OIDC, **200 at edge**, FreeScout owns its login page and is **not** forward-auth gated; `127.0.0.1:8090` loopback blocks the direct port but **not** the Traefik route. Probe-relevant residual inside the unpublished set: **`GHSA-j49f-9g94-3wh4`** rebinds a conversation's customer when a reply arrives from a *completely new email address* — **inbound email is an unauthenticated input channel**, and this is the same class as the previously-patched CVE-2026-53591 thread-injection leg, making it the most likely pre-auth item in the batch. **Unconfirmed** — the advisory is unpublished, so no range or vector is available.
- **Remediation:** bump `freescout_version` **`2.1.3-php8.3` → `2.1.5-php8.3`** in **both** `default.config.yml:2008` **and** `roles/pazny.freescout/defaults/main.yml:9` (version-pin-shadow rule). 2.1.5-php8.3 (2026-07-18) is a **drop-in**: same nfrastack 2.1.x scheme, same php8.3 variant, `linux/arm64` present, bundles app **1.8.230** → clears the 1.8.227 + 1.8.230 GHSAs. **⚠ Caveat on going further:** app 1.8.231 ships **only** in image **2.2.1**, and the 2.2.x line publishes **no php8.3 variant** — only `2.2.1-php8.5`, `2.2.1-alpine`, `latest`. Reaching 1.8.231 therefore means a **PHP 8.3 → 8.5 runtime jump** layered on the app bump, the same image-rescheme risk class REM-118 navigated on `php8.3-1.17.x → 2.x.x`. Take the 2.1.5-php8.3 drop-in now; treat 2.2.1 as a separately-verified move once php8.5 compatibility is exercised (or wait for a 2.2.x php8.3 tag). → **REM-142**
- **Source:** https://github.com/freescout-help-desk/freescout/releases/tag/1.8.231 · .../1.8.230 · .../1.8.227 · https://github.com/nfrastack/container-freescout/blob/main/CHANGELOG.md · https://hub.docker.com/v2/repositories/nfrastack/freescout/tags · `gh api repos/freescout-help-desk/freescout/security-advisories` (93 published)

### Covered / not-applicable / re-verified this batch (no new item)
- **outline** (`outlinewiki/outline:1.8.1`): **NOW CLEAN — REM-104 RESOLVED.** The pin advanced `1.8.0-1 → 1.8.1` (`default.config.yml:2027` + role default in sync), closing the item's whole target set: the LOW **unauth timing oracle** `GHSA-wgqc-257g-78v3` (non-constant-time token compare in `notifications.unsubscribe` + `subscriptions.delete`, patched *exactly* at 1.8.1) plus `GHSA-33jq-x32c-3ccw` (webhook survives creator deletion) and `GHSA-pp65-6cc2-4mx9` (MCP `list_documents` metadata leak), both 1.8.0. **CVE-clean at the pin:** across every advisory published since 2026-05-01 the **highest `patched_versions` on record is 1.8.1** — nothing is fixed above it — including `GHSA-5x79-rj4g-qrh8` / CVE-2026-54573 (HIGH, API-key/OAuth scope authz bypass via path-parsing discrepancy, 1.8.0) and the May cluster (CVE-2026-43886 8.2, CVE-2026-43888 8.7, CVE-2026-43889/43890/44695, all ≤ 1.7.1). **New but covered:** `GHSA-c43v-wwv4-9mcc` (MODERATE 6.5, published **2026-07-27** — two days ago, post-dating the batch-28 check: Viewer users publish into restricted collections via the MCP workflow) patches at 1.8.0, already below the pin. Slack items N/A (native Authentik OIDC, no Slack). **Currency note, no item filed:** upstream is at **v1.9.2** (07-21) via v1.9.0/v1.9.1 — the pin trails one minor line; fold into the next planned bump, since a future advisory could be 1.9-only with no 1.8.x backport. Probe: `traefik_auth_modes.outline='oidc'` (200 at edge, not forward-auth gated), `127.0.0.1:3005` loopback, Tier 3 — the token-gated unsubscribe/delete endpoints were the only anonymous surface and their timing oracle is now patched. Source: `gh api repos/outline/outline/security-advisories`
- **tileserver** (`maptiler/tileserver-gl:v5.6.0`): **NOW CLEAN — REM-117 RESOLVED.** The version-pin **shadow is closed**: `default.config.yml:1295` now pins `maps_tileserver_version: "v5.6.0"` (was floating `latest`) and `roles/pazny.offline_maps/defaults/main.yml:14` matches — effective tag immutable. v5.6.0 (2026-04-06) is **also the latest stable**; the only newer tags are pre-releases (`v5.7.0-pre.0`, `v5.6.1-pre.0`), so the pin is simultaneously reproducible *and* current — pinning to a `-pre` tag would reintroduce supply-chain risk for no security gain. CVE leg clean for the third consecutive batch: `gh api repos/maptiler/tileserver-gl/security-advisories` returns an **empty list** (zero advisories ever published); CVE-2024-35627 (XSS ≤ 4.4.10) and CVE-2025-46653 (DoS, fixed 5.3.0-r1) predate any pin; CVE-2025-44136/44137 remain **MapTiler Tileserver-PHP**, a different product = N/A. Standing caveat: *zero advisories ever* also means **no disclosure channel to watch** — perimeter posture is the durable control (same shape as bluesky_pds / infisical). Probe: `traefik_auth_modes.offline_maps='none'` — public tiles **by design**, no Authentik provider, anonymously reachable *when enabled* — but `install_offline_maps=false` (`default.config.yml:417`) and a `127.0.0.1:8070` bind → **no live surface**; the `--public_url`-absent header-reflection vector stays **theoretical** (Traefik fixes Host upstream).
- **superset** (`apache/superset:6.0.0-dev`): **CLEAN/re-verified — third consecutive re-confirm.** Checked against the **authoritative ASF** "CVEs fixed by release" page this batch, decisive on the only question that matters: **no CVE is listed as fixed in any release after 6.0.0.** The page attributes exactly four to 6.0.0 — CVE-2026-23980 (SQL neutralisation), CVE-2026-23982 (authz bypass in dataset creation), CVE-2026-23983 (user-info disclosure via the Tag endpoint, **disabled by default**), CVE-2026-23984 (read-only bypass on PostgreSQL) — all **authenticated**, all covered; **nothing** is attributed to 6.0.1 or 6.1.0 (6.1.0 shipped 2026-05-13, hygiene-only). The newest Superset CVE ID in existence remains CVE-2026-23984 from the Feb-24-2026 batch, unchanged across four scans. CVE-2026-23969 (ClickHouse SQLi) stays N/A — no ClickHouse. Probe: `traefik_auth_modes.superset='oidc'` (`SUPERSET_AUTH_TYPE=AUTH_OAUTH`, 200 at edge, own `/login` + Sign-in-with-Authentik, not forward-auth gated), `127.0.0.1:8089` loopback, Tier 2, `/health` intentionally public — **zero unauth CVE in the window**, so the anonymous surface is the login page and health probe only. Standing caveat unchanged: `6.0.0-dev` is a floating **pre-release** tag retained **deliberately** — `apache/superset:6.0.0` (non-dev) ships without any PostgreSQL Python driver and crash-loops on `ModuleNotFoundError: psycopg2`, so the `-dev` variant is load-bearing. A reproducibility gap (class of REM-141/135/143), not a CVE. Source: https://superset.apache.org/admin-docs/security/cves/

---

# nOS Vulnerability Scan Addendum — 2026-07-27 (Cycle 16, batch-35)

**Batch:** bluesky_pds, postgres, portainer, gitea, openwebui · **Probe:** unauthenticated_endpoint_scan
**Outcome:** 2 queue items added (REM-137 gitea **CRITICAL**, REM-138 openwebui HIGH); 3 components clean/re-verified (bluesky_pds, postgresql, **portainer — REM-100 resolved**). This batch **overturns two prior "clean/covered" dispositions on a timing technicality**: Gitea 1.27.0 landed **~37 hours after** batch-26 declared 1.26.4 "still the latest and CVE-clean", and Open WebUI 0.10.0 landed **8 days after** the 0.9.6 that batch-26 recommended as the fix. Both are cases where the pin moved *correctly* and the target moved again underneath it.

### 🔴 CRITICAL — [CVE-2026-58443 + CVE-2026-56750 + CVE-2026-58436, 36-CVE wave] Gitea 1.26.4 — Largest Advisory Wave in Project History, No 1.26.x Backport — PENDING
- **Component:** gitea (devops stack, `gitea/gitea:1.26.4`; `default.config.yml:1374` + `roles/pazny.gitea/defaults/main.yml:10` in sync; `install_gitea` default-on — Woodpecker CI's forge)
- **Why this overturns batch-26's "NOW CLEAN":** the 2026-07-12T04:02:42+02:00 scan predated **Gitea 1.27.0, published 2026-07-13T17:07:36Z**. An OSV version-aware query for `code.gitea.io/gitea@1.26.4` returns **37 vulnerabilities, 36 of them `fixed: 1.27.0`**. There is **no 1.26.5 and no 1.27.1** — the releases API lists `v1.27.0` as the newest tag and *every* advisory in the wave names 1.27.0 as the **sole** patched version. The 1.26 line got **no backport**, so the pin sits at the top of every affected range.
- **CVE-2026-58443** (GHSA-xxjv-752h-3vp2, **CVSS 9.6 CRITICAL**, affects ≤ v1.26.4) — a `public-only,write:repository` token can **update private pull-request head branches**: the public-only restriction is validated only against the *route* repository (the public base) and never against the private head repo receiving the push. **Public PoC exploit code is disclosed.** Requires a valid public-only write token for a user with normal write permission to the private head branch.
- **CVE-2026-56750** (GHSA-rgv6-xp99-6mgj, **CVSS 9.1 CRITICAL**) — **Remember-Me token theft does not invalidate the attacker's session.** On a token-hash mismatch (i.e. exactly when compromise is detected) Gitea deletes only the *victim's* local cookie and leaves the *attacker's* database session intact, defeating the split-token model and granting **indefinite persistent access** to the victim's account.
- **PROBE result (unauth_endpoint_scan) — GENUINE pre-auth leg, EDGE-REACHABLE:** **CVE-2026-58436** (GHSA-fw57-jgch-pgf3, **HIGH CVSS 8.7**, affects 1.22.6 → 1.26.x) — `ParseAcceptLanguage` **quadratic-time DoS via the Locale middleware on unauthenticated requests**. The middleware runs in front of *every* HTTP request and calls `golang.org/x/text` `language.ParseAcceptLanguage` on the raw `Accept-Language` header with no size or shape filter. The CVE-2022-32149 guard added in x/text v0.3.8 caps `-` characters at 1000 but **not `_`**, even though the parser's scanner aliases `_` → `-` before parsing — so an underscore-built header re-enters the quadratic path. **One unauthenticated GET pins one CPU core for ~2 s per 1 MiB of header**; ten concurrent clients saturate a ten-core host for ~1 MiB/request of upstream bandwidth, and the endpoint **returns 200 OK**, so the attack never surfaces on 4xx/5xx dashboards.
  - **Edge reachability:** `traefik_auth_modes.gitea = 'oidc'` → native_oidc with **no** forward-auth middleware, so the router answers **200 anonymously** and the Locale middleware fires on the landing and sign-in pages, before any credential is presented. The `127.0.0.1:3003` loopback host-bind gates only the direct container port, not the Traefik path.
  - **Bounding:** impact is **availability-only** (no data disclosure) — which is why this item is filed CRITICAL on the 58443/56750 legs rather than on the DoS. Both CRITICALs are **authenticated** (a valid public-only write token / a prior remember-me token theft), and registration is **external-only** per the pure-SSO doctrine, so the token-holder population is bounded to SSO-provisioned users.
- **Other HIGH in the wave (all fixed 1.27.0):** CVE-2026-56755 (O(N²) string concat in Debian package upload → CPU+memory exhaustion), **CVE-2026-55987** (OAuth2 sign-in **reactivates an administrator-deactivated account** on auth sources without refresh tokens — directly relevant: Gitea's auth source *is* Authentik OIDC), CVE-2026-56654 (access-token scope escalation in API), CVE-2026-58314 (two SSRF), CVE-2026-57894 (repo migration follows git HTTP redirects *after* allow/block validation → internal-git exfiltration), CVE-2026-58437 (repository visibility manipulation via git push options), CVE-2026-54481 (internal API HTTP client hardcodes `InsecureSkipVerify: true` with no config override).
- **~20 MODERATE:** SSRF cluster (CVE-2026-59765 / 58442 / 58441), PAT & public-only scope bypasses (CVE-2026-58444 / 58429 / 56443 / 50105), private-repo existence disclosure via the `go-get` meta endpoint (CVE-2026-58507), OIDC `userinfo` returns identity claims without enforcing token scopes (CVE-2026-55982), revoked-user private-object reads (CVE-2026-59766, sibling of CVE-2026-20800), SSH key parser DoS (CVE-2026-56657), NPM tag endpoint unbounded `io.ReadAll` DoS (CVE-2026-42931). Plus ~5 LOW.
- **Separate, NOT closed by this bump:** GHSA-263q-5cv3-xq9g / CVE-2025-68939 (HIGH, forbidden-extension release attachments) still lists **no fixed version** in OSV. 1.27.0 fixes the web-form *variant* (CVE-2026-58428) only; the parent record remains open upstream. Lineage note.
- **Remediation:** bump `gitea_version` **1.26.4 → 1.27.0** in **both** `default.config.yml:1374` **and** `roles/pazny.gitea/defaults/main.yml:10` (version-pin-shadow rule — `default.config.yml` wins at runtime). **Machinery gap:** `upgrades/gitea.yml` is scoped `from_regex: "^1\.25\."` so it does **not** match a 1.26.x install — widen it or author a 1.26→1.27 sibling recipe before the agent-driven upgrade path can execute this, exactly as `2026-07-09-gitea-1-25-5-to-1-26-4` did for the previous jump. Minor-line move: forward-only in-container migrations on first boot, no coexistence track. No 1.26.3-style regression is documented for 1.27.0 as of this scan. → **REM-137**
- **Source:** https://github.com/go-gitea/gitea/security/advisories/GHSA-xxjv-752h-3vp2 · https://github.com/advisories/GHSA-rgv6-xp99-6mgj · https://github.com/advisories/GHSA-fw57-jgch-pgf3 · https://blog.gitea.com/release-of-1.27.0/ · https://securityonline.info/gitea-vulnerability/ · OSV version-aware query `code.gitea.io/gitea@1.26.4` (37 vulns)

### ⚠ HIGH — [CVE-2026-59216 + 59219 + 59221 + 59214 + 59224 + 59714 + CVE-2026-59715] Open WebUI 0.9.6 — 18-CVE 0.10.0 Wave, incl. the First Unauthenticated Leg Since the N/A LDAP Critical — PENDING
- **Component:** openwebui (iiab stack, `ghcr.io/open-webui/open-webui:0.9.6`; `default.config.yml:1532` + `roles/pazny.open_webui/defaults/main.yml:13` in sync)
- **Why this is REM-101's *successor*, not a re-open:** the pin **correctly** advanced 0.8.12 → 0.9.6 and REM-101 is properly closed. But 0.9.6 (PyPI 2026-06-01) was superseded **eight days later** — **0.10.0** shipped 2026-06-29 and **0.10.2** (latest, 2026-07-01) carries an explicit upstream *"Security Advisory … update production deployments at your earliest convenience"* banner. OSV for `PyPI open-webui@0.9.6` returns **18 vulnerabilities, all `fixed: 0.10.0`**, disclosed as a coordinated 2026-06-29 / 2026-07-02 wave. 0.9.6 is the **last affected version** on every one.
- **Six HIGH:** **CVE-2026-59216** (GHSA-74h3-cxq7-vc5q, 7.7) — an authenticated **low-privilege** user executes arbitrary code-interpreter Python **and tools inside *another user's* authenticated session**, via an unvalidated Socket.IO event-caller `session_id`; the most severe leg. **CVE-2026-59219** (GHSA-855v-hq7w-jmjw, 7.1) — realtime endpoints accept **Redis-revoked JWTs after sign-out / OIDC back-channel logout**: a stolen token keeps authenticating new Socket.IO/websocket connections while HTTP endpoints correctly 401. *Redis-configured deployments only — which nOS is* — and it directly defeats the back-channel logout the SSO doctrine relies on. **CVE-2026-59221** (GHSA-frvj-c5qp-xj4w, 7.7) — terminal-proxy path-traversal guard bypass: `_sanitize_proxy_path()` decodes only 8 iterations, so a 9× percent-encoded `../admin/system` passes validation *still encoded* and the upstream terminal server decodes it, forwarding terminal credentials outside the intended path. **CVE-2026-59214** (stored web-worker XSS via Pyodide), **CVE-2026-59224** (terminal proxy forwards a **spoofable, integrity-unbound** user identity header upstream), **CVE-2026-59714** (cross-channel message overwrite via the chat-completion API).
- **Eight MODERATE:** CVE-2026-59212 (model `meta.knowledge` read-only file access upgradable to **write/delete**), 59217 (upload `metadata.knowledge_id` bypasses the knowledge-base write-access check), 59218 (account enumeration via observable login-timing discrepancy), 59220 (ReDoS in skill-mention regexes → **whole-instance DoS on the default config**), 59222 (`/api/v1/channels/{id}/members` exposes the **full user model including sensitive credentials**), 59223 (`WEB_FETCH_FILTER_LIST` host allow/block bypassable via URL path and non-label-boundary matching), 59225 (arena task endpoints bypass model access controls), 59227 (`POST /api/v1/images/edit` bypasses the global image-edit switch and the per-user image-gen permission). **Four LOW:** 59213, 59215, 59226, 59715.
- **PROBE result (unauth_endpoint_scan) — one genuine unauth leg, the first Open WebUI pre-auth finding since the N/A LDAP critical:** **CVE-2026-59715** (GHSA-gmfw-g93r-vg53, **LOW CVSS 3.1**, affects ≥ 0.6.16 < 0.10.0) — the Socket.IO server is configured `always_connect=True` and two Ydoc collaborative-document handlers (`ydoc:awareness:update`, `ydoc:document:leave`) perform **no authentication check at all**. An anonymous client can open a websocket, **spoof any user's presence/cursor/selection** in collaborative documents, broadcast fake departure events, and hold **unlimited unauthenticated connections** to exhaust server capacity. Rated LOW upstream (integrity/availability of a collaboration overlay, no data read). Edge-reachable: `traefik_auth_modes.open_webui = 'oidc'` is native_oidc with **no** forward-auth middleware, so the router answers 200 anonymously; the `127.0.0.1:3004` loopback binds only the direct container port. **Every other leg requires an authenticated session** (`WEBUI_AUTH=true` + Authentik OIDC + local signup disabled per the pure-SSO onboarding doctrine), so practical exposure is **authenticated-insider cross-user compromise**.
- **Remediation:** bump `openwebui_version` **0.9.6 → 0.10.2** in **both** `default.config.yml:1532` and `roles/pazny.open_webui/defaults/main.yml:13`. **0.10.0 is the minimum safe version**; 0.10.2 is latest and adds the upstream-flagged access-control fixes plus the Brotli CVE-2025-6176 dependency update. Expect a first-boot DB migration, same class as the 0.8 → 0.9 move. **REM-064** (CVE-2026-0765/0766, ZDI-26-031/032, admin-gated tool/function code-exec) remains **wontfix / vendor-disputed** and is **not** closed by 0.10.2 — keep tool/function authoring restricted to trusted admins. → **REM-138**
- **Source:** OSV version-aware query `PyPI open-webui@0.9.6` (18 vulns) · https://github.com/open-webui/open-webui/security/advisories/GHSA-74h3-cxq7-vc5q · https://github.com/open-webui/open-webui/security/advisories/GHSA-855v-hq7w-jmjw · https://github.com/open-webui/open-webui/security/advisories/GHSA-frvj-c5qp-xj4w · https://github.com/open-webui/open-webui/security/advisories/GHSA-gmfw-g93r-vg53 · https://github.com/open-webui/open-webui/releases

### Covered / not-applicable / re-verified this batch (no new item)
- **portainer** (`portainer/portainer-ce:2.33.8`): **NOW CLEAN — REM-100 RESOLVED.** The pin advanced `2.27.3 → 2.33.8`, moving off the EOL 2.27 LTS onto the supported **2.33 LTS** (2.33.8-LTS, 2026-05-07) and clearing the whole container-escape cluster — CVE-2026-44848 (CRIT 9.4, missing authz on Docker `/plugins/*` → non-admin installs and enables an arbitrary plugin with `CAP_SYS_ADMIN` + host mounts = host RCE), CVE-2026-44849 (CRIT 9.4, the Swarm service API applies only 1 of the 7 `EndpointSecuritySettings` restrictions), CVE-2026-44850, and the HIGH file-read / JWT-in-URL set. **New this batch, N/A by range + forward caveat:** **CVE-2026-55761** (GHSA-x626-fcwx-f5pc, HIGH 7.1, published 2026-07-02) — *unauthenticated* admin takeover on **uninitialised** instances: during the five-minute post-startup setup window `/api/restore` and `/api/users/admin/init` are reachable with no credentials, so an attacker replaces the DB with a malicious backup or simply creates an admin account → full host compromise via the Docker socket. Affects **2.39.0–2.39.3 and 2.40.0–2.42.x**, fixed **2.39.4 / 2.43.0** — 2.33.8 is **outside** the range (this is a 2.39+ setup-token regression). ⚠ **Caveat:** REM-100's old alternate target *2.39.2* is itself vulnerable to this — if ever leaving the 2.33 LTS, go to **2.39.4+ or 2.43.0**, never 2.39.0–2.42.x. Probe: no unauth exposure — even the generic setup-window class is closed structurally, since `roles/pazny.portainer/tasks/post.yml` health-waits `/api/system/status` then immediately POSTs `/api/users/admin/init` in the same play, so the instance is never left uninitialised; `127.0.0.1:9002` loopback, `traefik_auth_modes.portainer='oidc'` (Tier-1 admin-only), Docker via docker-socket-proxy (REM-001). Source: https://github.com/portainer/portainer/security/advisories/GHSA-x626-fcwx-f5pc · https://github.com/advisories/GHSA-rrmm-9v76-h3p4
- **postgresql** (`postgres:16.14-alpine`): **CLEAN/re-verified — fourth consecutive re-confirm.** postgresql.org/support/security still lists **nothing after the May-2026 cohort** (18.4 / 17.10 / **16.14** / 15.18 / 14.23); there is **no 16.15** and the next scheduled release window is ~Aug 2026. The whole cluster stays fixed in 16.14: CVE-2026-6472/6473/6474/6475/6476/6477/6478/**6479** (7.5 SSL/GSS-init DoS — the only unauth/network-reachable leg)/6575/6637/6638. Probe: `127.0.0.1:5432` loopback + internal `infra_net`/`shared_net`, scram-sha-256 auth, no HTTP endpoint and no Traefik router → zero external unauth surface. REM-009/020/045 remain resolved. Source: https://www.postgresql.org/support/security/
- **bluesky_pds** (`ghcr.io/bluesky-social/pds`, pin `0.4`): **CLEAN/re-verified.** The `bluesky-social/atproto` GitHub Security Advisories page returns literally *"There aren't any published security advisories"* — **zero advisories have ever been published** for the monorepo, so nothing affects `@atproto/pds` or the PDS image in the window; no NVD/OSV record either. Near-hits positively ruled out: the cvedetails "Bluesky" vendor page indexes **BlueSkychat** (unrelated product), the `qwell/bsky-exploits` researcher disclosures carry no CVE, and the 2026-04-15 Bluesky outage was a **DDoS incident**, not a code defect. Caveat: *no advisories ever* also means **no public disclosure channel to watch** — perimeter posture is the durable control, and the floating `0.4` tag (the image has no semver tags) is standing supply-chain hygiene of the same class as woodpecker `v3` / tileserver `latest`. Probe: **no Traefik router at all** (the `state/manifest.yml` entry has no `domain_var`, so the file provider publishes no route), `127.0.0.1:2583` loopback, `PDS_INVITE_REQUIRED=true` by default → anonymous account creation closed; `/xrpc/_health` + `com.atproto.server.describeServer` are intentionally-public AT Protocol endpoints and loopback-only here. Source: https://github.com/bluesky-social/atproto/security/advisories

---

# nOS Vulnerability Scan Addendum — 2026-07-21 (Cycle 16, batch-31)

**Batch:** bookstack, firefly, gitlab, wordpress, freepbx · **Probe:** unauthenticated_endpoint_scan
**Outcome:** 1 queue item added (REM-130 freepbx **CRITICAL**, vendor-blocked); 1 disposition change (**GitLab now clean — REM-111 resolved**); 3 pending items re-verified (REM-122 bookstack, REM-129 + REM-114 wordpress); firefly clean/re-verified. This re-check **overturns FreePBX's 2026-07-09 "no new unauthenticated FreePBX CVE" disposition**: the July-17-2026 FreePBX advisory wave lands two *unauthenticated* legs — a UCP socket.io→AMI RCE and a missedcall SQLi — squarely in the probe focus. Both are **doubly mitigated** in nOS (the UCP Node ports are never mapped, on top of the standing vendor-block).

### ⚠ CRITICAL — [GHSA-37j8-fhxx-9vhp, no CVE] FreePBX — Unauthenticated UCP socket.io→AMI Remote Code Execution — VENDOR-BLOCKED / MITIGATED
- **Component:** freepbx (voip stack, `tiredofit/freepbx:latest` — FreePBX-15-era, image abandoned upstream 2022-04-30 at tag 5.2.0; `install_freepbx=false` by default)
- **Why this overturns batch-24's "no new unauth CVE":** the 2026-07-09 scan predated the **2026-07-17** FreePBX advisory wave, which is the first *unauthenticated* FreePBX disclosure since REM-113/CVE-2026-46376.
- **GHSA-37j8-fhxx-9vhp** (no CVE assigned; **CVSS v4.0 base 9.3 CRITICAL**, BTES 8.1; provider urgency **Red**; fixed **UCP module 17.0.9**) — socket.io v4 removed certain auth protections, so the UCP Node server's `io.use(checkAuth)` gate is **bypassable by an unauthenticated client**; crafted socket.io events then inject **Asterisk Manager Interface (AMI)** actions → **arbitrary command execution as the `asterisk` system user**. The UCP Node server listens on **ports 8001 (non-TLS) / 8003 (TLS)** by default.
- **Companion (same wave):** an **unauthenticated SQL injection in the missedcall module** via inbound **Caller-ID name** → administrator takeover (fixed missedcall **16.0.11 / 17.0.6**). Asterisk-core CVEs in the same wave (reflected XSS `/httpstatus`, `ast_xml` XXE, `ast_coredumper` local-root) remain **local/adjacent-network**, not pre-auth network RCE.
- **PROBE result (unauth_endpoint_scan) — DOUBLY MITIGATED:**
  - **(a) UCP Node ports 8001/8003 are NEVER published** by `roles/pazny.freepbx/templates/compose.yml.j2` — the only mapped ports are `:80 → 127.0.0.1:8088` (loopback) plus SIP 5060 / IAX 4569 / RTP 10000-10100. The RCE socket is therefore **unreachable from host, LAN, or Tailscale** even when freepbx is running.
  - **(b) Vendor-block stands** (same wall as REM-014/046/113): the abandoned tiredofit image bundles FreePBX-15-era modules; UCP 17.0.9 / missedcall 17.0.6 are unreachable and no maintained ARM64 FOSS FreePBX image exists.
  - **(c)** `install_freepbx=false` by default; **(d)** manifest entry has `port_var` but **no `domain_var`** → **not Traefik-routed** (no edge route); web UI + missedcall sit behind the `127.0.0.1:8088` loopback bind.
  - **Version-match confidence: LOW** — the socket.io-v4 bypass requires socket.io **v4**, which a FreePBX-15-era UCP likely predates. Recorded here for lineage and for honesty that a **new unauthenticated advisory landed in the probe window**.
- **Remediation:** structurally unfixable in the current image — migrate off the abandoned `tiredofit/freepbx` image (no maintained ARM64 FOSS alternative today). Operators who enable freepbx accept the documented risk. → **REM-130**
- **Source:** https://github.com/FreePBX/security-reporting/security/advisories/GHSA-37j8-fhxx-9vhp · https://community.freepbx.org/t/unauthenticated-remote-code-execution-in-freepbx-ucp-via-socket-io-namespace-auth-bypass-and-ami-action-injection/109905 · https://securityonline.info/freepbx-rce-vulnerabilities/

### Covered / not-applicable / re-verified this batch (no new item)
- **gitlab** (`gitlab/gitlab-ce:18.11.7-ce.0`): **NOW CLEAN — REM-111 RESOLVED.** The pin advanced `18.10.8-ce.0 → 18.11.7-ce.0` (default.config.yml + role default in sync), which is the **July-8-2026** security release (19.1.2 / 19.0.4 / 18.11.7) and clears CVE-2026-10712 (Web IDE XSS) + CVE-2026-13320 (wiki-markup HTML-injection) + the unauth CVE-2026-7492 (private-project existence disclosure). 18.11.7-ce.0 is **still the latest** release — no 18.11.8 / 19.1.3 / 19.2 in the window. `install_gitlab=false`, native OIDC at edge, signup disabled, `127.0.0.1:8929` loopback. Source: https://docs.gitlab.com/releases/patches/patch-release-gitlab-19-1-2-released/
- **wordpress** (`wordpress:6.9.4-php8.3-apache`): **REM-129 (HIGH) + REM-114 (MEDIUM) stay pending.** wp2shell (CVE-2026-63030 REST route-confusion + CVE-2026-60137 WP_Query SQLi) is now **confirmed actively exploited in-the-wild with public PoCs** (disclosed 2026-07-17). The mu-plugin `cve-2026-63030-batch-block.php` unregisters `/batch/v1` → breaks the RCE chain at its entry; the standalone SQLi (REM-129) is still unpatched in 6.9.4. Fixed cores 6.8.6 / 6.9.5 / 7.0.2 are **not yet dockerized** (7.0.0/7.0.1 are in the CVE range) → image-lag-blocked. `install_wordpress=false`, `127.0.0.1:8084` loopback. Source: https://www.bleepingcomputer.com/news/security/wordpress-core-wp2shell-rce-flaws-get-public-exploits-patch-now/ · https://thehackernews.com/2026/07/new-wp2shell-wordpress-core-flaw-lets.html
- **bookstack** (`lscr.io/linuxserver/bookstack:v26.05-ls264`): **REM-122 (MEDIUM) stays pending, re-verified.** v26.05.2 (2026-07-02) is **still the newest** BookStack release — no v26.05.3 / v26.07, no new CVE. Every leg is authenticated; native OIDC at edge + `127.0.0.1:3013` loopback. Fix = LSIO tag tracking ≥26.05.2. Source: https://www.bookstackapp.com/blog/bookstack-release-v26-05-2/ · https://app.opencve.io/cve/?vendor=bookstackapp
- **firefly** (`fireflyiii/core:version-6.2.21`): **CLEAN/re-verified.** No in-window HIGH/CRITICAL applies — GHSA-5q8v-j673-m5v4 (LOW User-API IDOR, fix 6.5.4) affects ≥6.4.23 so the pin **predates** the vulnerable code; GHSA-29w6-c52g-m8jc (CSV injection) affects <6.1.7 so the pin **post-dates** the fix. forward_auth/header_oidc + `127.0.0.1:3014` loopback + scoped TRUSTED_PROXIES. Hygiene note only: 6.2.21 trails 6.5.x. Source: https://github.com/firefly-iii/firefly-iii/security

---

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
