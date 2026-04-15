# TODO

## ✅ DONE — Mac apps/utils přidány do playbooku (default.config.yml)

### Přidáno do `homebrew_cask_apps` (default true, vypnout v config.yml)
- **OnyX** — `onyx` — údržba macOS, cache cleanup
- **iMazing v3** — `imazing` — správa iOS zařízení
- **CheatSheet** — `cheatsheet` — přehled klávesových zkratek
- **Shottr** — `shottr` — screenshoty + OCR + scrolling capture
- **DockDoor** — `dockdoor` — Windows-like previewy oken v Docku
- **Hyperkey** — `hyperkey` — capslock → hyper modifier
- **LinearMouse** — `linearmouse` — customizace myši/trackpadu
- **Syncthing (app)** — `syncthing-app` — P2P file sync
- **Hidden Bar** — `hiddenbar` — skrývání ikon v menu baru
- **Raycast** — už bylo v seznamu (řádek 299)

### Přidáno do `homebrew_installed_packages` (CLI)
- **Security tools**: `trivy`, `grype`, `syft`, `gitleaks`, `nuclei`, `semgrep`
- **CLI agenty**: `ntfy` (CLI klient — server je samostatná Docker role), `opencode`

### Přidáno jako commented-out (opt-in v config.yml)
- **Antinote** — `antinote` (cask existuje)
- **Cotypist / boring.notch / flux-markdown / TypeWhisper** — nejsou v brew; manuální install z GitHubu

### Přidáno do `mas_installed_apps` (commented — vyžaduje `install_mas_apps: true` + mas login)
- Gifski (1351639930), QuickShade (931571202), Dropover (1355679052)

---

## 📋 PLÁN — Nové Docker role (`pazny.*`)

Každá nová služba dostane vlastní roli v `roles/pazny.<service>/` dle compose-override patternu (viz CLAUDE.md):
```
roles/pazny.<service>/
  defaults/main.yml      # version, port, data_dir, mem_limit
  tasks/main.yml         # data dir + compose override render
  tasks/post.yml         # (opt.) admin init, OIDC config, DB migrations
  templates/compose.yml.j2
```
Wire-up: `include_role` v `core-up.yml` / `stack-up.yml` + `install_<service>` toggle v `default.config.yml` + (volitelně) nginx vhost + `authentik_oidc_apps` entry.

### Priorita 1 — Infra / DevOps (doplnění stávajícího devops stacku)

| Role | Stack | DB | SSO | Priorita | Poznámka |
|------|-------|----|----|-----------|----------|
| `pazny.code_server` | devops | fs | proxy | **P1** | VS Code v browseru; heavy mem limit |
| `pazny.ntfy` | iiab | sqlite | proxy | **P1** | Push notifications; dvojí použití: server + Alloy alerting sink |
| `pazny.miniflux` | iiab | postgres | **OIDC native** | **P1** | RSS reader; minimal, OIDC out-of-the-box |

### Priorita 2 — Wiki / Edu / Docs

| Role | Stack | DB | SSO | Priorita | Poznámka |
|------|-------|----|----|-----------|----------|
| `pazny.hedgedoc` | b2b | postgres | **OIDC native** | P2 | Collaborative markdown — doplňuje Outline |
| `pazny.bookstack` | b2b | mariadb | **OIDC native** | P2 | Wiki s knihy/kapitoly strukturou |
| `pazny.onlyoffice` | b2b | – (redis) | proxy | P2 | Doc server pro Nextcloud/Outline; integrace přes iframe |
| `pazny.moodle` | iiab | mariadb | OIDC plugin / proxy | P3 | LMS — velký setup, první běh 5–10 min migrací |
| `pazny.kolibri` | iiab | sqlite/pg | proxy | P3 | Offline education; pair s Kiwix |

### Priorita 3 — Finance / ERP

| Role | Stack | DB | SSO | Priorita | Poznámka |
|------|-------|----|----|-----------|----------|
| `pazny.firefly` | b2b | mariadb | **OIDC native** | P2 | Personal finance; OIDC přes OAuth2 provider |
| `pazny.wallos` | iiab | sqlite | proxy | P3 | Subscription tracker; lightweight |
| `pazny.invoiceninja` | b2b | mariadb | proxy | P3 | Invoicing + CRM |
| `pazny.dolibarr` | b2b | mariadb | proxy | P3 | ERP/CRM alt. k ERPNextu |

### Priorita 4 — Mail stack

| Role | Stack | DB | SSO | Priorita | Poznámka |
|------|-------|----|----|-----------|----------|
| `pazny.stalwart` | **nový `mail` stack** | rocksdb (nativní) | LDAP/OIDC | P2 | JMAP+IMAP+SMTP+AS v jedné binárce; WebAdmin UI |
| `pazny.snappymail` | mail | fs | proxy | P2 | Webmail frontend; připojí Stalwart přes IMAP |

### Priorita 5 — IoT / Industrial / Time-series

| Role | Stack | DB | SSO | Priorita | Poznámka |
|------|-------|----|----|-----------|----------|
| `pazny.nodered` | iiab | fs | proxy | P2 | Flow automation; párování s Home Assistant, InfluxDB |
| `pazny.influxdb` | observability | nativní storage | proxy | P2 | Time-series DB; zdroj pro Grafanu (vedle Promethea) |
| `pazny.openplc` | **nový `engineering` stack** | sqlite | proxy | P3 | PLC runtime + editor |
| `pazny.farmos` | engineering | postgres | proxy | P3 | Farm management |

### Priorita 6 — Healthcare / specialized

| Role | Stack | DB | SSO | Priorita | Poznámka |
|------|-------|----|----|-----------|----------|
| `pazny.openemr` | **nový `health` stack** | mariadb | proxy | P4 | EMR — citlivá data, vyžaduje HTTPS everywhere |

### Priorita 7 — Volitelné CMS

| Role | Stack | DB | SSO | Priorita | Poznámka |
|------|-------|----|----|-----------|----------|
| `pazny.joomla` | iiab | mariadb | proxy | P4 | CMS alt. k WordPressu; nižší priorita |

---

## 🗓 Doporučené pořadí implementace

1. **Wave A** (P1, low-risk, ihned užitečné): `code_server`, `ntfy`, `miniflux`
2. **Wave B** (P2, doplňky stávajících stacků): `hedgedoc`, `bookstack`, `firefly`, `nodered`, `influxdb`, `onlyoffice`
3. **Wave C** (nové stacky): `stalwart` + `snappymail` → nový `mail` stack; `openplc` → engineering stack
4. **Wave D** (velké setupy): `moodle`, `kolibri`, `openemr`, `invoiceninja`, `dolibarr`
5. **Wave E** (nízká priorita): `joomla`, `wallos`, `farmos`

Každá Wave = 1 PR z worktree `cc/*` do `dev`. Po merge Wave A do `dev` se otevírá další worktree z `dev`.

---

## Modernizace / tech-debt
