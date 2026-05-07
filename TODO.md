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

### Priority 1 — Infra / DevOps (extend existing devops stack)  —  ✅ DONE (Wave A)

| Role | Stack | DB | SSO | Priority | Status |
|------|-------|----|----|-----------|----------|
| `pazny.code_server` | devops | fs | proxy | **P1** | ✅ shipped |
| `pazny.ntfy` | iiab | sqlite | proxy | **P1** | ✅ shipped |
| `pazny.miniflux` | iiab | postgres | **native OIDC** | **P1** | ✅ shipped |

### Priority 2 — Wiki / Edu / Docs  —  partially done (Wave B)

| Role | Stack | DB | SSO | Priority | Status |
|------|-------|----|----|-----------|----------|
| `pazny.hedgedoc` | b2b | postgres | **native OIDC** | P2 | ✅ shipped |
| `pazny.bookstack` | b2b | mariadb | **native OIDC** | P2 | ✅ shipped |
| `pazny.onlyoffice` | b2b | embedded pg | proxy | P2 | ✅ shipped |
| `pazny.moodle` | iiab | mariadb | OIDC plugin / proxy | P3 | pending |
| `pazny.kolibri` | iiab | sqlite/pg | proxy | P3 | pending |

### Priority 3 — Finance / ERP  —  partially done

| Role | Stack | DB | SSO | Priority | Status |
|------|-------|----|----|-----------|----------|
| `pazny.firefly` | b2b | mariadb | REMOTE_USER proxy | P2 | ✅ shipped (OAuth2-provider pending) |
| `pazny.wallos` | iiab | sqlite | proxy | P3 | pending |
| `pazny.invoiceninja` | b2b | mariadb | proxy | P3 | pending |
| `pazny.dolibarr` | b2b | mariadb | proxy | P3 | pending |

### Priority 4 — Mail stack

| Role | Stack | DB | SSO | Priority | Note |
|------|-------|----|----|-----------|----------|
| `pazny.stalwart` | **new `mail` stack** | rocksdb (native) | LDAP/OIDC | P2 | JMAP+IMAP+SMTP+AS in one binary; WebAdmin UI |
| `pazny.snappymail` | mail | fs | proxy | P2 | Webmail frontend; connects to Stalwart via IMAP |

### Priority 5 — IoT / Industrial / Time-series  —  partially done (Wave B)

| Role | Stack | DB | SSO | Priority | Status |
|------|-------|----|----|-----------|----------|
| `pazny.nodered` | iiab | fs | proxy | P2 | ✅ shipped |
| `pazny.influxdb` | observability | native storage | proxy | P2 | ✅ shipped |
| `pazny.openplc` | **new `engineering` stack** | sqlite | proxy | P3 | pending |
| `pazny.farmos` | engineering | postgres | proxy | P3 | pending |

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

1. **Wave A** (P1, low-risk, immediately useful): `code_server`, `ntfy`, `miniflux`  —  ✅ DONE
2. **Wave B** (P2, extensions to existing stacks): `hedgedoc`, `bookstack`, `firefly`, `nodered`, `influxdb`, `onlyoffice`  —  ✅ DONE
3. **Wave C** (new stacks): `stalwart` + `snappymail` → new `mail` stack; `openplc` → engineering stack  —  pending
4. **Wave D** (large setups): `moodle`, `kolibri`, `openemr`, `invoiceninja`, `dolibarr`  —  pending
5. **Wave E** (low priority): `joomla`, `wallos`, `farmos`  —  pending

Each Wave = a multi-agent batch under the `worktree-agent-*` doctrine
(see [docs/multi-agent-batch.md](docs/multi-agent-batch.md)) merging onto `master`.
Open the next batch from fresh `master` after the previous wave merges.

---

## Modernization / tech-debt
