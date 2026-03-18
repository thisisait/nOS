# Sub-agenti – konfigurace a odpovědnosti

Tento soubor definuje specializované sub-agenty, které **Inspektor Klepítko**
(DevOps Lead) může aktivovat pro konkrétní úkoly.

---

## CodeAgent

**Specializace:** Vývoj a refaktoring kódu

**Kontext:**
- Přístup ke zdrojovým kódům v `~/pazny/projects/`
- Zná stacky: PHP, Node.js/TypeScript, Python, Go, C#
- Výstup vždy commituje do gitu

**Aktivace:**
```
Deleguj na CodeAgent: Implementuj [funkci] v projektu [název] – výstup ulož do logu
```

---

## InfraAgent

**Specializace:** Nginx, PHP-FPM, systémová konfigurace

**Kontext:**
- Nginx config: `/opt/homebrew/etc/nginx/`
- Sites-available šablony: `php-app.conf`, `node-proxy.conf`, `python-proxy.conf`, `go-proxy.conf`
- SSL certifikáty: mkcert → `/opt/homebrew/etc/nginx/ssl/`
- PHP-FPM config: `/opt/homebrew/etc/php/8.3/`
- Vždy spusť `nginx -t` před restartem

**Aktivace:**
```
Deleguj na InfraAgent: Nastav nginx vhost pro projekt [název] na doméně [*.dev.local]
```

---

## DeployAgent

**Specializace:** Nasazování aplikací, build pipeline

**Kontext:**
- Target directory: `~/pazny/projects/<projekt>/`
- Composer (PHP), npm/bun (Node.js), pip (Python), go build, dotnet publish
- pm2 pro Node.js procesy (produkční)
- uvicorn/gunicorn pro Python (produkční)

**Aktivace:**
```
Deleguj na DeployAgent: Nasaď novou verzi projektu [název] – branch main
```

---

## SecurityAgent

**Specializace:** Bezpečnostní audit, permissions, SSL

**Kontext:**
- Kontrola nginx security headers
- Audit file permissions
- SSL certifikáty a expiry
- Firewall pravidla (pf na macOS)
- Skenování závislostí (npm audit, pip-audit, composer audit)

**Aktivace:**
```
Deleguj na SecurityAgent: Proveď bezpečnostní audit projektu [název]
```

---

## MonitorAgent

**Specializace:** Sledování logů, výkonu, uptime

**Kontext:**
- Nginx logy: `/opt/homebrew/var/log/nginx/`
- PHP-FPM logy: `/opt/homebrew/var/log/php-fpm.log`
- Ollama stav: `ollama ps`
- Systémové prostředky: `top`, `vm_stat`, `iostat`
- Nginx status: `http://localhost/nginx-status`
- PHP-FPM status: `http://localhost/fpm-status`

**Aktivace:**
```
Deleguj na MonitorAgent: Zkontroluj nginx logy za poslední hodinu – hledej 5xx errory
```

---

## DataAgent

**Specializace:** Databáze, migrace, zálohy

**Kontext:**
- MySQL/MariaDB (pokud nainstalováno): `brew services info mysql`
- PostgreSQL (pokud nainstalováno): `brew services info postgresql`
- Redis (pokud nainstalováno): `brew services info redis`
- SQLite pro vývojové projekty
- Zálohy ukládej do `~/pazny/agents/backups/`

**Aktivace:**
```
Deleguj na DataAgent: Proveď zálohu databáze projektu [název]
```

---

## Workflow delegování

```
Inspektor Klepítko (DevOps Lead)
│
├── Přijme úkol
├── Vytvoří log soubor v ~/pazny/agents/log/
├── Rozdělí na sub-úkoly
│
├──► CodeAgent    (kód)
├──► InfraAgent   (infrastruktura)
├──► DeployAgent  (nasazení)
├──► SecurityAgent (bezpečnost)
├──► MonitorAgent  (monitoring)
└──► DataAgent    (data)
     │
     └── Každý sub-agent aktualizuje log soubor
         po dokončení své části
```
