# TODO

## DONE — Mac apps/utils added to playbook (default.config.yml)

### Added to `homebrew_cask_apps` (default true, disable in config.yml)
- **OnyX** — `onyx` — macOS maintenance, cache cleanup
- **iMazing v3** — `imazing` — iOS device management
- **CheatSheet** — `cheatsheet` — keyboard shortcut overview
- **Shottr** — `shottr` — screenshots + OCR + scrolling capture
- **DockDoor** — `dockdoor` — Windows-like window previews in Dock
- **Hyperkey** — `hyperkey` — capslock -> hyper modifier
- **LinearMouse** — `linearmouse` — mouse/trackpad customization
- **Syncthing (app)** — `syncthing-app` — P2P file sync
- **Hidden Bar** — `hiddenbar` — hide menu bar icons
- **Raycast** — was already in the list (line 299)

### Added to `homebrew_installed_packages` (CLI)
- **Security tools**: `trivy`, `grype`, `syft`, `gitleaks`, `nuclei`, `semgrep`
- **CLI agents**: `ntfy` (CLI client — server is a separate Docker role), `opencode`

### Added as commented-out (opt-in in config.yml)
- **Antinote** — `antinote` (cask exists)
- **Cotypist / boring.notch / flux-markdown / TypeWhisper** — not in brew; install manually from GitHub

### Added to `mas_installed_apps` (commented — requires `install_mas_apps: true` + mas login)
- Gifski (1351639930), QuickShade (931571202), Dropover (1355679052)

---

## PLAN — New Docker roles (`pazny.*`)

Each new service gets its own role in `roles/pazny.<service>/` following the compose-override pattern (see CLAUDE.md):
```
roles/pazny.<service>/
  defaults/main.yml      # version, port, data_dir, mem_limit
  tasks/main.yml         # data dir + compose override render
  tasks/post.yml         # (opt.) admin init, OIDC config, DB migrations
  templates/compose.yml.j2
```
Wire-up: `include_role` in `core-up.yml` / `stack-up.yml` + `install_<service>` toggle in `default.config.yml` + (optionally) nginx vhost + `authentik_oidc_apps` entry.

### Priority 1 — Infra / DevOps (extend existing devops stack)

| Role | Stack | DB | SSO | Priority | Note |
|------|-------|----|----|-----------|----------|
| `pazny.code_server` | devops | fs | proxy | **P1** | VS Code in the browser; heavy mem limit |
| `pazny.ntfy` | iiab | sqlite | proxy | **P1** | Push notifications; dual use: server + Alloy alerting sink |
| `pazny.miniflux` | iiab | postgres | **native OIDC** | **P1** | RSS reader; minimal, OIDC out-of-the-box |

### Priority 2 — Wiki / Edu / Docs

| Role | Stack | DB | SSO | Priority | Note |
|------|-------|----|----|-----------|----------|
| `pazny.hedgedoc` | b2b | postgres | **native OIDC** | P2 | Collaborative markdown — complements Outline |
| `pazny.bookstack` | b2b | mariadb | **native OIDC** | P2 | Wiki with books/chapters structure |
| `pazny.onlyoffice` | b2b | – (redis) | proxy | P2 | Doc server for Nextcloud/Outline; iframe integration |
| `pazny.moodle` | iiab | mariadb | OIDC plugin / proxy | P3 | LMS — large setup, first run 5–10 min migrations |
| `pazny.kolibri` | iiab | sqlite/pg | proxy | P3 | Offline education; pair with Kiwix |

### Priority 3 — Finance / ERP

| Role | Stack | DB | SSO | Priority | Note |
|------|-------|----|----|-----------|----------|
| `pazny.firefly` | b2b | mariadb | **native OIDC** | P2 | Personal finance; OIDC via OAuth2 provider |
| `pazny.wallos` | iiab | sqlite | proxy | P3 | Subscription tracker; lightweight |
| `pazny.invoiceninja` | b2b | mariadb | proxy | P3 | Invoicing + CRM |
| `pazny.dolibarr` | b2b | mariadb | proxy | P3 | ERP/CRM alt. to ERPNext |

### Priority 4 — Mail stack

| Role | Stack | DB | SSO | Priority | Note |
|------|-------|----|----|-----------|----------|
| `pazny.stalwart` | **new `mail` stack** | rocksdb (native) | LDAP/OIDC | P2 | JMAP+IMAP+SMTP+AS in one binary; WebAdmin UI |
| `pazny.snappymail` | mail | fs | proxy | P2 | Webmail frontend; connects to Stalwart via IMAP |

### Priority 5 — IoT / Industrial / Time-series

| Role | Stack | DB | SSO | Priority | Note |
|------|-------|----|----|-----------|----------|
| `pazny.nodered` | iiab | fs | proxy | P2 | Flow automation; pairs with Home Assistant, InfluxDB |
| `pazny.influxdb` | observability | native storage | proxy | P2 | Time-series DB; Grafana data source (alongside Prometheus) |
| `pazny.openplc` | **new `engineering` stack** | sqlite | proxy | P3 | PLC runtime + editor |
| `pazny.farmos` | engineering | postgres | proxy | P3 | Farm management |

### Priority 6 — Healthcare / specialized

| Role | Stack | DB | SSO | Priority | Note |
|------|-------|----|----|-----------|----------|
| `pazny.openemr` | **new `health` stack** | mariadb | proxy | P4 | EMR — sensitive data, requires HTTPS everywhere |

### Priority 7 — Optional CMS

| Role | Stack | DB | SSO | Priority | Note |
|------|-------|----|----|-----------|----------|
| `pazny.joomla` | iiab | mariadb | proxy | P4 | CMS alt. to WordPress; lower priority |

---

## Recommended implementation order

1. **Wave A** (P1, low-risk, immediately useful): `code_server`, `ntfy`, `miniflux`
2. **Wave B** (P2, extensions to existing stacks): `hedgedoc`, `bookstack`, `firefly`, `nodered`, `influxdb`, `onlyoffice`
3. **Wave C** (new stacks): `stalwart` + `snappymail` → new `mail` stack; `openplc` → engineering stack
4. **Wave D** (large setups): `moodle`, `kolibri`, `openemr`, `invoiceninja`, `dolibarr`
5. **Wave E** (low priority): `joomla`, `wallos`, `farmos`

Each Wave = 1 PR from `cc/*` worktree into `dev`. After Wave A merges into `dev`, the next worktree is opened from `dev`.

---

## Modernization / tech-debt
