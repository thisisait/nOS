# devBoxNOS Security Advisory — Cycle 1 (2026-04-08)

**Inspektor Klepitko — Security Module**
**Scan type:** Web advisory check (CVE refresh for 14 components)
**Period:** 2026-04-01 — 2026-04-08

---

## Executive Summary

Initial baseline scan + first advisory refresh. **27 remediation items** tracked (13 CRITICAL, 11 HIGH, 3 MEDIUM). This cycle added **7 new findings** including a critical Authentik proxy auth bypass directly affecting devBoxNOS architecture and version corrections for n8n and GitLab.

**Stav:** Zatim zadna remediace nebyla provedena. Vsechny nalezi jsou v `pending` statu.

---

## Nove nalezy tento cyklus

### [CVE-2026-25748] Authentik — Proxy Auth Bypass via Malformed Cookie (CVSS 8.6)
- **Dopad na devBoxNOS: KRITICKE** — devBoxNOS pouziva proxy auth (nginx forward_auth) pro 13 sluzeb: Uptime Kuma, Calibre-Web, Home Assistant, Jellyfin, Kiwix, WordPress, ERPNext, FreeScout, Infisical, Paperclip, Superset, Puter, Metabase
- Utocnik vytvori malformovany cookie → Authentik ticho zahodi X-Authentik-* headery → zadost projde bez autentizace
- **Fix:** Soucasti upgradu na `authentik_version: "2025.12.4"` (uz trackovan jako REM-013)
- **Zdroj:** [TheHackerWire — Authentik Auth Bypass](https://www.thehackerwire.com/authentik-auth-bypass-via-malformed-cookie-cve-2026-25748/)

### [CVE-2026-25049] n8n — Sandbox Escape RCE (CVSS 9.4) — KOREKCE VERZE
- Puvodni doporuceni 2.0.0 je NEDOSTATECNE. Tato CVE vyzaduje n8n >= 2.5.2
- Authenticated user muze uniknout z JavaScript sandboxu pres type confusion a spustit systemove prikazy
- **Verejne dostupne exploity!**
- **Fix:** `n8n_version: "2.5.2"` (ne 2.0.0)
- **Zdroj:** [Endor Labs — CVE-2026-25049](https://www.endorlabs.com/learn/cve-2026-25049-n8n-rce)

### [CVE-2026-34205] Home Assistant — Unauthenticated Addon Endpoints (CVSS 9.7)
- Addony s host network mode exponuji neautentizovane endpointy na LAN
- Relevantni pokud HA pouziva addony s host networking
- **Fix:** Home Assistant Supervisor >= 2026.03.02
- **Zdroj:** [Home Assistant Security](https://www.home-assistant.io/security/)

### [CVE-2026-34940 + CVE-2026-5530] Ollama — OS Command Injection + SSRF
- CVE-2026-34940: Command injection pres Model URL
- CVE-2026-5530: SSRF v pull API (download.go) — pristup k internim sluzbam
- Ollama je na localhost, ale pokud je pristupny pres Open WebUI, utocnik muze chains
- **Fix:** `brew upgrade ollama` + overit OLLAMA_HOST=127.0.0.1
- **Zdroj:** [Tenable — CVE-2026-34940](https://www.tenable.com/cve/CVE-2026-34940), [OffSeq — CVE-2026-5530](https://radar.offseq.com/threat/cve-2026-5530-server-side-request-forgery-in-ollam-fdcf16de)

### Traefik — 3 dalsi CVE (vsechny fixnute v 3.6.11)
- CVE-2026-32595: Username enumeration pres timing attack v BasicAuth
- CVE-2026-33433: Identity spoofing pres non-canonical headerField
- CVE-2026-32305: mTLS bypass pres fragmentovany TLS ClientHello
- **Fix:** Soucasti pinu na `traefik_image_version: "3.6.11"` (uz REM-015)
- **Zdroj:** [GitLab Advisory DB](https://advisories.gitlab.com/pkg/golang/github.com/traefik/traefik/v3/CVE-2026-32595/)

### Metabase — Notification API Credential Exfiltration
- Authenticated user muze extrahovat DB connection credentials pres crafted notification template
- **Fix:** Overit ze Metabase `latest` tag stahuje opravenou verzi
- **Zdroj:** [Metabase Blog — Vulnerability Postmortem](https://www.metabase.com/blog/security-vulnerability-postmortem)

### GitLab — Korekce na 18.10.1
- Nejnovejsi bezpecnostni patch je 18.10.1 (ne 18.8.2 jak puvodni report)
- Opravuje Jira credential leak, GraphQL DoS, dalsi auth issues
- **Fix:** `gitlab_version: "18.10.1-ce.0"`
- **Zdroj:** [GitLab Patch Releases](https://about.gitlab.com/releases/2026/01/07/patch-release-gitlab-18-7-1-released/)

---

## Sledovane — bez novych nalezu

| Komponenta | Posledni advisory | Stav |
|---|---|---|
| WordPress core | April 2026 | Zadne CVE v core. Plugin CVEs (Perfmatters, Smart Slider 3) — relevantni jen pokud pouzivate tyto pluginy |
| Nextcloud | CVE-2026-33580 | Talk webhook brute force — low priority pro devBoxNOS (Talk neni primarni) |
| Redis | - | Zadne nove CVE od CVE-2025-49844 (uz v reportu) |
| Vaultwarden | - | Existujici CVE potvrzeny, zadne nove. Fix 1.35.4 platny |
| PostgreSQL | - | Existujici CVE potvrzeny, zadne nove. Fix 16.10-alpine platny |

---

## Action Items pro tento tyden

### CRITICAL (opravit ASAP):

1. **Authentik 2025.2 → 2025.12.4** — Kombinace CVE-2026-25227 (code injection) + CVE-2026-25748 (proxy auth bypass) = kompletni kompromitace SSO + vsech proxy-auth sluzeb
   ```yaml
   # default.config.yml
   authentik_version: "2025.12.4"
   ```

2. **n8n → 2.5.2** (ne 2.0.0!) — 5 CRITICAL CVE vcetne unauth RCE + sandbox escape. Verejne exploity.
   ```yaml
   n8n_version: "2.5.2"
   ```

3. **Redis → 7.4.6-alpine + requirepass** — RCE + zadna autentizace na shared network
   ```yaml
   redis_version: "7.4.6-alpine"
   # + pridat --requirepass do command
   ```

4. **FreePBX** — Zero-day aktivne exploitovany. Omezit admin panel na localhost IHNED.
   ```yaml
   # Bind SIP to localhost
   - "127.0.0.1:5060:5060"
   ```

### HIGH (opravit do tydne):

5. **Traefik → v3.6.11** — gRPC bypass + mTLS bypass + auth spoofing
   ```yaml
   traefik_image_version: "v3.6.11"
   ```

6. **Grafana → 12.4.2** — File write RCE
   ```yaml
   grafana_version: "12.4.2"
   ```

7. **GitLab → 18.10.1-ce.0** — SAML bypass, 2FA bypass, DoS, credential leak
   ```yaml
   gitlab_version: "18.10.1-ce.0"
   ```

8. **Vaultwarden → 1.35.4** — RCE + privilege escalation
   ```yaml
   vaultwarden_version: "1.35.4"
   ```

9. **PostgreSQL → 16.10-alpine** — SQLi + pg_dump RCE
   ```yaml
   postgresql_version: "16.10-alpine"
   ```

10. **Ollama** — Command injection + SSRF
    ```bash
    brew upgrade ollama
    # Overit: OLLAMA_HOST=127.0.0.1:11434
    ```

11. **Home Assistant Supervisor** — Unauthenticated addon endpoints (CVSS 9.7)
    ```bash
    # Overit verzi HA Supervisor >= 2026.03.02
    ```

### INFO (sledovat):

- **ERPNext → v15.98.1** — Unauth document access + SQLi
- **Open WebUI → 0.6.35** — Switch from :main tag
- **Metabase** — Overit ze :latest resolvuje opravenou verzi
- **WordPress** — Core OK, pozor na pluginy
- **Nextcloud Talk** — CVE-2026-33580 (webhook brute force) — low priority

---

## Prikazy k provedeni

```bash
# 1. Authentik upgrade (NEJVYSSI PRIORITA)
# V default.config.yml zmenit:
# authentik_version: "2025.12.4"
# Pak:
ansible-playbook main.yml -K --tags "stacks"

# 2. n8n pin
# V default.config.yml zmenit:
# n8n_version: "2.5.2"

# 3. Redis pin + auth
# V default.config.yml zmenit:
# redis_version: "7.4.6-alpine"
# V credentials.yml pridat:
# redis_password: "{prefix}_pw_redis"
# V infra compose template pridat --requirepass

# 4. Vsechny version piny najednou
# Editovat default.config.yml:
# traefik_image_version: "v3.6.11"
# grafana_version: "12.4.2"
# gitlab_version: "18.10.1-ce.0"
# vaultwarden_version: "1.35.4"
# postgresql_version: "16.10-alpine"
# erpnext_version: "v15.98.1"
# openwebui_version: "0.6.35"

# 5. Ollama upgrade
brew upgrade ollama

# 6. Full stack redeploy
ansible-playbook main.yml -K --tags "stacks,nginx"

# 7. Verify
ansible-playbook main.yml -K --tags "stack_verify"
```

---

## Doporuceni pro Klepitko knowledge base

1. **Authentik 2025.12.x** muze mit breaking changes oproti 2025.2 — Klepitko by mel znat nove env vars, zmeny v API, a nova flow schema
2. **n8n 2.x** je major version bump — muze zlomit existujici workflows. Klepitko by mel vedet jak migrovat 1.x → 2.x workflows
3. **CVE-2026-25748** meni bezpecnostni model proxy auth — Klepitko by mel vedet ze proxy auth "fail open" v nepatched Authentik = zadna ochrana
4. **Ollama SSRF chain** pres Open WebUI je novy attack vector — Klepitko by mel monitorovat Open WebUI → Ollama traffic

---

## Scan Metadata

- **Scanner:** Inspektor Klepitko — Security Module
- **Cycle:** 1
- **Date:** 2026-04-08 18:00 UTC
- **Components checked:** 14 (authentik, traefik, grafana, gitlab, n8n, nextcloud, wordpress, vaultwarden, redis, ollama, homeassistant, metabase, postgresql, freepbx)
- **Components remaining:** 22 (pending first CVE scan)
- **New findings:** 7
- **Total remediation items:** 27
- **Sources:** GitHub Security Advisories, NVD, vendor blogs, OSV.dev, security research publications
