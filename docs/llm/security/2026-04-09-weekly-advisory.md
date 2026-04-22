# nOS Security Advisory — Cycle 2 (2026-04-09)

**Inspektor Klepitko — Security Module**
**Scan type:** Web advisory check (CVE refresh for 18 newly scanned components)
**Period:** 2026-04-08 — 2026-04-09

---

## Executive Summary

Cycle 2 rozsiril pokryti na 32 z 37 komponent. **10 novych nalezu** (2 CRITICAL, 6 HIGH, 2 MEDIUM). Celkem **37 remediacnich polozek** (15 CRITICAL, 17 HIGH, 5 MEDIUM). **Zadna remediace zatim nebyla provedena — vsechny nalezy z Cycle 0+1+2 jsou stale v `pending` stavu.**

**Nejkritictejsi novy nalez:** FreeScout zero-click RCE (CVE-2026-28289, CVSS 10/10) — utocnik posle email a prevezme server bez interakce uzivatele.

---

## Nove nalezy tento cyklus

### [CVE-2026-template-traversal] Gitea — Directory Traversal → RCE (CRITICAL)
- **Dopad na nOS:** Gitea pouziva `latest` tag — pokud resolvuje na <= 1.24.6, je zranitelny
- Authenticated utocnik vytvori malicious template repo → symlink na `.ssh/authorized_keys` → injekce SSH klice → RCE na Docker hostu
- **Verejne dostupny exploit** na GitHubu
- **Fix:** `gitea_version: "1.25.5"` (latest stable)
- **Zdroj:** [ClemaX/Gitea-Forgejo-CVE-2026](https://github.com/ClemaX/Gitea-Forgejo-CVE-2026)

### [CVE-2026-28289] FreeScout — Zero-Click RCE via Email (CRITICAL, CVSS 10/10)
- **Dopad na nOS: KRITICKE** — FreeScout zpracovava prichozi emaily, utok nevyzaduje autentizaci ani interakci
- Utocnik posle crafted email → bypass .htaccess restrikce pres zero-width space character → upload PHP webshell → RCE
- CVE-2026-28289 je bypass opravy pro CVE-2026-27636 (fixnuto v 1.8.206)
- **Aktivne exploitovano** v health, finance, tech sektorech
- **Fix:** `freescout_version: "1.8.207"` + `AllowOverrideAll` off v Apache
- **Zdroj:** [HelpNetSecurity](https://www.helpnetsecurity.com/2026/03/05/freescout-vulnerability-cve-2026-28289/), [OX Security](https://www.ox.security/blog/freescout-rce-cve-2026-27636/), [BleepingComputer](https://www.bleepingcomputer.com/news/security/mail2shell-zero-click-attack-lets-hackers-hijack-freescout-mail-servers/)

### [CVE-2026-23982] Apache Superset — Authorization Bypass (HIGH)
- Low-priv user muze prepisovat dataset SQL queries → pristup k neopravenym datum
- Kombinace s CVE-2025-48912 (Row Level Security SQLi) a CVE-2025-27696 (ownership takeover)
- **Fix:** `superset_version: "6.0.0"` (major version bump!)
- **Zdroj:** [Apache Superset CVEs](https://superset.apache.org/docs/security/cves/)

### [CVE-2026-32710] MariaDB — Heap Buffer Overflow (HIGH, CVSS 8.6)
- Buffer overflow v `JSON_SCHEMA_VALID()` funkci → crash nebo code execution
- Plus CVE-2025-13699 (mariadb-dump RCE, CVSS 7.0)
- nOS pouziva `mariadb_version: "lts"` — nutno overit ze resolvuje na >= 11.4.10
- **Fix:** Pin `mariadb_version: "11.4.10"`
- **Zdroj:** [SecurityOnline](https://securityonline.info/mariadb-json-schema-validation-buffer-overflow-vulnerability-cve-2026-32710/)

### [CVE-2025-64496] Open WebUI — SSE Code Injection (HIGH, CVSS 7.3) — KOREKCE VERZE
- **KOREKCE:** Puvodni doporuceni 0.6.6 (REM-005) je NEDOSTATECNE
- CVE-2025-64496: Hostile model server injektuje JavaScript pres SSE → kradez JWT → account takeover + RCE
- CVE-2025-64495: Stored DOM XSS v prompt templates
- **Fix:** `openwebui_version: "0.6.35"` (ne 0.6.6!)
- **Zdroj:** [Cato Networks](https://www.catonetworks.com/blog/cato-ctrl-vulnerability-discovered-open-webui-cve-2025-64496/), [CSO Online](https://www.csoonline.com/article/4113139/open-webui-bug-turns-free-model-into-an-enterprise-backdoor.html)

### [CVE-2025-31499] Jellyfin — FFmpeg Argument Injection (HIGH)
- Attacker s platnym itemId muze injektovat unsanitized parametry do FFmpeg → arbitrary code execution
- Relevantni pokud Jellyfin endpoints jsou pristupne (za proxy auth, ale stale riziko)
- **Fix:** `jellyfin_version: "10.10.7"`
- **Zdroj:** [NVD](https://nvd.nist.gov/vuln/detail/CVE-2025-31499), [Snyk](https://security.snyk.io/vuln/SNYK-DOTNET-JELLYFINCONTROLLER-9728210)

### Portainer — Dependency CVEs (HIGH)
- GO-2026-4394: Arbitrary code execution via PATH hijacking v OpenTelemetry SDK
- CVE-2025-68121: Go crypto/tls TLS session resumption bypass (CVSS 10.0 v podkladove Go knihovne)
- CVE-2025-30204: golang-jwt token forgery
- Portainer `latest` by mel byt patchovany (>= 2.27), ale je treba overit
- **Fix:** Verify `latest` resolves to patched version; pin for reproducibility
- **Zdroj:** [Portainer Release Notes](https://docs.portainer.io/release-notes), [Portainer Blog](https://www.portainer.io/blog/cve-2025-68121-and-docker)

### [CVE-2026-1642] Nginx — SSL Upstream Injection (MEDIUM)
- SSL upstream injection + ngx_mail buffer overread + TLS session reuse bypass
- Nginx na nOS je edge proxy — relevantni pro HTTPS terminaci
- **Fix:** `brew upgrade nginx`
- **Zdroj:** [Nginx Security Advisories](https://nginx.org/en/security_advisories.html)

### [CVE-2026-28377] Grafana Tempo — S3 Key Exposure (MEDIUM)
- S3 SSE-C encryption key exposed v plaintext na /status/config
- nOS pouziva lokalni storage (ne S3), takze nizke riziko, ale endpoint by mel byt chraneny
- **Fix:** Upgrade Tempo; omezit pristup k /status/* endpointum
- **Zdroj:** [ThreatINT](https://cve.threatint.eu/CVE/CVE-2026-28377)

### Uptime Kuma — SSTI + File Read (MEDIUM)
- SSTI v notification templates (GHSA-vffh-c9pq-4crh) — incomplete fix, reprodukovano na 2.1.3
- Cloud metadata exposure pres authenticated accounts
- Za Authentik proxy auth, takze nizsi riziko
- **Fix:** Ensure latest stable; monitor upstream fix
- **Zdroj:** [GitHub Security Advisories](https://github.com/louislam/uptime-kuma/security/advisories)

---

## Sledovane — bez novych nalezu

| Komponenta | Posledni advisory | Stav |
|---|---|---|
| Outline | Search 2026-04-09 | Zadne CVE nalezeny |
| Woodpecker CI | Search 2026-04-09 | Zadne CVE nalezeny (MISCONFIG-002 z Cycle 0 stale platny) |
| Infisical | Search 2026-04-09 | Zadne CVE nalezeny |
| Calibre-Web | Search 2026-04-09 | Zadne CVE specificky pro Calibre-Web (Calibre desktop ma CVEs, ale irrelevantni) |
| Kiwix | Search 2026-04-09 | Zadne CVE nalezeny |
| Puter | Search 2026-04-09 | Zadne CVE nalezeny |
| Grafana Loki | Search 2026-04-09 | Zadne Loki-specificke CVE v 2025/2026 |
| Grafana Alloy | Search 2026-04-09 | Zadne Alloy-specificke CVE nalezeny |
| dnsmasq | Search 2026-04-09 | CVE-2025-12198/12199/12200 — spornych, neni jasne zda platne |

---

## Kompletni prioritizovany action list (Cycle 0+1+2)

### CRITICAL (opravit ASAP):

1. **Authentik 2025.2 → 2025.12.4** — Code injection + proxy auth bypass = kompletni kompromitace SSO
   ```yaml
   authentik_version: "2025.12.4"
   ```

2. **n8n → 2.5.2** — 5 CRITICAL CVE, unauth RCE + sandbox escape, verejne exploity
   ```yaml
   n8n_version: "2.5.2"
   ```

3. **Redis → 7.4.6-alpine + requirepass** — RCE + zero auth
   ```yaml
   redis_version: "7.4.6-alpine"
   ```

4. **FreePBX** — Zero-day aktivne exploitovany, SIP porty na 0.0.0.0
   ```yaml
   # Bind SIP to localhost:
   - "127.0.0.1:5060:5060"
   ```

5. **FreeScout → 1.8.207** — *NOVY* Zero-click RCE via email, CVSS 10/10
   ```yaml
   freescout_version: "1.8.207"
   ```

6. **Gitea → 1.25.5** — *NOVY* Template directory traversal → RCE, public exploit
   ```yaml
   gitea_version: "1.25.5"
   ```

### HIGH (opravit do tydne):

7. **Traefik → v3.6.11** — gRPC bypass + mTLS bypass + auth spoofing
   ```yaml
   traefik_image_version: "v3.6.11"
   ```

8. **Grafana → 12.4.2** — File write RCE
   ```yaml
   grafana_version: "12.4.2"
   ```

9. **GitLab → 18.10.1-ce.0** — SAML bypass, 2FA bypass, credential leak
   ```yaml
   gitlab_version: "18.10.1-ce.0"
   ```

10. **Vaultwarden → 1.35.4** — RCE + privilege escalation
    ```yaml
    vaultwarden_version: "1.35.4"
    ```

11. **PostgreSQL → 16.10-alpine** — SQLi + pg_dump RCE
    ```yaml
    postgresql_version: "16.10-alpine"
    ```

12. **Ollama** — Command injection + SSRF
    ```bash
    brew upgrade ollama
    ```

13. **Home Assistant Supervisor** — Unauthenticated addon endpoints (CVSS 9.7)

14. **Open WebUI → 0.6.35** — *KOREKCE* SSE injection + XSS (ne 0.6.6!)
    ```yaml
    openwebui_version: "0.6.35"
    ```

15. **Superset → 6.0.0** — *NOVY* Auth bypass + SQLi (major version!)
    ```yaml
    superset_version: "6.0.0"
    ```

16. **MariaDB → 11.4.10** — *NOVY* Buffer overflow + dump RCE
    ```yaml
    mariadb_version: "11.4.10"
    ```

17. **Jellyfin → 10.10.7** — *NOVY* FFmpeg argument injection
    ```yaml
    jellyfin_version: "10.10.7"
    ```

18. **Portainer** — Verify latest resolves to >= 2.27

### MEDIUM (sledovat):

19. **ERPNext → v15.98.1** — Unauth document access + SQLi
20. **Metabase** — Notification API credential exfiltration
21. **Nginx** — `brew upgrade nginx`
22. **Tempo** — S3 key exposure (low risk for local storage)
23. **Uptime Kuma** — SSTI incomplete fix

---

## Prikazy k provedeni

```bash
# === PHASE 1: Emergency version pins (default.config.yml) ===
# authentik_version: "2025.12.4"
# n8n_version: "2.5.2"
# redis_version: "7.4.6-alpine"
# freescout_version: "1.8.207"       # NOVY
# gitea_version: "1.25.5"            # NOVY

# === PHASE 2: High priority version pins ===
# traefik_image_version: "v3.6.11"
# grafana_version: "12.4.2"
# gitlab_version: "18.10.1-ce.0"
# vaultwarden_version: "1.35.4"
# postgresql_version: "16.10-alpine"
# openwebui_version: "0.6.35"        # KOREKCE (ne 0.6.6)
# superset_version: "6.0.0"          # NOVY (major!)
# mariadb_version: "11.4.10"         # NOVY
# jellyfin_version: "10.10.7"        # NOVY
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

1. **FreeScout zero-click RCE** je novy attack vector — emailova sluzba muze byt kompromitovana bez jakekoliv interakce. Klepitko by mel monitorovat FreeScout logy pro podezrele prilohy (.htaccess, .user.ini)
2. **Gitea template processing** meni bezpecnostni model — template repos maji vetsi moc nez se ocekava. Klepitko by mel vedet ze repository templates mohou obsahovat symlinky
3. **Superset 6.0.0** je major version bump — muze zmenit API, dashboard formaty, a RBAC model. Klepitko by mel otestovat kompatibilitu pred upgradem
4. **Open WebUI Direct Connections** feature je rizikovy — pokud uzivatele pripoji externi model server, muze byt kompromitovan frontend. Klepitko by mel vedet o tomto attack vektoru

---

## Stav pokryti

| Metrika | Hodnota |
|---|---|
| Komponenty skenovane | 32 / 37 (86%) |
| Pending | 5 (paperclip, rustfs, tileserver, qgis_server, bluesky_pds) |
| Celkem remediacnich polozek | 37 |
| CRITICAL | 15 |
| HIGH | 17 |
| MEDIUM | 5 |
| Auto-fixable | 31 |
| Manual review | 6 |
| Provedene remediace | 0 |

---

## Scan Metadata

- **Scanner:** Inspektor Klepitko — Security Module
- **Cycle:** 2
- **Date:** 2026-04-09 06:00 UTC
- **Components checked this cycle:** 18 (nginx, portainer, gitea, openwebui, infisical, mariadb, superset, outline, freescout, woodpecker, jellyfin, uptime_kuma, calibreweb, kiwix, puter, loki, tempo, alloy, dnsmasq)
- **Components remaining:** 5 (paperclip, rustfs, tileserver, qgis_server, bluesky_pds)
- **New findings:** 10
- **Total remediation items:** 37
- **Sources:** GitHub Security Advisories, NVD, vendor blogs, Snyk, OSV.dev, HelpNetSecurity, BleepingComputer, SecurityOnline, CatoNetworks
