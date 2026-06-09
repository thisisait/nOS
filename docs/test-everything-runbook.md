# Test-everything runbook

How to exercise the ENTIRE nOS surface for max resilience/stability, and what
must work identically on every machine vs what may differ. Authored 2026-06-09
from a config/coverage audit against an all-on tenant (pazny.eu).

A plain `ansible-playbook main.yml` with an all-on config (every `install_*`
true) covers ~80% of the surface — all Docker services, the host daemons, SSO
autologin, the at-rest gate, audit-chain. It does NOT exercise: `blank=true`,
the upgrade/coexistence/migration engines, backup **restore**, breach
notification, GDPR export/forget, MFA-on, multi-user RBAC, or the e2e suite.
Those are the gaps this runbook closes.

## Test cadence (four tiers)

1. **Plain full run** — `ansible-playbook main.yml`. Every config change / weekly
   drift check. Steady-state idempotent validation (a second run should be
   `changed=0`).
2. **Blank cold-start** — `ansible-playbook main.yml -e blank=true`. ~Monthly.
   Catches state-accumulation + cold-init bugs the idempotent run hides
   (Jellyfin/Open WebUI/GitLab first-init loops, first-admin seed, single-run
   autowiring). The canonical "fresh machine" baseline — run it immediately
   before any cross-machine replication test. Safe only where there is no
   critical data.
3. **Framework-feature exercises** — the `--tags` + CLI checklist below.
   ~Quarterly, and always after touching the relevant engine. Destructive/
   stateful: run AFTER a blank baseline, dry-run before the confirm flag.
4. **E2E + multi-user + MFA-on** — on-demand, operator-gated. Before a release
   tag. Run against a blank baseline with the framework exercises already green.

**Ordering rule:** blank → plain (verify `changed=0`) → framework (dry-run then
confirm) → e2e/multi-user/MFA last. Never run a destructive exercise
(`gdpr-forget --confirm`, `restore`, coexistence cutover) without a fresh
backup or blank baseline first.

## Framework-feature test checklist (exact commands)

- **Offline gates (fast, no services)** — every change:
  `python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py tests/upgrades/test_template_vars_resolvable.py tests/anatomy/test_lockfile_sync.py tests/anatomy/test_plugin_wiring_contract.py tests/anatomy/test_security_presenter_gates.py -v`
- **Smoke (HTTP, all tiers)** — `tools/nos-smoke.py --failed-only` then
  `tools/nos-smoke.py --json`. Expect every Tier-1/2 service in
  {200,204,401,redirect}.
- **Audit chain (gov, already on)** —
  `php files/anatomy/wing/bin/verify-audit-chain.php --db=$HOME/wing/app/data/wing.db --json`
  (valid HMAC per chained row; WORM triggers reject UPDATE/DELETE).
- **Upgrade engine** (dry-run first) —
  `ansible-playbook main.yml -K --tags upgrade -e upgrade_service=grafana -e upgrade_dry_run=true`,
  then drop `upgrade_dry_run`. CAUTION: an applied upgrade reverts on the next
  plain run unless the role-default version var (or `default.config.yml` pin) is
  bumped — verify the running image tag after.
- **Coexistence** (dry-run; queue may be empty) —
  `ansible-playbook main.yml --tags coexistence -e coexist_dry_run=true`. Real
  track: `… -e coexist_service=grafana -e coexist_tag=new -e coexist_version=12.0.0 -e coexist_base_port=3000 -e coexist_stack=observability -e coexist_data_source=clone_from:legacy -e coexist_dry_run=true`
  then drop the dry-run. Verify the second track on a shifted port + separate
  domain + no Authentik redirect_uri collision.
- **Migrations** — catalog is empty (only `_template.yml`). Author
  `files/anatomy/migrations/<ISO-date>-test.yml`, then
  `ansible-playbook main.yml -K -e auto_migrate=true`; confirm detect/action/
  verify/rollback fire. Otherwise defer.
- **Backup** (needs `configure_backup: true` + `restic_repo` set) —
  `ansible-playbook main.yml -K --tags backup`, then `restic -r <repo> snapshots`.
  RustFS nightly path: `launchctl list | grep nos.backup`;
  `aws --endpoint-url http://127.0.0.1:9010 s3 ls backups/`.
- **Restore** (the untested WRITE half — after a backup exists, blank-safe host) —
  plan `ansible-playbook main.yml -K --tags restore -e restore_date=YYYY-MM-DD --check`,
  then `… -e restore_auto_confirm=true`. Verify MariaDB+Postgres+volumes+
  authentik-blueprints replay, then re-run smoke.
- **GDPR Art-15 export** (dry-run default) —
  `ansible-playbook main.yml --tags gdpr-export -e export_subject=dsar-test@pazny.eu`,
  then add `-e export_confirm=true` (bundle → `~/.nos/dsar-exports/<subject>/`).
- **GDPR Art-17 erasure** (dry-run default) —
  `ansible-playbook main.yml --tags gdpr-forget -e forget_subject=dsar-test@pazny.eu`,
  then `-e forget_confirm=true`. Confirm exact-email-match delete (no
  cross-subject erasure) + residual-store scrub.
- **Breach (gov, Art-33)** —
  `php files/anatomy/wing/bin/breach-file.php --json=-` (pipe a JSON record),
  `php files/anatomy/wing/bin/breach-scan.php`,
  `php files/anatomy/wing/bin/breach-report.php --id=<n> --format=json`. Verify
  controller + DPO header from `instance_org`/`gdpr_dpo_name`/`gdpr_dpo_contact`
  + the 72h clock.
- **Agent loop** (pre-flight dry-run) — `bash tools/run-scout.sh --dry-run`,
  `… run-upgrade-architect.sh --dry-run`, `… run-remediator.sh --dry-run`,
  `… run-upgrade-advisor.sh --dry-run`. `launchctl list | grep pulse`;
  `curl http://127.0.0.1:18789/status` (OpenClaw). Full agent runs need
  `anthropic_api_key` (or a per-agent ollama override) in credentials.yml.
- **Git forge** (local-first) — validate-only `bash tools/recipe-pr.sh grafana`;
  open a local Gitea PR `bash tools/recipe-pr.sh grafana --open-pr`; verify
  Woodpecker CI fires; promote `bash tools/promote-public.sh <branch> --open-pr`.
- **MFA-on** (operator-gated, NOT cadence) — enrol TOTP on akadmin FIRST, flip
  `enforce_mfa: true`, run, then `grep authentik_break_glass_codes ~/.nos/secrets.yml`;
  verify Tier-2/3/4 do NOT get the Tier-1 MFA prompt.
- **Multi-user RBAC** (after a blank baseline) — invite tier2/tier3/tier4 test
  users via Wing `/users/invite`, enrol each in incognito. Verify isolation
  (tier2 git→200 / wing→403; tier3 nextcloud→200 / admin→403; tier4 only
  kiwix/jellyfin). Confirm Wing `/events` `actor_id` per user + the per-user
  Infisical secret + Stalwart mailbox were provisioned (`nos_invite_provisioning_enabled`).

## Replicable vs non-replicable (cross-machine parity)

**MUST be identical on every machine — assert it:** SSH + iiab-terminal TUI;
every Docker service healthy + smoke verdict per tier; SSO behaviour
(native_oidc auto-redirect, forward_auth gate, supports:no keeps its button);
platform-abstraction outputs (`nos_pkg_manager`/`nos_service_manager`/…);
audit-chain HMAC + WORM; the at-rest gate verdict; the backup CONTRACT
(AES-256, SQL dumps + volume tars + authentik-blueprints.json) and that restore
replays it; upgrade/coexistence/migration ENGINE logic; GDPR export/forget
bundle shape + exact-email-match semantics; agent-loop wiring; the git-forge
flow; language runtimes at MAJOR.MINOR.

**MAY differ — assert only that the role completes, never the value:** dotfiles
content; Dock layout; Finder/keyboard osx_defaults; terminal theme; Homebrew/
Cask app VERSIONS + install paths (`/opt/homebrew` vs `/usr/local`) — formula
NAMES are replicable, versions/paths vary; Mac App Store apps; sudoers custom
rules; Playwright e2e (UI flow on this machine only); machine-specific paths
(`restic_repo`, external-storage mounts — the CONTRACT is replicable, the path
string is local); VNC/ARD/Samba (SSH is the replicable remote-access path);
Tailscale hostname + `tenant_domain`.

**Rule of thumb:** SSH / services / SSO / networking / agent-loop / Docker /
state-management / compliance-logic / backup-contract = REPLICABLE (assert
identically). UI / shell / editor / Dock / themes / app-versions / local-paths =
COSMETIC (assert the role completes without error; do not assert the value).
