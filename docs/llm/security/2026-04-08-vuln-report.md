# devBoxNOS Vulnerability Report — 2026-04-08

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
- **Impact:** Use-after-free in Lua scripting engine. 13-year-old bug discovered at Pwn2Own Berlin 2025. In devBoxNOS, Redis has NO requirepass — any container on shared_net can exploit without credentials. ~60,000 servers globally affected.
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
