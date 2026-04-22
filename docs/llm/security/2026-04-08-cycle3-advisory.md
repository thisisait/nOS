# nOS Security Advisory — Cycle 3 (2026-04-08)

**Inspektor Klepitko — Security Module**
**Scan type:** CVE refresh (5 pending components) + SSRF vector analysis (attack probe #3)
**Period:** 2026-04-09 — 2026-04-08 (cycle 3)

---

## Executive Summary

Cycle 3 completed coverage of all 37 components (100%). **7 new CVE findings** + **6 SSRF vector findings** from the attack probe. **44 total remediation items** (17 CRITICAL, 19 HIGH, 8 MEDIUM).

**Most critical new finding:** RustFS hardcoded gRPC token (CVE-2025-68926, CVSS 9.8) — anyone with access to the gRPC port can delete all data. Plus a correction of n8n's minimum safe version to 2.10.1 (CVE-2026-27493 + CVE-2026-27577).

**Attack Probe:** SSRF vector analysis identified n8n as the primary SSRF entry point — unauthenticated webhooks can scan the entire internal Docker network.

---

## New CVE findings this cycle

### [CVE-2025-68926] RustFS — Hardcoded gRPC Token (CRITICAL, CVSS 9.8)
- **Impact on nOS: CRITICAL** — RustFS uses a static "rustfs rpc" token for gRPC authentication, publicly available in source code
- An attacker with access to the gRPC port can delete all data, change policies, reconfigure the cluster
- **Fix:** Upgrade to `1.0.0-alpha.78+`
- **Source:** [NVD](https://nvd.nist.gov/vuln/detail/CVE-2025-68926), [SecurityOnline](https://securityonline.info/cve-2025-68926-critical-hardcoded-credential-flaw-exposes-rustfs-storage-clusters/)

### [CVE-2026-27822] RustFS — Stored XSS in Console (CRITICAL, CVSS 9.0)
- Attacker injects JavaScript via bypass of the PDF preview logic -> steals admin credentials from localStorage -> account takeover
- **Fix:** Upgrade to `1.0.0-alpha.83+`
- **Source:** [GitHub GHSA](https://github.com/rustfs/rustfs/security/advisories/GHSA-v9fg-3cr2-277j), [GBHackers](https://gbhackers.com/stored-xss-vulnerability-in-rustfs-console-puts-s3-admin-credentials-at-risk/)

### [CVE-2026-27493 + CVE-2026-27577] n8n — Form Node Injection + Sandbox Escape (CRITICAL)
- **CORRECTION:** n8n minimum safe version is now **2.10.1**, not 2.5.2 (REM-022)
- CVE-2026-27493 (CVSS 9.5): Second-order expression injection in Form nodes
- CVE-2026-27577 (CVSS 9.4): Sandbox escape -> arbitrary host commands
- Chain: Form injection -> sandbox escape -> full RCE on the host
- **CISA KEV:** n8n CVE-2025-68613 added to the Known Exploited Vulnerabilities catalogue
- **Fix:** `n8n_version: "2.10.1"` (fixes all 7 n8n CVEs)
- **Source:** [TheHackerNews](https://thehackernews.com/2026/03/critical-n8n-flaws-allow-remote-code.html), [SecurityWeek](https://www.securityweek.com/critical-n8n-vulnerabilities-allowed-server-takeover/)

### [CVE-2025-52039] ERPNext — SQL Injection (HIGH, CVSS 8.2)
- SQLi in the `get_material_requests_based_on_supplier()` function (Frappe ERPNext 15.57.5)
- Part of a series of 10 Error-Based SQLi (CVE-2025-52039 to CVE-2025-52050)
- Complements the existing REM-017 (CVE-2026-27471 unauth document access)
- **Fix:** Upgrade ERPNext to latest v15 stable (>= v15.98.1 covers both)
- **Source:** [Ameeba](https://www.ameeba.com/blog/cve-2025-52039-sql-injection-vulnerability-in-frappe-erpnext/), [NVD](https://nvd.nist.gov/vuln/detail/CVE-2025-52039)

### [CVE-2025-65267] ERPNext — Stored XSS via SVG Avatar (HIGH)
- Malicious JavaScript in an uploaded SVG avatar image -> account takeover
- Affects ERPNext v15.83.2 / Frappe v15.86.0
- **Fix:** Upgrade ERPNext to latest stable; add SVG sanitization
- **Source:** [CVEDetails](https://www.cvedetails.com/product/46305/Frappe-Erpnext.html)

### [CVE-2026-39360 + CVE-2026-27607] RustFS — Missing Authorization + POST Policy (MEDIUM)
- CVE-2026-39360: Missing auth check in multipart copy (UploadPartCopy) -> object exfiltration
- CVE-2026-27607: Missing POST policy validation -> storage exhaustion + unauthorized access
- **Fix:** Upgrade to `1.0.0-alpha.90+` (covers all 4 RustFS CVEs)
- **Source:** [CVEDetails](https://www.cvedetails.com/cve/CVE-2026-27607/), [ThreatINT](https://cve.threatint.eu/CVE/CVE-2026-39360)

### [CVE-2025-11183] QGIS Server QWC2 — XSS (LOW)
- XSS in the attribute table via name/description fields — requires editing capability
- nOS uses QGIS Server without the QWC2 frontend -> **minimal risk**
- **Source:** [NTC Swiss](https://hub.ntc.swiss/ntcf-2025-4286)

---

## SSRF Vector Analysis (Attack Probe #3)

### SSRF-001: n8n — Unauthenticated Internal Network Scanning (CRITICAL)
- **Entry point:** n8n HTTP Request node + unauthenticated webhooks
- **Target:** All internal Docker services (Redis :6379 without auth, PostgreSQL :5432, MariaDB :3306, Prometheus :9090, Portainer :9002)
- **Attack:** Attacker creates a workflow with an HTTP Request node -> scans the internal network -> exfiltrates data from Redis (no auth!), reads PostgreSQL banners
- **Remediation:** Enable `N8N_WEBHOOK_AUTH=true`; restrict internal IP ranges on the HTTP node; upgrade n8n

### SSRF-002: Uptime Kuma — Monitor URL SSRF (HIGH)
- **Entry point:** Uptime Kuma monitor creation (admin auth required)
- **Target:** All containers on `shared_net`
- **Attack:** Admin creates an HTTP monitor for `http://redis:6379` -> Kuma probe reveals internal services
- **Remediation:** URL validation — deny private IP ranges, Docker DNS names

### SSRF-003: Metabase/Superset — SQL Data Source SSRF (HIGH)
- **Entry point:** Data source connection setup (admin)
- **Target:** Internal databases (MariaDB, PostgreSQL)
- **Attack:** Admin adds a new data source with an internal URL -> SQL queries against internal DBs
- **Remediation:** Whitelist data source connections; use dedicated DB users

### SSRF-004: GitLab/Gitea — Webhook SSRF (MEDIUM)
- **Entry point:** Repository webhook configuration
- **Target:** Internal HTTP endpoints
- **Attack:** Webhook URL set to an internal service -> POST request on every push
- **Remediation:** Block private-IP webhooks in Gitea/GitLab admin settings

### SSRF-005: Grafana — Data Source Proxy SSRF (MEDIUM)
- **Entry point:** `/api/datasources/proxy/*` endpoint
- **Target:** Prometheus, Loki, Tempo (legitimate), but also arbitrary HTTP endpoints
- **Remediation:** Restrict data source proxy to known service IPs

### SSRF-006: Open WebUI — LLM-Mediated SSRF (MEDIUM)
- **Entry point:** Open WebUI Direct Connections feature
- **Target:** Ollama on `host.docker.internal:11434`, potentially others
- **Attack:** Hostile model server -> SSE injection -> browser-side SSRF
- **Remediation:** Disable Direct Connections; bind Ollama to 127.0.0.1 only

---

## Watched — no new findings

| Component | Last check | Status |
|---|---|---|
| Bluesky PDS | Cycle 3 search | No CVEs found (small community, no CVE process) |
| Paperclip | Cycle 3 search | No CVEs found (paperclip.ing orchestration tool) |
| Tileserver GL | Cycle 3 search | No new CVEs (last CVE-2020-15500, old) |

---

## Complete prioritized action list (Cycle 0+1+2+3)

### CRITICAL (fix ASAP):

1. **Authentik 2025.2 -> 2025.12.4** — Code injection + proxy auth bypass
   ```yaml
   authentik_version: "2025.12.4"
   ```

2. **n8n -> 2.10.1** — *CORRECTION* 7 CVEs including CISA KEV, unauth RCE + sandbox escape + form injection
   ```yaml
   n8n_version: "2.10.1"
   ```

3. **Redis -> 7.4.6-alpine + requirepass** — RCE + zero auth
   ```yaml
   redis_version: "7.4.6-alpine"
   ```

4. **RustFS -> 1.0.0-alpha.90** — *NEW* 4 CVEs: hardcoded token (CVSS 9.8) + stored XSS (CVSS 9.0) + missing auth + POST policy bypass
   ```yaml
   rustfs_version: "1.0.0-alpha.90"
   ```

5. **FreePBX** — Zero-day actively exploited, SIP ports on 0.0.0.0
6. **FreeScout -> 1.8.207** — Zero-click RCE via email
7. **Gitea -> 1.25.5** — Template directory traversal -> RCE

### HIGH (fix within a week):

8. **Traefik -> v3.6.11** — gRPC bypass + mTLS bypass + auth spoofing
9. **Grafana -> 12.4.2** — File write RCE
10. **GitLab -> 18.10.1-ce.0** — SAML bypass, 2FA bypass, credential leak
11. **Vaultwarden -> 1.35.4** — RCE + privilege escalation
12. **PostgreSQL -> 16.10-alpine** — SQLi + pg_dump RCE
13. **Ollama** — Command injection + SSRF (`brew upgrade ollama`)
14. **Home Assistant -> 2026.1.2+** — Unauth addon endpoints (CVSS 9.7) + stored XSS
15. **Open WebUI -> 0.6.35** — SSE injection + XSS
16. **Superset -> 6.0.0** — Auth bypass + SQLi (major version!)
17. **MariaDB -> 11.4.10** — Buffer overflow + dump RCE
18. **Jellyfin -> 10.10.7** — FFmpeg argument injection
19. **Portainer** — Verify latest resolves to >= 2.27
20. **ERPNext -> v15.98.1** — *EXPANDED* Unauth document access + SQLi (CVE-2026-27471) + 10 additional SQLi (CVE-2025-52039+) + stored XSS via SVG

### MEDIUM (watch):

21. **Metabase** — Notification API credential exfiltration
22. **Nginx** — `brew upgrade nginx`
23. **Tempo** — S3 key exposure (low risk)
24. **Uptime Kuma** — SSTI incomplete fix
25. **n8n SSRF** — Enable webhook auth, restrict HTTP node IP ranges
26. **Uptime Kuma SSRF** — URL validation for monitor creation

---

## Commands to run

```bash
# === PHASE 1: Emergency version pins (default.config.yml) ===
# authentik_version: "2025.12.4"
# n8n_version: "2.10.1"                # CORRECTION (not 2.5.2!)
# redis_version: "7.4.6-alpine"
# rustfs_version: "1.0.0-alpha.90"     # NEW
# freescout_version: "1.8.207"
# gitea_version: "1.25.5"

# === PHASE 2: High priority version pins ===
# traefik_image_version: "v3.6.11"
# grafana_version: "12.4.2"
# gitlab_version: "18.10.1-ce.0"
# vaultwarden_version: "1.35.4"
# postgresql_version: "16.10-alpine"
# openwebui_version: "0.6.35"
# superset_version: "6.0.0"            # major version!
# mariadb_version: "11.4.10"
# jellyfin_version: "10.10.7"
# erpnext_version: "v15.98.1"

# === PHASE 3: Homebrew updates ===
brew upgrade ollama nginx

# === PHASE 4: Redis auth (requires compose template change) ===
# Add to default.credentials.yml:
# redis_password: "{prefix}_pw_redis"
# Add --requirepass to redis command in infra compose

# === PHASE 5: Full redeploy ===
ansible-playbook main.yml -K --tags "stacks,nginx"
ansible-playbook main.yml -K --tags "stack_verify"
```

---

## Recommendations for the Klepitko knowledge base

1. **RustFS gRPC token** — Alpha-quality software with hardcoded credentials. Klepitko should verify on every upgrade that the token was changed from the default
2. **n8n SSRF** is a systemic problem — the HTTP Request node can be abused as an internal network scanner. Klepitko should know that n8n webhooks without auth = open SSRF gateway
3. **n8n CISA KEV** — CVE-2025-68613 is now in the CISA Known Exploited Vulnerabilities catalogue. That means a federal mandate to patch. Even though nOS is not federal, this indicates active in-the-wild exploitation
4. **ERPNext SQLi series** (CVE-2025-52039-52050) reveals a systemic input-validation problem in the Frappe framework. Klepitko should be cautious on upgrade — more SQLi will likely appear
5. **SSRF attack surface** is broad — 6 services can make outbound HTTP requests onto the internal network. Klepitko should monitor Docker network traffic for unexpected internal HTTP calls

---

## Coverage status

| Metric | Value |
|---|---|
| Components scanned | **37 / 37 (100%)** |
| Pending | 0 |
| Total remediation items | 44 |
| CRITICAL | 17 |
| HIGH | 19 |
| MEDIUM | 8 |
| Auto-fixable | 36 |
| Manual review | 8 |
| Remediations applied | 0 |
| Attack probes executed | 1/8 (SSRF vector analysis) |

---

## Scan Metadata

- **Scanner:** Inspektor Klepitko — Security Module
- **Cycle:** 3
- **Date:** 2026-04-08
- **Components checked this cycle:** 8 (erpnext, bluesky_pds, paperclip, rustfs, qgis_server, tileserver + n8n refresh, home_assistant refresh)
- **New CVE findings:** 7
- **New SSRF findings:** 6
- **Total remediation items:** 44
- **Sources:** NVD, GitHub Security Advisories, SecurityOnline, TheHackerNews, SecurityWeek, Ameeba, CVEDetails, ThreatINT, GBHackers, CISA KEV
