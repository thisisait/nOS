# devBoxNOS Security Advisory — Cycle 3 (2026-04-08)

**Inspektor Klepitko — Security Module**
**Scan type:** CVE refresh (5 pending components) + SSRF vector analysis (attack probe #3)
**Period:** 2026-04-09 — 2026-04-08 (cycle 3)

---

## Executive Summary

Cycle 3 dokoncil pokryti vsech 37 komponent (100%). **7 novych CVE nalezu** + **6 SSRF vektor nalezu** z attack probe. Celkem **44 remediacnich polozek** (17 CRITICAL, 19 HIGH, 8 MEDIUM).

**Nejkritictejsi novy nalez:** RustFS hardcoded gRPC token (CVE-2025-68926, CVSS 9.8) — kazdy s pristupem k gRPC portu muze smazat vsechna data. Plus korekce n8n minimum safe verze na 2.10.1 (CVE-2026-27493 + CVE-2026-27577).

**Attack Probe:** SSRF vector analysis identifikovala n8n jako hlavni SSRF entry point — unauthenticated webhooks mohou scanovat celou interni Docker sit.

---

## Nove CVE nalezy tento cyklus

### [CVE-2025-68926] RustFS — Hardcoded gRPC Token (CRITICAL, CVSS 9.8)
- **Dopad na devBoxNOS: KRITICKE** — RustFS pouziva staticky token "rustfs rpc" pro gRPC autentizaci, verejne v source code
- Utocnik s pristupem ke gRPC portu muze smazat vsechna data, menit politiky, rekonfigurovat cluster
- **Fix:** Upgrade na `1.0.0-alpha.78+`
- **Zdroj:** [NVD](https://nvd.nist.gov/vuln/detail/CVE-2025-68926), [SecurityOnline](https://securityonline.info/cve-2025-68926-critical-hardcoded-credential-flaw-exposes-rustfs-storage-clusters/)

### [CVE-2026-27822] RustFS — Stored XSS v Console (CRITICAL, CVSS 9.0)
- Utocnik injektuje JavaScript pres bypass PDF preview logiky → kradez admin credentials z localStorage → account takeover
- **Fix:** Upgrade na `1.0.0-alpha.83+`
- **Zdroj:** [GitHub GHSA](https://github.com/rustfs/rustfs/security/advisories/GHSA-v9fg-3cr2-277j), [GBHackers](https://gbhackers.com/stored-xss-vulnerability-in-rustfs-console-puts-s3-admin-credentials-at-risk/)

### [CVE-2026-27493 + CVE-2026-27577] n8n — Form Node Injection + Sandbox Escape (CRITICAL)
- **KOREKCE:** n8n minimum safe verze je nyni **2.10.1**, ne 2.5.2 (REM-022)
- CVE-2026-27493 (CVSS 9.5): Second-order expression injection v Form nodes
- CVE-2026-27577 (CVSS 9.4): Sandbox escape → arbitrary host commands
- Chain: Form injection → sandbox escape → full RCE na hostu
- **CISA KEV:** n8n CVE-2025-68613 pridano do Known Exploited Vulnerabilities katalogu
- **Fix:** `n8n_version: "2.10.1"` (fixuje vsech 7 n8n CVE)
- **Zdroj:** [TheHackerNews](https://thehackernews.com/2026/03/critical-n8n-flaws-allow-remote-code.html), [SecurityWeek](https://www.securityweek.com/critical-n8n-vulnerabilities-allowed-server-takeover/)

### [CVE-2025-52039] ERPNext — SQL Injection (HIGH, CVSS 8.2)
- SQLi v `get_material_requests_based_on_supplier()` funkci (Frappe ERPNext 15.57.5)
- Soucasti serie 10 Error-Based SQLi (CVE-2025-52039 az CVE-2025-52050)
- Doplnuje existujici REM-017 (CVE-2026-27471 unauth document access)
- **Fix:** Upgrade ERPNext na latest v15 stable (>= v15.98.1 pokryva obe)
- **Zdroj:** [Ameeba](https://www.ameeba.com/blog/cve-2025-52039-sql-injection-vulnerability-in-frappe-erpnext/), [NVD](https://nvd.nist.gov/vuln/detail/CVE-2025-52039)

### [CVE-2025-65267] ERPNext — Stored XSS via SVG Avatar (HIGH)
- Malicious JavaScript v uploadovanem SVG avatar image → account takeover
- Affects ERPNext v15.83.2 / Frappe v15.86.0
- **Fix:** Upgrade ERPNext na latest stable; pridat SVG sanitization
- **Zdroj:** [CVEDetails](https://www.cvedetails.com/product/46305/Frappe-Erpnext.html)

### [CVE-2026-39360 + CVE-2026-27607] RustFS — Missing Authorization + POST Policy (MEDIUM)
- CVE-2026-39360: Missing auth check v multipart copy (UploadPartCopy) → objekt exfiltrace
- CVE-2026-27607: Missing POST policy validation → storage exhaustion + unauthorized access
- **Fix:** Upgrade na `1.0.0-alpha.90+` (pokryva vsechny 4 RustFS CVE)
- **Zdroj:** [CVEDetails](https://www.cvedetails.com/cve/CVE-2026-27607/), [ThreatINT](https://cve.threatint.eu/CVE/CVE-2026-39360)

### [CVE-2025-11183] QGIS Server QWC2 — XSS (LOW)
- XSS v attribute table pres name/description fields — vyzaduje editing capability
- devBoxNOS pouziva QGIS Server bez QWC2 frontendu → **minimalni riziko**
- **Zdroj:** [NTC Swiss](https://hub.ntc.swiss/ntcf-2025-4286)

---

## SSRF Vector Analysis (Attack Probe #3)

### SSRF-001: n8n — Unauthenticated Internal Network Scanning (CRITICAL)
- **Entry point:** n8n HTTP Request node + unauthenticated webhooks
- **Target:** Vsechny interni Docker sluzby (Redis :6379 bez auth, PostgreSQL :5432, MariaDB :3306, Prometheus :9090, Portainer :9002)
- **Attack:** Utocnik vytvori workflow s HTTP Request node → scanuje interni sit → exfiltruje data z Redis (bez auth!), cte PostgreSQL banners
- **Remediace:** Enable `N8N_WEBHOOK_AUTH=true`; restrict HTTP node internal IP ranges; upgrade n8n

### SSRF-002: Uptime Kuma — Monitor URL SSRF (HIGH)
- **Entry point:** Uptime Kuma monitor creation (admin auth required)
- **Target:** Vsechny kontejnery na `shared_net`
- **Attack:** Admin vytvori HTTP monitor pro `http://redis:6379` → Kuma probe odhali interni sluzby
- **Remediace:** URL validation — deny private IP ranges, Docker DNS names

### SSRF-003: Metabase/Superset — SQL Data Source SSRF (HIGH)
- **Entry point:** Data source connection setup (admin)
- **Target:** Interni databaze (MariaDB, PostgreSQL)
- **Attack:** Admin prida novou data source s interni URL → SQL queries proti internim DB
- **Remediace:** Whitelist data source connections; use dedicated DB users

### SSRF-004: GitLab/Gitea — Webhook SSRF (MEDIUM)
- **Entry point:** Repository webhook configuration
- **Target:** Interni HTTP endpointy
- **Attack:** Webhook URL nastaven na interni sluzbu → POST request pri kazdém push
- **Remediace:** Block private IP webhooks v Gitea/GitLab admin settings

### SSRF-005: Grafana — Data Source Proxy SSRF (MEDIUM)
- **Entry point:** `/api/datasources/proxy/*` endpoint
- **Target:** Prometheus, Loki, Tempo (legitimni), ale take libovolne HTTP endpointy
- **Remediace:** Restrict data source proxy to known service IPs

### SSRF-006: Open WebUI — LLM-Mediated SSRF (MEDIUM)
- **Entry point:** Open WebUI Direct Connections feature
- **Target:** Ollama na `host.docker.internal:11434`, potencialne dalsi
- **Attack:** Hostile model server → SSE injection → browser-side SSRF
- **Remediace:** Disable Direct Connections; bind Ollama to 127.0.0.1 only

---

## Sledovane — bez novych nalezu

| Komponenta | Posledni check | Stav |
|---|---|---|
| Bluesky PDS | Cycle 3 search | Zadne CVE nalezeny (male community, no CVE process) |
| Paperclip | Cycle 3 search | Zadne CVE nalezeny (paperclip.ing orchestration tool) |
| Tileserver GL | Cycle 3 search | Zadne nove CVE (posledni CVE-2020-15500, stary) |

---

## Kompletni prioritizovany action list (Cycle 0+1+2+3)

### CRITICAL (opravit ASAP):

1. **Authentik 2025.2 → 2025.12.4** — Code injection + proxy auth bypass
   ```yaml
   authentik_version: "2025.12.4"
   ```

2. **n8n → 2.10.1** — *KOREKCE* 7 CVE vcetne CISA KEV, unauth RCE + sandbox escape + form injection
   ```yaml
   n8n_version: "2.10.1"
   ```

3. **Redis → 7.4.6-alpine + requirepass** — RCE + zero auth
   ```yaml
   redis_version: "7.4.6-alpine"
   ```

4. **RustFS → 1.0.0-alpha.90** — *NOVY* 4 CVE: hardcoded token (CVSS 9.8) + stored XSS (CVSS 9.0) + missing auth + POST policy bypass
   ```yaml
   rustfs_version: "1.0.0-alpha.90"
   ```

5. **FreePBX** — Zero-day aktivne exploitovany, SIP porty na 0.0.0.0
6. **FreeScout → 1.8.207** — Zero-click RCE via email
7. **Gitea → 1.25.5** — Template directory traversal → RCE

### HIGH (opravit do tydne):

8. **Traefik → v3.6.11** — gRPC bypass + mTLS bypass + auth spoofing
9. **Grafana → 12.4.2** — File write RCE
10. **GitLab → 18.10.1-ce.0** — SAML bypass, 2FA bypass, credential leak
11. **Vaultwarden → 1.35.4** — RCE + privilege escalation
12. **PostgreSQL → 16.10-alpine** — SQLi + pg_dump RCE
13. **Ollama** — Command injection + SSRF (`brew upgrade ollama`)
14. **Home Assistant → 2026.1.2+** — Unauth addon endpoints (CVSS 9.7) + stored XSS
15. **Open WebUI → 0.6.35** — SSE injection + XSS
16. **Superset → 6.0.0** — Auth bypass + SQLi (major version!)
17. **MariaDB → 11.4.10** — Buffer overflow + dump RCE
18. **Jellyfin → 10.10.7** — FFmpeg argument injection
19. **Portainer** — Verify latest resolves to >= 2.27
20. **ERPNext → v15.98.1** — *ROZSIRENO* Unauth document access + SQLi (CVE-2026-27471) + 10 additional SQLi (CVE-2025-52039+) + stored XSS via SVG

### MEDIUM (sledovat):

21. **Metabase** — Notification API credential exfiltration
22. **Nginx** — `brew upgrade nginx`
23. **Tempo** — S3 key exposure (low risk)
24. **Uptime Kuma** — SSTI incomplete fix
25. **n8n SSRF** — Enable webhook auth, restrict HTTP node IP ranges
26. **Uptime Kuma SSRF** — URL validation for monitor creation

---

## Prikazy k provedeni

```bash
# === PHASE 1: Emergency version pins (default.config.yml) ===
# authentik_version: "2025.12.4"
# n8n_version: "2.10.1"                # KOREKCE (ne 2.5.2!)
# redis_version: "7.4.6-alpine"
# rustfs_version: "1.0.0-alpha.90"     # NOVY
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

## Doporuceni pro Klepitko knowledge base

1. **RustFS gRPC token** — Alpha-quality software s hardcoded credentials. Klepitko by mel pri kazdem upgrade overit ze token byl zmenen z defaultu
2. **n8n SSRF** je systemovy problem — HTTP Request node muze byt zneuzit jako interni network scanner. Klepitko by mel vedet ze n8n webhooks bez auth = open SSRF gateway
3. **n8n CISA KEV** — CVE-2025-68613 je ted v CISA Known Exploited Vulnerabilities katalogu. To znamena federalni mandate na patch. I kdyz devBoxNOS neni federal, indikuje to aktivni exploitation in-the-wild
4. **ERPNext SQLi serie** (CVE-2025-52039-52050) ukazuje systemicky problem s input validation ve Frappe frameworku. Klepitko by mel byt opatrny pri upgradu — dalsi SQLi se pravdepodobne objevi
5. **SSRF attack surface** je rozlehly — 6 sluzeb muze delat outbound HTTP requesty na interni sit. Klepitko by mel monitorovat Docker network traffic pro neocekavane interni HTTP volani

---

## Stav pokryti

| Metrika | Hodnota |
|---|---|
| Komponenty skenovane | **37 / 37 (100%)** |
| Pending | 0 |
| Celkem remediacnich polozek | 44 |
| CRITICAL | 17 |
| HIGH | 19 |
| MEDIUM | 8 |
| Auto-fixable | 36 |
| Manual review | 8 |
| Provedene remediace | 0 |
| Attack probes provedene | 1/8 (SSRF vector analysis) |

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
