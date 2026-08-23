# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**nOS** — Ansible playbook that automates a macOS development environment on Apple Silicon (M1+). A complete self-hosted **Agentic Home Lab** with ~50 Docker services organized into 76 Ansible roles under the `pazny.*` namespace, 77 anatomy plugins for cross-service wiring, SSO (Authentik), secrets vault (Infisical), a unified web-desktop (nOS face), AI agents (OpenClaw + Ollama MLX, Hermes, OpenCode), observability (LGTM stack + InfluxDB), nightly backup to RustFS, and Tailscale remote access. Every service is FOSS; all data stays local. Fully replicable — `nos --remove=data --confirm` (legacy `blank=true`) wipes everything and reinstalls from scratch.

`nOS` is the open-source reference implementation behind [**This is AIT — Agentic IT**](https://thisisait.eu). Forked from geerlingguy/mac-dev-playbook → roles renamed under the `pazny.*` namespace.

## The repo is not the running system

**This checkout is the SOURCE. nOS runs from elsewhere on the host** — `~/stacks`,
`~/keap/src`, `~/face/src`, `~/wing`, launchd organs — so development here never
disturbs the estate serving on this machine. A converge is what moves source into
runtime; nothing else does.

The consequence, and it is the one that costs tokens when forgotten: **a git ref
answers "what is in the repo", never "what is running"**, and the two are
routinely different on purpose. The deployed KEAP sat three releases ahead of the
local checkout for a week in August 2026 and both were correct.

Same shape one level down: `default.config.yml` is the committed default and
`config.yml` (gitignored) overrides it, so a flag read from the default alone is
not the flag the estate uses. A local branch ref is likewise not `origin`'s until
someone fetches.

**Do not hand-derive any of this.** Ask, the way CLAUDE.md already tells you to
ask for the security queue:

```bash
tools/estate-status.py          # host vs local repo vs origin, all three
tools/estate-status.py --config install_gitlab   # the RESOLVED value, not the default
tools/red-status.py             # what is red RIGHT NOW, across every source
tools/agent-status.py           # what the agents did, and how the runs ended
tools/loop-status.py            # which weakness sources produce proposals
tools/cortex-drift.py           # the vendored organ vs ~/keap/src
tools/identity-status.py        # declared account roster vs what each realm holds
tools/nos-cc.sh                 # all of the above, live, in one tmux session
```

**Start a session with `tools/red-status.py`.** A notification is an event and
red is a state, and the estate had no way to ask for the state until 2026-08-18:
two nightly jobs failed for two days having correctly notified once, on the first
night, and then gone quiet by design — the repeat-failure rule that stops a
per-minute job flooding the inbox also stops a nightly one repeating news that
still holds. Establishing that took six ad-hoc SQL queries. The reader is
strictly a reader (gate `test_the_red_reader_only_reads.py`) and exits 0 whatever
it finds; an unreadable source is reported as UNKNOWN, never as green.

**A pane shows STATE, not scrollback.** `tools/nos-cc.sh` is the terminal control
centre those readers feed — built 2026-08-18 after the first bound ceremony ever
to complete named the gap as its own primary finding. Its one design rule is
worth carrying anywhere a surface gets built: a tailed log looks healthy right up
until its writer stops, and then it looks exactly the same, so every pane re-runs
a reader (`tools/nos-watch.sh`) and says so when the reader itself fails. It owns
one tmux session, anchors every target with `=` (tmux matches by PREFIX, so an
unanchored `-t nos` reaches the operator's own sessions), and never starts a
converge for you. Gate: `test_the_control_centre_shows_state.py`.

## Git Workflow

Three long-lived branches (`feat → dev → master`), revived 2026-05-17 after the `master`-only flow proved hard to gate once contributors arrive:

- **`master`** — release-ready trunk. **Protected: PR-only, fast-forward only, branch lock active on both GitHub and the local Gitea mirror.** Direct push refused. Release tags `v<semver>` live here.
- **`dev`** — integration branch. `feat/*` and `fix/*` merge here via fast-forward (CLI is fine, no PR required). `dev → master` happens via PR.
- **`feat/<short-name>`, `fix/<short-name>`** — short-lived, off `dev`. Squash WIP before merge.
- **`pzny`** — operator's local cross-feature workspace. Mirrors to local Gitea only (where Woodpecker runs the auto-deploy pipeline); never pushed to GitHub.

Worktrees branch off `dev` by default now (was `master`). The 2026-04-16 "never resurrect dev" rule is **superseded** — the three-tier flow is now load-bearing.

### Branch protection — one-time operator setup

The `master` protection above is **not** a workflow file — it is a GitHub repo-settings operation a fresh operator (or anyone forking nOS) MUST configure once, or direct pushes to `master` silently succeed and the release flow's PR gate is bypassed. The local `tools/git-hooks/pre-push` hook is a client-side backstop, not a substitute for the server-side rule.

**GitHub — Repo Settings → Branches → add a rule for `master`:**

- **Require a pull request before merging** (this is the `dev → master` PR gate).
- **Require status checks to pass** + **Require branches to be up to date before merging** (this is the *fast-forward-only* guarantee — `master` can never diverge from a validated `dev`).
- **Do not allow bypassing the above settings** — keep on so even admins go through the PR. (Sole-operator self-merge then needs `gh pr merge --rebase --admin`; see memory `nos-release-flow`.)
- **Allow force pushes: disabled** and **Allow deletions: disabled** — this is the "branch lock".

**Gitea mirror (local):** Repo → Settings → Branches → Branch Protection → `master`: enable "Block force push" + "Require pull requests" so the mirror lock matches GitHub.

**Verify with the RULESETS endpoint, not the branch-protection one (corrected 2026-08-02).** This repo's `master` is guarded by a **repository ruleset** (`Master protection`, created 2026-05-17: `deletion`, `non_fast_forward`, `required_linear_history`, `pull_request` ≥1 approval, `required_signatures`; bypass `OrganizationAdmin: always`). Classic branch protection is NOT configured, so `gh api repos/:owner/:repo/branches/master/protection` returns **404 while the branch is fully protected** — the old instruction here read that 404 as "unprotected, fix before the next release" and would send an operator to fix something that is not broken. Use:

```bash
gh api repos/:owner/:repo/rulesets                 # expect an active ruleset targeting ~DEFAULT_BRANCH
gh api repos/:owner/:repo/rulesets/<id>            # expect the five rules above
```

`git push origin master` from a non-fast-forward state must still be refused.

**Two release-flow facts learned cutting v0.10-beta:**

1. **`gh pr merge --rebase` fails on a release-sized PR.** 188 commits / 626 files / 133k additions → `rebaseable: false` with `mergeable: true`, error *"This branch can't be rebased"*. Not merge commits, not empty commits, not mixed authors, not signatures (v0.8/v0.9 were unsigned too and merged) — GitHub's rebase engine simply gives up at that size. `squash` is disabled repo-wide and `required_linear_history` forbids a merge commit, so **no PR merge method works** at release scale. When `merge-base(master, dev) == master tip` — always true for this flow — a rebase-merge IS a fast-forward, so `git push origin origin/dev:master` produces byte-identical history. That is the release-scale path; verify the merge-base equality first.
2. **Every commit is unsigned and the ruleset requires signatures.** The admin bypass logs `Found 188 violations` and lets it through, which means the signature rule has never once been satisfied — it is bypassed, not met. Either turn on commit signing (`commit.gpgsign`) or drop the rule; leaving it is a gate that only ever reports its own defeat.

## Commit Convention

- Format: **Conventional Commits** (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`, etc.)
- **No Co-Authored-By, no `--author` flag, no author-name override.** Git populates the author from `git config` automatically.
- **Subject ≤ 50 chars** (Conventional Commits soft limit). Hard cap 72.
- **Body: bullets, ≤ 6 lines.** Surgeon-tone — tendon touched, symptom, structural fix, gate that pins it. No multi-paragraph essays; deeper "why" goes in the PR description.

## Vision

An OS-agnostic "all-in-one PC" under the brand **This is AIT** (working engine name **nOS**, website [thisisait.eu](https://thisisait.eu)). All logic and data run on replicable self-hosted FOSS technologies. The Ansible playbook is the single source of truth. OpenClaw is the autonomous DevOps agent.

## Key Commands

```bash
# Full playbook run (sudo prompt via vars_prompt — no -K needed)
ansible-playbook main.yml

# Clean reinstall (wipes data, resets all services, prompts for a new prefix)
ansible-playbook main.yml -e blank=true   # = nos --remove=data --confirm

# Removal ladder via the nos CLI (installed by the playbook; docs/nos-cli.md).
# remove=none|data|deep|all — data = today's blank scope (source + images kept);
# deep = data + docker images/build cache + brew/npm/pip caches (= flush=deep);
# all = deep + user SOURCE (~/nos tenants, ~/.nos, ~/wing, …) (= uninstall).
# WITHOUT --confirm/-y a removal is a DRY RUN: prints the inventory, exits 0.
nos --remove=data              # dry run — inventory only, nothing removed
nos --remove=data --confirm    # execute interactively (ENTER + prefix gates)
nos --remove=all -y --leave    # non-interactive full teardown, then stop (handoff)

# Run a specific component by tag
ansible-playbook main.yml --tags "stacks,nginx"
ansible-playbook main.yml --tags "observability"
ansible-playbook main.yml --tags "ssh,iiab-terminal"

# Syntax validation
ansible-playbook main.yml --syntax-check

# Enable every known-good service (test profile; excludes erpnext/freepbx/spacetimedb)
nos [--remove=data --confirm] -e @profiles/all-on.yml

# Run the Docker stack layer autonomously — no sudo, no vars_prompt (agent/CI dev)
tools/nos-stacks.sh [tag]        # e.g. tools/nos-stacks.sh woodpecker

# LOCAL PRE-RELEASE GATE — run BEFORE a release push. Builds a FROZEN venv that
# mirrors the CI integration job 1:1 (ansible-core 2.21.0 + lockfile-pinned
# collections + Python 3.13.13) in .ci-venv/ (operator's ~/.ansible untouched).
tools/ci-local.sh                       # filter-load probe + syntax-check (fast)
tools/ci-local.sh ansible-playbook main.yml   # full wet-test in the frozen env
tools/ci-local.sh --rebuild             # recreate the frozen venv from scratch
tools/ci-local.sh --refresh-lock        # re-resolve ranges → print versions to re-pin
```

**Frozen integration toolchain (the "1:1 local + CI" pipeline):** `tools/ci-freeze.env` (Python + ansible-core pins) + `requirements.lock.yml` (exact collection/role pins) are the single source of truth consumed by **both** `tools/ci-local.sh` and the CI integration jobs (`.github/workflows/ci.yml`). The operator's daily driver stays **ansible-core 2.20.5** (`.python-version` pins Python 3.13.13); the frozen venv is the **2.21.0 mirror** used only for the pre-release wet-test, because the GitHub runner's filter-load path imports `VaultDecryptionContext` (a 2.21 symbol). Refresh both files together via `tools/ci-local.sh --refresh-lock`. **Honest caveat:** GitHub's hosted macOS runner is NOT the operator's Mac (its framework-Python custom-module quirk is why macOS Integration is `continue-on-error`); this freezes the **toolchain**, not the **environment** — a truly identical macOS environment needs a self-hosted runner (deferred).

## Architecture

### Vocabulary — `tier` vs `layer`

**`tier` means RBAC and nothing else** (1–4, who may reach a service). The word carried
four unrelated meanings until 2026-08-07; the axes and the settled rules live in
[docs/doctrine/layers.md](docs/doctrine/layers.md) — read it before adding a third
adjective to a service.

- **`layer`** (L0 substrate · L1 platform · L2 application · L3 custom) is the new axis:
  *what else breaks when this stops*. It is DERIVED from the graph's service→service
  dependency edges — live since R2 (2026-08-07, 35 edges; gate
  `test_service_layer_is_derived.py`); services without a survey carry
  `layer_withheld`, never a guess (`layers.md` §4).
- **`F1`–`F4`/`H`** is face-app build complexity, already prefixed
  ([docs/doctrine/face-app-tiers.md](docs/doctrine/face-app-tiers.md)).
- **Delivery tier is retired.** Say **role service** (`roles/pazny.<name>/`) or
  **manifest app** (`apps/<name>.yml`). No code ever branched on it.

### Anatomy — the structural backbone

> **Doctrine source:** `docs/bones-and-wings-refactor.md` §1.1 + §6.

The core of nOS is the **anatomy** — a layered metaphor for how the platform is wired:

- **Bones** (`files/anatomy/bone/`) — Bone, the local FastAPI bridge between Ansible runs and Wing's SQLite store.
- **Wings** (`files/anatomy/wing/`) — Wing, the Nette PHP security-research dashboard + state-framework UI.
- **Pulse** (`files/anatomy/pulse/`) — Pulse daemon, the host-side scheduled-job runner.
- **Veins** (carriers) — Bone↔Wing HTTP, callback telemetry, plugin-loader hook channels.
- **Tendons** (cross-service wiring) — what each plugin's `lifecycle:` block declares (renders, dashboard provisioning, post-API setup).
- **Nerves** — agentic feedback loops: A8 conductor → Pulse jobs → audit lineage. Components are live (A8 conductor agent, A14 AgentKit runtime, `actor_action_id` audit lineage); the scheduled *closed-loop* conductor (auto-run on a cadence) is still queued.
- **Cortex** (KEAP — external repo `thisisait/nos-keap` (public; org-transferred 2026-07-13 from `budweis-dev/knowledge-explorer-and-preserver`, old path redirects), deployed by `roles/pazny.keap` + `keap-base` plugin) — the knowledge layer of the brain: curated ~790-node taxonomy, content links resolved into the live content services (Kiwix, Calibre-Web, Nextcloud, Open WebUI), a capture/preservation review queue, and the agent-facing knowledge API (`/agent/v1`, loopback + scope-split bearer tokens) that AgentKit agents query. Unlike Bone/Wing/Pulse it runs as a Docker service (iiab stack, `header_oidc`, `gated_net`-only per SEC-02), built from a git-cloned source at `keap_repo_ref`.

When working within the anatomy use **surgeon-like commit messages**: name the exact tendon / vein / bone touched, the symptom that surfaced the issue, the structural change that closes it, and the test that pins it. See P0.x commit series (`12a7828..ca26bd7`) for examples.

### Role-based service delivery (76 roles under `pazny.*`)

Every Docker service is owned by an Ansible role in `roles/pazny.<service>/`. Each role follows the **compose-override pattern**:

```
roles/pazny.<service>/
  defaults/main.yml         # version, port, data_dir, mem_limit defaults
  tasks/main.yml            # data dir + compose-override render
  tasks/post.yml            # (optional) post-start API calls, DB setup, admin init
  templates/compose.yml.j2  # Docker Compose service fragment (no top-level networks:)
  handlers/main.yml         # (optional) service-specific restart handler
  meta/main.yml             # role metadata
```

**Compose-override merge:** each role renders `templates/compose.yml.j2` into `{{ stacks_dir }}/<stack>/overrides/<service>.yml`. Orchestrators (`core-up.yml`, `stack-up.yml`) use `ansible.builtin.find` to discover override files and pass them as `-f` flags to `docker compose up`. Base stack templates declare only `services: {}` + networks — the real service definitions come from role overrides.

**Role invocation with tag inheritance:** `include_role` needs both `apply: { tags: [...] }` **and** `tags: [...]` on the task itself so CLI `--tags` filtering actually reaches the inner role tasks.

**`--tags <svc>` compose-up auto-fire (A17, 2026-05-20):** every task in the compose-up flow (`tasks/stacks/{core,stack}-up.yml`) carries `tags: ['stacks'|'core', 'always']`. Running `ansible-playbook main.yml --tags woodpecker` therefore renders the override AND recreates the container in one shot. Opt out with `--skip-tags stacks` (or `--skip-tags core`) when you want a render-only pass.

**Non-Docker roles** (wing, openclaw, iiab_terminal, bone, hermes, opencode, backup, state_manager, dotfiles, `mac.*`): wired via `import_role` in `main.yml` — these install directly on the host, not through Docker Compose.

### Configuration layering (later overrides earlier)

1. **`default.config.yml`** — every variable with a default (committed)
2. **`default.credentials.yml`** — every secret as a `{{ global_password_prefix }}_pw_*` template (committed)
3. **`config.yml`** — your feature-toggle overrides (gitignored)
4. **`credentials.yml`** — your secret overrides (gitignored)

Passwords follow the pattern `{global_password_prefix}_pw_{service}`. A blank run prompts for the prefix. Ansible `vars_files` precedence outranks role `defaults/main.yml`.

### Playbook execution flow (`main.yml`)

1. **Password-prefix prompt** (on a confirmed removal — `remove=data|deep|all` + `confirm=true`, legacy `blank=true`)
2. **Blank reset** — wipes Docker state, data dirs, and configs. Honors external-storage overrides via `tasks/stacks/external-paths.yml`, so data on `/Volumes/SSD1TB/` gets wiped rather than the empty `~/service` fallbacks.
3. **Auto-enable dependencies** — flips on PostgreSQL, Redis, MariaDB based on which `install_*` flags are set.
4. **Auto-generate secrets** — Outline, Bluesky, Authentik, Infisical, Vaultwarden, Paperclip.
5. **Host roles:** `osx-command-line-tools` → `pazny.mac.homebrew` → `pazny.dotfiles` → `pazny.mac.mas` → `pazny.mac.dock`.
6. **Host tasks:** macOS system prefs → SSH / IIAB Terminal → language runtimes → Nginx → external storage.
7. **`tasks/stacks/core-up.yml`** — `infra` + `observability` stacks (always first):
   - Role renders (compose-override templates)
   - `docker compose up infra -d` + `docker compose up observability -d` (non-blocking), then `tasks/stacks/wait-stacks-healthy.yml` polls every container to healthy
   - DB setup (MariaDB databases, PostgreSQL databases + `pgcrypto`)
   - Post-start roles: Authentik blueprints + OIDC, Infisical init, Bluesky PDS, Portainer admin + OAuth.
8. **Service configs:** Nginx vhosts, data dirs, Alloy scrape targets, observability dashboards.
9. **`tasks/stacks/stack-up.yml`** — the remaining stacks (`iiab`, `devops`, `b2b`, `voip`, `engineering`, `data`):
   - Role renders
   - `docker compose up <stack> -d` per stack (concurrent when `stack_up_parallel: true`, default; one-at-a-time when `false`), then the shared in-stream health-wait
   - Post-start roles: admin init, OIDC configuration, DB migrations, onboarding
   - Authentik service-side OIDC setup, Bluesky PDS bridge.
10. **Post-provision:** stack-health verification → service registry.

**Stack bring-up (A19, 2026-05-23):** bring-up is non-blocking `docker compose up -d`; `tasks/stacks/wait-stacks-healthy.yml` → `files/anatomy/scripts/stack-health-probe.py` then runs an **in-stream health-wait heartbeat**. Each `stack_wait_tick_interval` (default 15s) tick prints a per-stack readiness line into `ansible.log` (e.g. `iiab: 17/18 ready (waiting: jellyfin[starting])`) so a long bring-up never freezes the log. The wait is **STRICT** — every container must reach healthy, no tolerance escape hatch; slow services (GitLab cold init ~12 min) just need a generous `stack_up_wait_timeout` (default 540s; the all-on profile sets 1200s). `stack_up_parallel: false` brings stacks up one at a time to avoid Docker-daemon saturation on a cold blank. Applies to `core-up.yml`, `stack-up.yml`, and `apps-up.yml`.

**Key invariant:** infra + observability are **always required, always first**. Post-start tasks can assume MariaDB, PostgreSQL, Authentik, Infisical, Grafana, Loki, and Tempo are online.

### Docker stacks (9 compose projects in `~/stacks/`)

| Stack | Services (each owned by a `pazny.*` role) |
|-------|------|
| **infra** | MariaDB, PostgreSQL, Redis, Portainer, Traefik, Bluesky PDS, Authentik (server + worker), Infisical |
| **observability** | Grafana, Prometheus, Loki, Tempo, InfluxDB |
| **iiab** | WordPress, Nextcloud, n8n, Node-RED, Kiwix, offline maps, Jellyfin, Open WebUI, MCP Gateway (mcpo), Uptime Kuma, Calibre-Web, Home Assistant, RustFS, KEAP (cortex), Vaultwarden, ntfy, Miniflux |
| **apps** | Tier-2 manifest-driven apps (apps_runner — Documenso, 2FAuth, Qdrant, Roundcube) |
| **devops** | Gitea, Woodpecker CI, GitLab, Paperclip, code-server |
| **b2b** | ERPNext, FreeScout, Outline, HedgeDoc, BookStack, Firefly III, OnlyOffice |
| **voip** | FreePBX (Asterisk) |
| **engineering** | QGIS Server |
| **data** | Metabase, Apache Superset |

> **OnlyOffice (euro-office) vs Documenso — independent, non-competing services.** The table lists OnlyOffice under `b2b` and Documenso under `apps`; they serve orthogonal purposes and do NOT overlap. **OnlyOffice / euro-office** is an embedded **collaborative editing engine** (iframe-embedded in Nextcloud, BookStack, Outline) — it edits *live, mutable* documents. **Documenso** is a standalone Tier-2 **e-signature platform** (`apps/documenso.yml`) — e-signing requires *immutability*, the opposite invariant. The euro-office pilot (`ghcr.io/euro-office/documentserver`, a JWT-compatible OnlyOffice fork) only ever swaps the editing backend; it has no e-signing surface, so **Documenso stays regardless**. See `roles/pazny.onlyoffice/defaults/main.yml` ("Documenso is NOT covered by euro-office (no e-signing) and stays") and the pilot devlog `docs/devlog/nos-core/2026/2026-06-13-euro-office-pilot.md` for the historical context.

**Bring-up tuning vars** (`default.config.yml`): `stack_up_parallel` (default `true`; `false` = one-at-a-time, contention-free cold blank), `stack_up_wait_timeout` (default 540s; per-stack STRICT health budget), `stack_wait_tick_interval` (default 15s; heartbeat cadence). **`profiles/all-on.yml`** is a committed test profile that enables every known-good service (excludes erpnext/freepbx/spacetimedb), forces sequential bring-up + 1200s timeout — run with `nos [--remove=data --confirm] -e @profiles/all-on.yml`. **`tools/nos-stacks.sh [tag]`** runs the stack layer with no sudo and no vars_prompt (compose-up tasks carry zero `become:`; `-e nos_sudo_password=''` skips the prompt) — for agent/CI dev; refuses every removal token (`remove=`/`confirm=true`, legacy `blank=`/`flush=`/`uninstall=`).

### Non-Docker applications

- **OpenClaw** — AI agent daemon via launchd, Ollama 0.19+ with the MLX backend
- **Hermes** — cross-channel agent gateway (host daemon, Ollama MLX + FastAPI web UI). Sibling of OpenClaw, NOT a Docker service. Opt-in launchd web-UI daemon via `hermes_daemon_mode` (default OFF; loopback-only); `files/anatomy/plugins/hermes-base/plugin.yml` wires forward-auth + GDPR + A9 notification so the auto-derived `hermes.<tld>` Traefik route is Authentik-gated (was 404 — no Provider registered). Channels (Telegram/Discord) stay manual `hermes gateway install`.
- **OpenCode** — agentic coding helper
- **IIAB Terminal** — Python Textual TUI, SSH `ForceCommand` for the `home` user
- **Wing** — security-research dashboard; source at `files/anatomy/wing/`, host launchd as of anatomy A3.5 (FrankenPHP single binary)
- **Bone** — local REST API bridge; source at `files/anatomy/bone/`, host launchd as of anatomy A3a
- **Pulse** — scheduled-job daemon; source at `files/anatomy/pulse/`, host launchd skeleton as of anatomy A4
- **Cortex (daemon)** — the reasoning organ, fourth host organ beside Bone/Wing/Pulse: loopback-only Node daemon (`roles/pazny.cortex`, `install_cortex`) serving `/agent/v1/validate` from the vendored KEAP port at `files/anatomy/cortex/`. Distinct from "Cortex (KEAP)" above — the Docker-served knowledge layer
- **Conductor** — autonomous DevOps agent; profile at `files/anatomy/agents/conductor/`, first-class Wing consumer as of A8

### IAM & SSO (Authentik)

Central SSO via Authentik at `auth.<tld>` (default `auth.dev.local`). OIDC providers + applications are generated from per-plugin `authentik:` blocks in `files/anatomy/plugins/<svc>-base/plugin.yml`, harvested by `authentik-base`'s aggregator into `inputs.clients` and rendered into the live Authentik blueprint by the plugin loader (D1.2/D1.3 cutover, 2026-05-05). The legacy central `authentik_oidc_apps` list in `default.config.yml` was retired in D1.3 — only the empty stub survives as the Tier-2 apps_runner extension channel.

> **Plugin wiring contract (2026-05-23):** every plugin manifest block (`authentik`, `notification`, `pulse`, `compose_extension`, `observability`, `lifecycle`, `requires`) has a documented status — which blocks have a *live consumer* vs *forward-ready metadata* — in `files/anatomy/docs/plugin-wiring-capabilities.md`, pinned by `tests/anatomy/test_plugin_wiring_contract.py` and measured by `tools/plugin-wiring-report.py`. Notification routing is unified at the canonical A9 severity shape (`on_critical`/`on_high`/`on_medium`/`on_low`/`on_info` → `wing-inbox`|`ntfy`|`mail`) across **every service plugin** (60/60 as of 2026-08-18; 9 of the 16 composition plugins carry none by design). Do not copy the tally forward — ask `tools/plugin-wiring-report.py`.

**β1.A (2026-05-05) doctrine — three SSO buckets, not two:**

- **`native_oidc`** — service consumes OIDC at app level. Operator clicks "Sign in with Authentik" inside the service. Per-user identity flows into the service.
  - **env-driven:** Grafana, Outline, Open WebUI, n8n, GitLab (omniauth), Vaultwarden, WordPress, Infisical, Miniflux, HedgeDoc, BookStack, Node-RED (β1.B passport-openidconnect)
  - **FreeScout — ASPIRATIONAL, not live (measured 2026-08-02).** The `FREESCOUT_OIDC_*` env block renders, but it is consumed by the `freescout-oauth` **module**, and both upstream sources are HTTP 404 — so `/data/Modules` is empty and `/login` shows the local form with no Authentik button. The clone task reported `changed` on every converge by matching git's `"Cloning into…"`, which prints before the failure. Do **not** count FreeScout as native_oidc until a reachable module source exists; see `roles/pazny.freescout/tasks/post.yml` header and RELEASE.md v0.10-beta §Known open.
  - **file/API-driven:** Gitea (Admin API), Nextcloud (`occ`), Portainer (`PUT /api/settings`), ERPNext (Frappe Social Login Key via bench), Home Assistant (auth_oidc HACS plugin), Jellyfin (SSO-Auth server plugin), Superset (`OAUTH_PROVIDERS` in superset_config.py)

- **`header_oidc`** — Authentik proxy outpost forwards `Remote-User` / `Remote-Email` headers; service auto-creates the local user from headers. True SSO from the user POV (no service-side login screen) but no per-app OIDC client.
  - Firefly III (β1.A 2026-05-05), KEAP/cortex (`X-Authentik-uid`-keyed per-user rows, 2026-07-10)

- **`forward_auth`** — pure access gate. Authentik session = "you're in"; service has no per-user state. Same Authentik provider object as header_oidc.
  - Uptime Kuma, Calibre-Web, Kiwix, Paperclip, Wing, code-server, ntfy, InfluxDB (OSS), ONLYOFFICE, Mailpit, Metabase, SpacetimeDB, OpenClaw, Hermes, Qdrant, SnappyMail, Woodpecker (route gate on top of Gitea-OAuth app-auth)

- **No SSO:** FreePBX, QGIS
- **AT Protocol identity:** Bluesky PDS (the Authentik→PDS bridge auto-provisions `@user.bsky.<tld>` accounts)

The trichotomy makes the runtime semantics legible: native_oidc and header_oidc both grant true SSO with per-user identity; forward_auth is access control without per-user state. See `docs/native-sso-survey.md` for the full audit (verdicts, costs, edge cases) and `docs/upstream-pr-opportunities.md` for the FOSS contributions that would let nOS flip individual forward_auth services to native_oidc (rather than maintaining local sidecars / forks / hacks).

Cookie domain `.<tld>` enables cross-subdomain session sharing. Embedded outpost binds to every `header_oidc` + `forward_auth` provider via the `10-oidc-apps.yaml` blueprint render. The `authentik_app_tiers` map in `default.config.yml` survives as the per-slug → RBAC tier override; per-plugin `authentik.tier` is the new source of truth.

### RBAC (role-based access control)

Four access tiers bound to Authentik groups via expression policies (`authentik_rbac_tiers` + `authentik_app_tiers` in `default.config.yml`). The per-tier service lists below are **representative, not exhaustive** — the authoritative per-service tier is each plugin's `authentik.tier` (with `authentik_app_tiers` as the legacy Tier-2 fallback):
- **Tier 1 (admin):** Portainer, Infisical, Grafana — `nos-providers`, `nos-admins`
- **Tier 2 (manager):** Gitea, GitLab, n8n, Superset, Metabase, Paperclip, ERPNext, FreeScout — + `nos-managers`
- **Tier 3 (user):** Nextcloud, Outline, Open WebUI, nOS face, Vaultwarden, Uptime Kuma, Calibre-Web, Home Assistant — + `nos-users`
- **Tier 4 (guest):** Kiwix, Jellyfin, WordPress — + `nos-guests`

Group names are configurable via `authentik_rbac_tiers`. Legacy installs provisioned before 2026-04-22 carry the old `devboxnos-*` prefix — migrate by updating group names in Authentik, or run `nos --remove=data --confirm` to regenerate.

### Secrets management

- **Infisical CE** (`vault.dev.local`) — central vault for infra secrets, REST API + CLI
- **Vaultwarden** (`pass.dev.local`) — Bitwarden-compatible personal vault for tenants

### Observability (Apple Silicon optimized)

- **Metrics:** Grafana Alloy (`prometheus.exporter.unix`, ARM64-safe) → Prometheus
- **Logs:** Alloy tails Nginx / PHP / agent logs → Loki
- **Traces:** OTLP receiver (gRPC `:4317`, HTTP `:4318`) → Tempo

### State & Migration Framework

Declarative state and safe transitions for long-lived installs. Four surfaces:

- **State** — `state/manifest.yml` (committed, expected shape) vs. `~/.nos/state.yml` (runtime, generated per run by `pazny.state_manager`). Merged, never overwritten. `~/.nos/` is the runtime side-car — delete it and the next run regenerates.
- **Migrations** — one-shot global transitions (rename `devboxnos-*` → `nos-*`, move state dirs, rewrite identifiers) in `files/anatomy/migrations/<ISO-date>-<slug>.yml` (moved from `/migrations/` in 2026-05-03 anatomy A1). Run automatically early in the `tasks:` section (after host roles) — moved out of `pre_tasks` 2026-05-10 because `pre_tasks` runs before Homebrew Python and `nos_state` needs PyYAML. Idempotent: each step has `detect` / `action` / `verify` / `rollback`. Breaking migrations prompt for confirmation unless `-e auto_migrate=true`.
- **Upgrade recipes** — per-service version transitions in `upgrades/<service>.yml`. `pre` / `apply` / `post` / `rollback` phases. Invoked explicitly (`--tags upgrade -e upgrade_service=<svc>`) or via Wing. Covers breaking patterns like `pg_upgrade`, `mariadb-upgrade`, Grafana dashboard-preserving bumps.
- **Coexistence** — dual-version operation via `nos_coexistence` module. Provision a second track on a shifted port with cloned data, test, cut over via atomic Nginx reload, clean up after TTL. Supported: Grafana, Postgres, MariaDB, Authentik (special), Gitea, Nextcloud, WordPress.

Observability: a callback plugin (`callback_plugins/wing_telemetry.py`) emits structured events for every task + framework action to Bone → Wing SQLite (with `~/.nos/events.jsonl` fallback). Wing exposes `/migrations`, `/upgrades`, `/timeline`, `/coexistence` views. Custom Ansible modules: `files/anatomy/library/nos_state.py`, `nos_migrate.py`, `nos_authentik.py`, `nos_coexistence.py` (moved from `/library/` in 2026-05-03 anatomy A1; `ansible.cfg` declares the new path).

Authoring: see [files/anatomy/docs/framework-overview.md](files/anatomy/docs/framework-overview.md), [files/anatomy/docs/migration-authoring.md](files/anatomy/docs/migration-authoring.md), [files/anatomy/docs/upgrade-recipes.md](files/anatomy/docs/upgrade-recipes.md), [files/anatomy/docs/coexistence-playbook.md](files/anatomy/docs/coexistence-playbook.md), [files/anatomy/docs/wing-integration.md](files/anatomy/docs/wing-integration.md). Authoritative spec: [files/anatomy/docs/framework-plan.md](files/anatomy/docs/framework-plan.md). (All these were moved from `/docs/` to `files/anatomy/docs/` in anatomy A1 per the operator-runbook-vs-agent-contract split rule — `docs/bones-and-wings-refactor.md` §4.2.)

### Reverse proxy: Traefik (primary) + host nginx (opt-in fallback)

Traefik in a container is the default edge proxy as of C1 (2026-04-29). It binds 80/443 unconditionally and serves both Tier-1 and Tier-2 services through two providers:

- **File provider** — `traefik_dynamic_dir/services.yml` is auto-derived from `state/manifest.yml`. Every Tier-1 service with `domain_var` + `port_var` set in the manifest gets a router + service block. No per-role edits — one central YAML.
- **Docker provider** — Tier-2 apps in the `apps` compose stack emit Traefik labels in their compose service block. The runner (`files/anatomy/library/nos_apps_render.py`) auto-generates the labels from the manifest.

Authentik forward-auth is a file-provider middleware (`authentik@file`), applied via Tier-1 routers' `middlewares=` field or Tier-2 labels. TLS reads the same cert path nginx used (`{{ tls_cert_path }}` / `{{ tls_key_path }}`) — mkcert wildcards or LE wildcards Just Work.

`install_nginx: false` is the default. Host nginx remains as an opt-in fallback (`install_nginx: true`) for operators with bespoke vhost-level constraints — `tasks/nginx.yml` is fully gated behind the flag. Nginx vhost templates remain in `templates/nginx/sites-available/` for that path.

Authoritative guide: [docs/traefik-primary-proxy.md](docs/traefik-primary-proxy.md).

### Manifest apps (apps_runner onboarding)

For long-tail self-hosted apps that don't merit a full `pazny.<name>` role, drop a YAML manifest at `apps/<name>.yml` and re-run the playbook. `pazny.apps_runner` discovers manifests, validates them (via `files/anatomy/module_utils/nos_app_parser` — schema + GDPR Article 30 + TLS / SSO / EU-residency gates), resolves magic tokens, renders a single merged compose override, brings the apps stack up, and fires post-hooks (service-registry append, Wing systems ingest, Authentik blueprint reconverge, Bone HMAC `app.deployed` events, Portainer endpoint reg, Kuma monitor extension, GDPR upsert via Wing CLI, smoke catalog runtime extension).

GDPR enforcement is **mandatory** — the parser refuses any manifest without a complete `gdpr:` block (purpose, legal_basis enum, data categories, data subjects, retention horizon, processors, EU-residency flag). This is by design: GDPR Article 30 compliance is part of the deploy gate, not an afterthought.

Coolify (Apache-2.0) maintains ~280 compose templates that we can import via `tools/import-coolify-template.py` (rewrites their `${SERVICE_*}` token syntax to ours, scaffolds the `gdpr:` block with `TODO` sentinels the operator must fill in before the parser will accept the file).

Authoritative guides: [docs/tier2-app-onboarding.md](docs/tier2-app-onboarding.md), [docs/coolify-import.md](docs/coolify-import.md).

### Adding a new Docker service (role service)

**Current pre-Track-Q workflow.** After bones & wings A6.5 + Track Q, the target workflow becomes thin role + `files/anatomy/plugins/<service>-base/plugin.yml`; see `docs/bones-and-wings-refactor.md` §1.1/§13.1 and `files/anatomy/docs/role-thinning-recipe.md`.

1. Create a role `roles/pazny.<service>/` following the compose-override pattern above.
2. Add an `include_role` call in the right orchestrator (`core-up.yml` or `stack-up.yml`) — remember both `apply: { tags: [...] }` **and** `tags: [...]` so `--tags` filtering works.
3. Add an `install_<service>` toggle in `default.config.yml`.
4. Add a row to `state/manifest.yml` with `domain_var` + `port_var` so Traefik file-provider auto-routes it.
5. (Optional, pre-Q only) Add an OIDC entry in `authentik_oidc_apps` + env vars in the compose template. Do not use this pattern for roles already migrated to plugin-based autowiring.

### Adding a new app (manifest app)

```bash
cp apps/_template.yml apps/myapp.yml
$EDITOR apps/myapp.yml          # fill meta + gdpr + compose blocks
PYTHONPATH=files/anatomy python3 -m module_utils.nos_app_parser apps/myapp.yml   # smoke-parse (module_utils lives under files/anatomy/ since A1)
ansible-playbook main.yml
```

No code changes. The runner takes care of routing, secrets, and observability.

### Feature-toggle pattern

~94 `install_*` / `configure_*` boolean variables (count moves; grep `default.config.yml`). `when:` conditions + tags for CLI filtering. Bring-up tuning vars (`stack_up_parallel`, `stack_up_wait_timeout`, `stack_wait_tick_interval`) live in `default.config.yml`; `profiles/all-on.yml` is the committed "everything-on" override profile.

## Linting Rules

- **yamllint:** max line length 180 (warning)
- **ansible-lint:** skips `schema[meta]`, `role-name`, `fqcn`, `name[missing]`, `no-changed-when`, `risky-file-permissions`, `yaml`

## Lockfile discipline

**`composer.json` and `composer.lock` are always in sync. Same for any future Python lock (Pulse / Bone).**

Editing `files/anatomy/wing/composer.json` directly without running `composer update` ships a broken commit — the playbook's `pazny.wing/tasks/main.yml` task `[pazny.wing] Run composer install` exits 4 with a cryptic *"lock file is not up to date"* trace deep in a blank run. Two gates catch this BEFORE the playbook does:

1. **Pytest gate** — `tests/anatomy/test_lockfile_sync.py` runs `composer validate --strict --no-check-publish` against the wing tree. CI runs it on every PR/push (composer is installed in the `pytest` job). Local: `python3 -m pytest tests/anatomy/test_lockfile_sync.py`.
2. **Operator-side pre-flight** — `pazny.wing/tasks/main.yml` runs the same `composer validate` *immediately before* the install task. If lock is stale, the playbook fails at the validate step with a clear diagnosis.

Adding a Wing dep:

```bash
cd files/anatomy/wing
composer require <package> --no-install   # updates BOTH composer.json + composer.lock
git add composer.json composer.lock
```

Or for a manual edit you already made:

```bash
cd files/anatomy/wing
composer update <package> --no-install     # regenerates lock entry only
git add composer.lock
```

Never edit `composer.json` and commit without `composer.lock` updates. Same principle applies to any future `pyproject.toml` / `requirements.lock` for Pulse + Bone — when those gain explicit lock files, mirror these gates.

## Documentation doctrine (devlog epic, 2026-06-12)

**Live doctrine = `.md`** in `docs/` or `files/anatomy/docs/`. **History/narrative = devlog** entries under `docs/devlog/nos-core/` (authored via the `/devlog` skill, compiled by `tools/devlog-compile.py` into `state/devlog-bundle.jsonl`, synced into WordPress by `tasks/devlog-sync.yml`, published to GH Pages on release tags). **Completed plans/handoffs = `docs/archive/`** (grep inbound references before every move). `docs/active-work.md` is a NOW-only pointer, hard ceiling 150 lines (`test_active_work_slim.py`). On-site devlog namespaces (site/tenant/machine/user) live in the WordPress DB only and are written via `tools/devlog-post.py` — never raw curl, never the admin account; every write emits a Bone audit event as `actor_id: agent:devlog`. Doctrine: `docs/devlog/README.md`.

## Documentation Language

`README.md`, `TLDR.md`, inline comments, and task names are in **English**. The Czech-language legacy has been retired as part of the `nOS` rebrand. If you find residual Czech strings, translate them.

## Apple Silicon Constraints

- Target: ARM64 only (M1+). `homebrew_prefix: /opt/homebrew`.
- **`homebrew_prefix` is ISA-bound, not die-variant-bound.** `default.config.yml` resolves it via `ansible_facts['machine'] == 'arm64'` → `/opt/homebrew`, else `/usr/local`. Homebrew keys its prefix on the instruction-set architecture (`arm64` vs `x86_64`), NOT the CPU die variant: every Apple Silicon family — M1, M2, M3, M4 (incl. Pro/Max/Ultra), M5+ — reports `machine == 'arm64'` and shares `/opt/homebrew`. So the conditional already covers all current and future Apple Silicon sub-variants; there is no per-die path to add. The `else /usr/local` branch is the Intel (`x86_64`) fallback, kept only for completeness — Intel Macs are out of scope post-macOS 27. Pinned by `tests/anatomy/test_homebrew_prefix_isa_bound.py`.
- Ollama 0.19+: native MLX backend (57% faster prefill, 93% faster decode).
- Docker Desktop for Mac (not Colima / Lima).

## Known Tech Debt

Live items only. Closed epics live in "Recently shipped doctrine" further below — one-line pointers with links to the authoritative guide.

- **ansible-core 2.24 jump (future):** Track J Phase 4 migrated `ansible_env` → `ansible_facts['env']` (9 occurrences); Track H Phases 1-6 pinned the rest of the surface to 2.20 and verified forward-compat under 2.21.0rc1 (sandbox install, syntax + tests + ansible-lint production profile all clean). When upstream ships 2.24 stable, the upgrade is a single `requirements.yml` floor bump + collection version review + 1 blank — ~4 hours, not a Track. Floor today: ansible-core 2.20.5 (operator + CI matrix).
- **CI Integration runs ansible-core 2.21+ in an isolated venv — the "filter-less" CI red needed a NEWER ansible, not an older one (2026-06-08):** the 2026-06-08 CI saga (cascade of *"No filter named 'bool'/'to_nice_json'/…"* + `| default()` not trapping undefined, Integration jobs only) was a GitHub-runner anomaly: on these runners the full playbook's filter-load path imports **`VaultDecryptionContext` from `ansible._internal._yaml._dumper`** — a symbol **ADDED in ansible-core 2.21**. Our pin held ansible-core at **2.20.x**, whose `_dumper.py` lacks the symbol → `ansible.builtin.core` filter plugins get **skipped** → EVERY filter (incl. `default`) throws "No filter named" mid-run. It was **not** ansible-core 2.20.6, **not** Python 3.14, **not** the deprecated `{{ vars }}` path, **not** ansible.cfg, **not** a mixed/baked install (a clean-venv diagnostic — single `ansible.__path__`, `PYTHONPATH` unset, `import ansible.plugins.filter.core` OK — disproved all of those) — all earlier misdiagnoses; a dev box never reproduces it (the symbol matters only on this runner's load path) and pytest jobs stayed green because they don't run the playbook. **Fix:** the two Integration jobs install ansible into a fresh `python -m venv "$RUNNER_TEMP/nosvenv"` and prepend its `bin` to `$GITHUB_PATH`. 2.21 is forward-compat-verified (Track H, 2.21.0rc1) and still ships the deprecated `{{ vars }}` (removed only in 2.24), so the playbook runs unchanged; `<2.24` keeps `{{ vars }}` working. The operator baseline stays **2.20.5** locally — CI's 2.21 is just the wet-test floor that satisfies the runner. **FROZEN 1:1 (2026-06-08, post-saga):** the venv ansible-core (now pinned exactly to **`ansible-core==2.21.0`**, the only 2.21 release) + the galaxy collections (now installed from `requirements.lock.yml`, exact pins) come from a single source of truth — `tools/ci-freeze.env` + `requirements.lock.yml` — consumed by both the Integration jobs AND `tools/ci-local.sh`, the **local pre-release gate** that reproduces the frozen venv on the dev box (filter-load probe + syntax-check, or a full wet-test). Running `tools/ci-local.sh` before a release push is what would have collapsed this 21-cycle saga to ~1; refresh both files via `tools/ci-local.sh --refresh-lock`. `.python-version` pins the local Python to 3.13.13. The 5 offline gates in `tests/anatomy/test_config_stock_jinja_only.py` + the stock-Jinja edits made while chasing this are kept as defensive portability hardening (behaviour-preserving on both 2.20.5 and 2.21). **macOS Integration is `continue-on-error: true` (non-blocking) as of 2026-06-08:** a *second*, independent GitHub-macOS-runner regression has the **custom-module interpreter** path ignore the env pin, the cfg `interpreter_python` pin, AND `-e ansible_python_interpreter` (extra-vars) — `nos_state` runs on an auto-discovered framework python WITHOUT pyyaml even though `$PY` provably has it (`PY-DEPS-OK`). 7 fixes couldn't redirect it; it is a runner/ansible-2.21 quirk, not a code defect. The Linux `integration-linux` job is the **intended** gating wet-test — but as of 2026-07-22 it does NOT yet prove the playbook: `stacks/infra/docker-compose.yml` is not rendered on Linux, `docker compose up infra` returns rc=1, and the STRICT health probe passes the resulting empty stack as `0/0 ready`. It had been green for weeks with no infra at all. See `docs/hidden_fees/08`; restore this claim only when (1)-(3) there are closed. Revert the macОС `continue-on-error` once the runner/ansible ships a fix. (Galaxy `504`s on the macOS job are a separate transient; the retry loop is 6×.)
- Mattermost removed (no ARM64 FOSS image). Vars + DB scaffolding purged 2026-05-16.
- ERPNext is **excluded from the all-on test profile** (heavy Frappe bench migration is unreliable on a cold blank; the `erpnext_post.yml` auto-retry mitigates but does not fully fix it). Effectively parked — enable via `install_erpnext=true` for a supervised run.
- Jellyfin / Open WebUI: known upstream bugs on fresh DB init — first run may restart-loop until data regenerates.
- Bluesky PDS federation not yet functional (the identity bridge creates accounts, but AT Protocol federation requires public DNS).
- Pre-2026-04-22 installs carry legacy `devboxnos-*` Authentik group names, `com.devboxnos.*` launchd bundle IDs, and the `~/.devboxnos/` state directory. Rebrand complete in-repo; migration on existing hosts needs a blank reset (or manual rename of the Authentik groups + `launchctl bootout` of the old plists).
- **Drift baseline staleness (security scan):** `docs/llm/security/scan-state.json` `last_full_scan` field can drift (>14 days = drift hook starts complaining). Long-term: A8 conductor agent auto-runs scans on schedule (queued). **The claim that `hooks/playbook-end.d/20-cve-drift-check.sh` "works today" was FALSE and is now fixed (2026-07-28):** two writers put two ISO-8601 spellings into `scan-state.json` (`scan-runner.sh` writes trailing-Z via jq `todate`; the security agent writes local time with a numeric offset), and both the jq `fromdateiso8601` call and the BSD `date -j -f` call accepted only the Z form. jq *aborts* rather than returning null, so the hook printed nothing, `drift-watch.sh` logged "produced no JSON — skip", and the nightly `conductor:security-drift-watch` had **never once produced a verdict** — silently, at exit 0. Its first successful run reported `pending_critical: 1` (REM-137, the 36-CVE Gitea 1.27.0 cluster). Gate: `tests/anatomy/test_drift_check_parses_both_iso_spellings.py`.
- **Security remediation backlog:** authoritative file `docs/llm/security/remediation-queue.json`. **This line no longer carries the numbers** — it carried them for four months and was wrong three times, every time because a reader copied a moving value forward. Ask instead:
  ```bash
  tools/rem-status.py            # tally + every pending HIGH/CRITICAL (reads the file only)
  tools/rem-status.py --all      # every pending row
  tools/discovery-scan.py        # compares the queue against `docker ps` and CLAUDE.md itself
  ```
  What stays here is the part that is knowledge rather than state:
  **A pending row is not proof of exposure.** Twelve rows so far were already LIVE at their fix version and had simply never been reconciled — the queue does not learn from a converge. **A row can be wrong in the other direction too:** REM-178 found REM-137 recording fix `1.27.0` while the pin and the running binary were `1.27.1`, and a recorded fix BELOW what the estate runs re-opens the gap if anyone acts on it. **`discovery:contradiction-scan` is a READER, not a writer** — it reports and files a roadmap row; closing stays a deliberate act with the evidence written into `resolved_by`. **The methodological lesson, which recurred three times in one batch: a GHSA with NO CVE id.** A scan phrased as "no new *CVE* past the pin" was literally true and wrong by six days (metabase), and the same blind spot produced the n8n and authentik waves — scan the vendor's advisory endpoint, not the CVE feed. Forward plan `docs/roadmap.md`; the structural follow-up (one SoT for exposure/RBAC/compliance) is `docs/archive/nos-genome-and-organelles.md`. Vendor-blocked: **FreePBX REM-014/046/113** (tiredofit image abandoned upstream 2022-04-30 — CRITICAL CVEs UNFIXABLE, operators accept the risk) **+ Ollama REM-126** (unauthenticated GGUF-quantization memory leak, no upstream fix); REM-064 (Open WebUI, authenticated-admin-only RCE) reclassified **wontfix**.
- **Success markers must be written by a reader, not by the attempting code (2026-08-01).** Two adversarial audits found the same shape across the scheduled-job layer and the post-start wiring layer: `dispatched_at` stamped by the sender even on failure; `status=scanned` stamped by a scan that never ran (and that fabricated freshness is what the drift watcher reads for staleness); a source that vanished recording nothing, so "Backup OK — N sources"; a `notify` that could never fire because `pip --quiet` empties the stdout its `changed_when` reads. **Corollary for gates:** a gate you can satisfy by editing the gate is not one — the pulse-command allowlist passed because the same commit taught it to render a token production had never heard of. Division of labour: **pytest owns the shape, `--tags verify` owns the effect, `nos-smoke --strict` owns end-to-end truth**; none may claim another's job. Live gates: `test_post_wiring_is_not_self_reporting.py`, `test_pulse_catalog_renders_every_token.py`, `test_host_daemon_source_restarts.py`, `test_backup_reaches_the_brain.py`.
- **OpenTofu post-cutover:** punch list #1–#3 shipped 2026-06-12 (backup custody via `run_tofu_state()`, enabled-filtering in registry→tfvars — NOTE, **corrected 2026-08-23**: a service flipping `enabled→false` on a live tenant plans as DESTROY, and the guard used to refuse it until a supervised apply or the next blank — asking for one decision twice, since `install_*: false` is already the operator's declaration and already stops the container. It now ATTRIBUTES each destroy: one whose service's install flag resolves off applies; one that is un-authored, or belongs to an ENABLED service, or sits at an address it cannot parse, still refuses and says which. Filter `nos_tofu_destroy_split`, gate `test_tofu_destroy_guard.py` — and the daily plan-only drift Pulse job `authentik-tofu-drift-base`). **Non-blank converge state-PK desync CLOSED 2026-06-15** — provider PKs churn out from under the state every re-converge (providers are `managed=None`, no single churner), which made the destroy-guard refuse every non-blank run; fix = a drift-conditional, identity-only **self-reconcile preflight** before `tofu plan` (`tools/tofu-authentik-reconcile.sh --preflight`, via the stable `application.slug → provider` bridge; gate `test_tofu_reconcile_preflight.py`), PROVEN live by a 3-converge arc. The destroy-guard also now catches dangerous in-place UPDATEs; adopt-path attachment import shipped. Authoritative: `docs/opentofu-authentik-cutover.md`.
- **Inspektor + Librarian agent runners — deferred (metadata.runner_status):** ship as AgentKit contract-only (no live execution). Inspektor waits on a trivy/grype/nuclei substrate plugin; Librarian waits on a Qdrant corpus pipeline. Scout, Remediator, Conductor are live. See `docs/sso-and-attribution.md` for the agent matrix.

## Operator gotchas (image / config-specific)

These aren't backlog — they're surprises a future operator can hit when extending the playbook. Each carries a hard rule.

**Moved out of this list** (2026-08-07, `docs/idea/13-relations.md` §R5 — a gotcha that is someone else's property is doctrine, and one about the operator's own machine is a runbook step): the two upstream-image facts (a healthcheck that cannot RUN in a `scratch`/rust-slim image; LSIO code-server serving plain HTTP on 8443) now live as citable sections in `docs/doctrine/foreign-properties.md` §2 / §3, cited from the code they govern; "run removals from a terminal outside the IDE" is `docs/nos-cli.md` §Where to run a removal FROM.

- **Mkcert CA gate for Authentik OIDC roles — NO LONGER A THING TO REMEMBER (gated 2026-08-07):** the mkcert root CA volume mount AND every env var pointing at it (`*_CA_CERTS`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`, `GF_AUTH...TLS_CLIENT_CA`, …) must sit inside `{% if install_authentik | default(false) and (tenant_domain_is_local | default(true) | bool) %}`. Without the TLD half, LE chain validation breaks on public TLDs; without the `install_authentik` half the container bind-mounts `{{ stacks_dir }}/shared-certs/rootCA.pem`, a path `tasks/stacks/core-up.yml:60-69` writes only when `mkcert -CAROOT` returns 0. `tests/anatomy/test_mkcert_ca_mount_is_guarded.py` now enforces both halves on all 25 references, keyed on the *container path* rather than an env-var name allow-list — writing this gate found `n8n-base` guarded on the TLD half alone. The canonical home stays the plugin compose-extension (`files/anatomy/plugins/<service>-base/templates/<service>-base.compose.yml.j2`), not the per-role compose template (D2 doctrine, 2026-05-05).
- **Forward-auth ≠ native-OIDC double-protection — GATED 2026-08-07:** services with `200 OK` on a Traefik route (e.g. Gitea, Portainer, HedgeDoc) are not bypassing SSO — they have native OIDC with a "Sign in with Authentik" button on their own login page. Stacking `authentik@file` on top is a double login for no security gain, and it 302's machine callers (the Woodpecker case, `roles/pazny.traefik/vars/main.yml:90-94`). `tests/anatomy/test_forward_auth_does_not_stack.py` refuses the contradiction across all four attachment paths — including the silent one, where `traefik_auth_modes` **falls through to `proxy`** for an id nobody listed (`services.yml.j2:54`). It shipped green: 19 native_oidc services, 19 correct edge modes, corroborated against the 19 `authentik@file` routers the live estate renders. What it cannot cover — the missing `access` facet, runtime opt-in flags like `paperclip_native_oidc_enabled`, and a native_oidc claim whose upstream OIDC does not exist (FreeScout) — is named in the file's header.
- **`{{ vars }}` eager-resolve trap — GATED, not remembered.** A var in `default.config.yml`/`default.credentials.yml` using a non-stock Jinja filter, or referenced only via `| default()` with no definition loading before core-up, aborts the run with `No filter named '<x>'`. Both variants are pinned by `tests/anatomy/test_config_stock_jinja_only.py`, which is more authoritative than this paragraph was: the two-page account that stood here is in the gate's own docstring, where a reader arrives by failing it. Strategic fix (stop passing `{{ vars }}` wholesale) rides the ansible-core 2.24 track.

## Recently shipped doctrine (one-line pointers)

Closed epics, archived here so future archaeology has a starting point. Authoritative content lives in the linked guide.

- **A3.5 Wing host-revert** (2026-05-04) — Wing runs as FrankenPHP launchd `eu.thisisait.nos.wing`. See Architecture / non-Docker section above.
- **Track Q autowiring** (2026-05-05 → 2026-05-07) — 63 plugins live, per-plugin `authentik:` blocks are SSO source-of-truth, central `authentik_oidc_apps` retained as empty Tier-2 apps_runner stub. See `files/anatomy/docs/role-thinning-recipe.md`.
- **D2 OIDC env block migration** (2026-05-05 → 2026-05-20) — role compose templates carry no OIDC env / mkcert CA / authentik extra_host blocks; plugin compose-extensions are the live render path. Stale breadcrumbs scrubbed 2026-05-20.
- **Phase 1 multi-agent batch retro** (2026-05-05) — worker-prompt doctrine for parallel work. See `docs/multi-agent-batch.md`.
- **Pulse Wing API** (shipped pre-A14) — `actionJobs`, `actionJobsDue`, `actionRuns`, `actionRunFinish` live in `files/anatomy/wing/app/Presenters/Api/PulsePresenter.php`. Pulse subscribers register via plugin manifest `pulse_jobs:` blocks.
- **Wing /events schema** (P1, 2026-05-05) — `source TEXT` + `actor_id` + `actor_action_id` columns + idempotent ALTER sweep.
- **wing-nginx stale-IP** (2026-05-04) — closed structurally by A3.5 (sidecar gone, host launchd replaces it).
- **E2E ephemeral SSO tester identity** (A13.6, 2026-05-07) — see `docs/e2e-tester-identity.md`.
- **SSO + identity attribution doctrine** (locked 2026-05-17) — trichotomy + body-attribution privilege-escalation fix. See `docs/sso-and-attribution.md`.
- **Notification fanout A9** (2026-05-16 / 17) — Bone→ntfy/SMTP routing, severity floors, daily digest, per-plugin templates, Stalwart TLS path. See `files/anatomy/docs/notification-fanout.md`.
- **A14 AgentKit runtime** (2026-05-07) — `App\AgentKit\*`, conductor agent first. See "AIT — AgentKit runtime" section below.
- **A15 Users + Invitations console** (2026-05-15+) — operator-facing /users page; `AUTHENTIK_BOOTSTRAP_TOKEN` env in `roles/pazny.wing/templates/wing.plist.j2`.
- **A16 Woodpecker CI autowiring** (2026-05-17) — Gitea repo creation + Woodpecker activation are playbook-managed.
- **A17 Stack-up tags + nos-push + deploy-trigger + Wing daemon hardening** (2026-05-20) — see commits `5c16a05..d87efef`.
- **A18 Invite-flow Cesta B (Infisical + Stalwart)** (2026-05-20) — `UsersPresenter::actionInviteCreate` optionally provisions per-user credentials into Infisical (`/users/<name>/`) and a Stalwart mailbox via JMAP after the Authentik invitation lands. Bundles Stalwart v0.11.8 → v0.16.6 upgrade (REST → JMAP API). See `docs/invite-provisioning.md`.
- **A19 plugin-wiring unification + orchestration health-wait** (2026-05-23) — notification routing canonicalized to 55/55 service plugins (gate `test_plugin_wiring_contract.py`, report `tools/plugin-wiring-report.py`, doctrine `files/anatomy/docs/plugin-wiring-capabilities.md`); in-stream health-wait heartbeat replaces blocking `--wait` (`wait-stacks-healthy.yml` + `stack-health-probe.py`); `stack_up_parallel`/sequential cold-blank + `profiles/all-on.yml`; sudo-free `tools/nos-stacks.sh`. See `RELEASE.md` (v0.2-beta).
- **A19 single-run autowiring** (2026-05-23) — `authentik_bootstrap_token` is playbook-generated and pinned as the Authentik blueprint token key, so Wing /users + invitations work on ONE blank run (no fetch-tool second pass); Woodpecker↔Gitea OAuth2 client is auto-created.
- **Upgrade-engine first-real-apply** (2026-05-30, `daf6a2b..865191d`) — the `--tags upgrade` apply path had never run for real (dry-run short-circuits before handlers → false-positive "success"). Now exercised end-to-end: `nos_migrate.py` renders recipe step strings via Jinja2 against controller-passed `tmpl_vars` (play-vars) + engine tokens; upgrade-table `exec.shell` wrapper aliases recipe `command:`→`cmd` + auto-`shell`; `compose.set_image_tag` gained `override`/`--force-recreate`/converge-on-drift, new `compose.recreate`; live container names are `<stack>-<service>-1`, base file `docker-compose.yml`; `upgrade_exclude` carve-out; **applied upgrades must bump the role-default version var or a plain `main.yml` re-render reverts them**. authentik major upgrades are forward-only (rollback `noop`; restoring the dump under new code half-migrates the schema). PG major stays on the coexistence track. See memory `upgrade-engine-apply-path`.
- **Wing tiered RBAC via Nette identity** (2026-05-30, `4f5c40f`) — added `nette/security`; `app/Security/ForwardAuthUserStorage.php` builds a stateless `Nette\Security` identity from the `X-Authentik-*` forward-auth headers each request (roles = Authentik groups → `$user->isInRole()`, no session churn so CSRF survives). `BasePresenter` gained `TIER_GROUPS` + `callerTier`/`requireTier` + a declarative `$minAccessTier` enforced by default in `startup()` — a privileged presenter gates with one property instead of an easy-to-forget `startup()` override; `requireSuperAdmin` still pins `nos-providers`+`nos-admins`. Gate contract: `tests/anatomy/test_security_presenter_gates.py`.
- **Observability veins + agent serialization + fleet review** (2026-05-30, `317f174..b0b2cbb`) — the `grafana-wing` composition plugin provisions the orphaned `wing_sqlite` datasource (the P1 datasource split left it in an unrendered `all.yml.j2`), so the SQLite-backed Grafana dashboards (99-playbook, 22-ai-agents) finally populate against a full `wing.db`; stub panels → real `agent_sessions`/`remediation_items` queries; idempotent `bin/ingest-{remediation,pentest}.php` re-sync (WHERE-guarded, `changed=0` steady-state); gitleaks 8.x positional-repo scan fix (un-empties Wing Inbox + Secret Findings); `pulse-run-agent.sh` mkdir mutex serializes claude-CLI agents (concurrent runs had crashed all participants); upgrade-advisor stale-recipe gaps closed (gitlab `from_regex` 18.10+ fix + 5 at-target forward-coverage tracks). Fleet review `docs/archive/fleet-review-2026q2.md` (fleet mode / Track F reality vs aspiration). New gate `tests/anatomy/test_grafana_datasource_provisioned.py`. See `RELEASE.md` (v0.3-beta).
- **v0.4-beta cross-platform (Linux)** (2026-05-31, `feat/linux-port`) — the full playbook provisions Ubuntu 24.04 LTS end-to-end, pinned by the standing `Integration (ubuntu-24.04)` CI wet-test (runs `ansible-playbook main.yml` on a GitHub Linux runner; the macOS `integration` matrix can't test Linux). `tasks/_platform.yml` resolves `nos_pkg_manager`/`nos_service_manager`/`nos_nginx_*`/`docker_bin` per OS; every brew install, `launchctl`/`osascript`/`defaults`/`pmset` call and macOS system-settings task is gated `nos_pkg_manager=='homebrew'` / `ansible_os_family=='Darwin'` — **macOS-byte-identical** (gates resolve true on a Mac). Bone/Pulse/backup/heartbeat render `systemd --user` units (`pazny.linux.systemd_user::ensure_unit`; a Persistent= timer's bound-oneshot failure at provisioning is tolerated); Wing runs the FrankenPHP single binary from `~/.local/bin`; Bone/Pulse venvs build from system `python3` (`tasks/python.yml` apt `python3-venv`). mkcert installs via apt (platform-aware CAROOT); `templates/nginx/nginx.conf` is portable (epoll / `user www-data` / `/var`+`/run`); **host-nginx per-service vhosts are macOS-only — Traefik is the Linux edge proxy**. `nos_docker_ready` (a final `docker info` probe) gates the whole compose layer so a Docker-less host (GitHub macOS runner) skips stacks gracefully. The macOS `integration` idempotence re-run (`changed=0`) is also green: **`wing_api_token` is now a persisted secret** (it regenerated every run → churned the Pulse launchd plist), install/PECL/dotnet/service-start `changed_when` key off real state, dnsmasq restart is notify-driven. **Deferred post-v0.4:** OpenClaw (Ollama/CUDA), Hermes, host-nginx vhost templates on Linux, fleet provisioning. See `RELEASE.md` (v0.4-beta) + `docs/linux-port.md`.
- **Gov / GDPR compliance batch** (2026-06-01) — Czech gov-readiness remediation, LIVE-validated on a `+all +gov` reconverge (failed=0). Structural P0 controls shipped **default-OFF + `profiles/gov-local.yml` opt-in**: enforced **MFA** (`50-mfa-policy.yaml.j2` → `nos-tier1-mfa-flow`, TOTP+WebAuthn, passkey resident-key `preferred`), **at-rest gate** (`tasks/preflight-at-rest.yml` FileVault/LUKS hard-fail), **backup-crypto** (AES-256 in `backup.sh`), **tamper-evident audit hash-chain** (`App\Model\AuditChain` + WORM triggers + `verify-audit-chain.php`), **breach-notification** (`BreachDeadlines` + `bin/breach-{file,scan,report}.php` + hourly Pulse + Tier-1 `/breaches`). GDPR articles: **Art-30** all 31 boilerplate purposes authored + Controller/DPO block (gate `test_gdpr_register_coverage.py`); **Art-17** honest DSAR terminal status (`record-dsar.php --update`), erasure-map backend-store reach, **exact-email-match delete** (no cross-subject erasure); **Art-15** right-of-access export (`tasks/gdpr-export.yml`, opt-in `[gdpr-export,never]`); **Art-7** consent registry (`gdpr_consent` + `bin/record-consent.php`, SSO-decoupled via never-called `consent_capture_satisfied`). Built via design + adversarial-review workflows (15 + 35 agents); the post-batch review's 22 findings were fixed/triaged. **STILL OPEN P0:** ISDS (datové schránky) + NIA/eIDAS federation (greenfield) + retention enforcement (metadata, not enforced). See `docs/compliance/gov-readiness-audit-2026q2.md` (reconciled 2026-06-01 scorecard) + `docs/security-baseline.md` + memory `gov-compliance-audit-findings`.
- **v0.5-beta SSO/MFA coherence + security cluster** (2026-06-06) — **MFA posture**: non-gov default is posture B (global MFA, remembered ~8h via `mfa_remember_window: "hours=8"`); `profiles/gov-local.yml` pins **strict step-up** (`seconds=0`, 2FA every auth-flow run). **SSO autologin** is honest-by-upstream: forward_auth passthrough services = true 0-click; native_oidc auto-redirect where upstream allows (Grafana), else "Sign in with Authentik" button; documented **ceilings** — portainer (OIDC button, no auto-redirect), infisical (CE org-OIDC enterprise-locked → forward_auth gate + own form), metabase (OSS no OIDC → gate + shared account). **Security cluster**: SEC-02 isolated the header-trust backends (calibre/2FAuth on Traefik-only `gated_net`, firefly on `b2b_net`+`gated_b2b_net` off the flat `shared_net`) — live-verified a peer-container header forge is BLOCKED; REM-043 closed the n8n SSRF via the built-in `N8N_SSRF_PROTECTION_ENABLED` guard (the queued `N8N_WEBHOOK_AUTH` advice was a non-existent env var); a durable MTI provider-flip reconcile in `main.yml` deletes the stale `OAuth2Provider` row when a service flips native_oidc→forward_auth (Authentik's `ProxyProvider` is a multi-table-inheritance subclass sharing the globally-unique Provider name). **Calibre** library autowiring: empty-DB bootstrap + Gutenberg sample book seed. See `RELEASE.md` (v0.5-beta).
- **OpenTofu Authentik cutover — ADR-0001 Phase 1 COMPLETE** (2026-06-12) — `authentik_engine: tofu` is the live authority: OpenTofu owns providers + applications + outpost attachments (data-driven `for_each` over `state/tofu-authentik-services.yml`, regenerated by `tools/tofu-authentik-gen-registry.py` from plugin + Tier-2 app-manifest `authentik:` blocks); the other six blueprints still apply imperatively by design. Validated: tofu-engine blank `failed=0`, `tofu plan` no-op, smoke 48/48, RBAC bindings + agent clients land. Five traps fixed + gated (blueprint auto-apply no-op render, `lookup('template')` registry bridge, `-parallelism=1` outpost-attachment race, Tier-2 registry harvest, `internal_host_ssl_validation=true`). **(2026-06-15) non-blank converge made idempotent** — the recurring state-PK desync is closed by a self-reconcile preflight (`tools/tofu-authentik-reconcile.sh --preflight`, gate `test_tofu_reconcile_preflight.py`). Runbook + punch list: `docs/opentofu-authentik-cutover.md`.
- **Security batch + converge-green** (2026-07-08) — cycle-16 queue committed + reconciled; the live-exploitable CRITICAL closed: **REM-118 FreeScout → nfrastack 2.1.3-php8.3** (CVE-2026-53595 9.4 unauth account takeover; cross-org tiredofit→nfrastack EOL + `SITE_URL`→`APP_URL`; `upgrades/freescout.yml` = first real upgrade recipe), **REM-110 Bone** recon endpoints scope-gated + PyJWT≥2.13.0, **REM-107 Alloy** OTLP loopback bind (`alloy_otlp_bind_addr`). Three degraded services that were failing the STRICT health gate unblocked: **qgis** idempotent entrypoint guard + `command:` restore (compose `entrypoint:` clears the image CMD), **gitlab** VirtioFS puma `realdirpath ENOTSUP` → tmpfs over the rails sockets dir, **puter** telemetry-preload crash → `command:` drop of the `-r telemetry.js` preload. All live-verified (61 containers, 0 unhealthy). Forward plan: `docs/roadmap.md` (revised 2026-07-08).

## AIT — AgentKit runtime (Anatomy A14, 2026-05-07)

Self-hosted, platform-agnostic, audit-first agent runtime. Lives under `files/anatomy/wing/app/AgentKit/` (PHP, namespace `App\AgentKit\*`). Borrows the Anthropic Managed Agents conceptual surface — agent / session / thread / outcome / vault / webhook — but every byte of state lives in `wing.db` so OpenClaw / future local LLMs swap in via a one-line URI change in `agent.yml`. Authoritative guide: `docs/ait-runtime-architecture.md`.

**Key contracts (locked by anatomy CI gates):**

- **Agent definition** = `files/anatomy/agents/<name>/{agent.yml, system.md, rubric.md}`. `agent.yml` validated against `state/schema/agent.schema.yaml` on every push by `tests/anatomy/test_agent_schema.py`. Name pattern `^[a-z][a-z0-9-]{1,38}[a-z0-9]$`, lower+dashes only.
- **Model URI scheme** = `<provider>-<model-id>`, dashes throughout (e.g. `anthropic-claude-opus-4-7`, `openclaw-qwen-coder-32b`). Pinned by `App\AgentKit\AgentLoader::isValidModelUri` + the schema regex + `tests/anatomy/test_agentkit_naming.py::test_uri_scheme_uses_dash_separator`.
- **LLMClient interface** has exactly 2 methods (`identifier()`, `send()`). Surface drift caught by `tests/anatomy/test_agentkit_naming.py::test_llm_client_protocol_is_minimal`. Both `AnthropicAdapter` (uses `anthropic-ai/sdk` composer dep) and `OpenClawAdapter` (HTTP to `OPENCLAW_BASE_URL`) honor the protocol.
- **Tables** (in `files/anatomy/wing/db/schema-extensions.sql`): `agent_sessions`, `agent_threads`, `agent_iterations`, `agent_vaults`, `agent_credentials`, `agent_subscriptions` (verified by `tests/anatomy/test_agentkit_naming.py::test_all_agentkit_tables_declared`), plus `agent_memory_stores` (the Dreams table, pinned by `tests/anatomy/test_agentkit_dreams.py`).
- **Audit lineage**: every LLM call → `events` row + OTel span + token tally in `agent_sessions`. `actor_action_id == agent_sessions.uuid` so a single `SELECT WHERE actor_action_id=?` reconstructs the entire run. 12 new event types (`agent_session_*`, `agent_thread_*`, `agent_iteration_*`, `agent_tool_use`, `agent_tool_result`, `agent_message`, `agent_grader_decision`, `agent_webhook_dispatch`, `agent_vault_resolved`).
- **OTel**: `App\AgentKit\Telemetry\OtelExporter` POSTs JSON spans to Alloy on `127.0.0.1:4318` (host config already opens both 4317 gRPC + 4318 HTTP). Service name `nos.agentkit`. Trace_id stored in `agent_sessions.trace_id` for Tempo deep-link from Wing /agents UI.
- **Vault**: `agent_credentials.secret_ref` is NEVER plaintext — it's a pointer (`env:VAR_NAME` or `infisical:/path`) resolved by `CredentialResolver` at session-open time. Plaintext only lives in function-local memory inside the adapter call.
- **Outcome iteration**: agents with `outcomes.rubric_path` enter the iteration loop — separate Grader LLM call returns strict-JSON `{result, feedback}`, runs in isolated context window. Max 3 iterations default, 10 max.
- **Webhooks (outbound)**: `WebhookDispatcher` fires HMAC-signed POSTs in Standard Webhooks v1 shape. Auto-disable after 20 consecutive failures.

**Composer deps added** (lockfile-sync gate enforces both committed): `anthropic-ai/sdk` (official), `open-telemetry/sdk` + `exporter-otlp` (official OTel PHP), `symfony/yaml`, `guzzlehttp/guzzle`.

**Runtime entry points:**
- CLI: `php files/anatomy/wing/bin/run-agent.php --agent=<name> [--prompt=...] [--vault=...] [--trigger=pulse|webhook|operator]`. Returns JSON summary, exit 0 on idle/satisfied, 1 on terminated, 2 on config error.
- Browser UI: `/agents` (catalog), `/agents/<name>` (detail), `/agents/<name>/sessions/<uuid>` (deep dive with threads + iterations + Tempo trace link).
- API: `GET /api/v1/agents`, `GET /api/v1/agents/<name>`, `GET /api/v1/agents/<name>/sessions`, `GET /api/v1/agent-sessions/<uuid>` (bearer auth).

**First agent shipped: `conductor`** (`files/anatomy/agents/conductor/`). System prompt + rubric describe the self-test ceremony — `mcp_wing GET /api/v1/hub/health`, `mcp_wing GET /api/v1/pulse_jobs`, etc. Conductor reports under markdown heading `## Conductor report` with sections `Health`, `Findings`, `Recommendations for operator`. Grader scores against `rubric.md` (evidence-discipline + structural).

**Post-A14 follow-ups — ALL SHIPPED (2026-05-15+; was a "deferred" list):**
- Multi-agent process pool — `AgentKit/ProcessPool.php`, instantiated in `Coordinator.php`
- Dreams (cross-session memory consolidation) — `AgentKit/Memory/Dreamer.php` + `MemoryStore.php` + `bin/dream-agent.php` + the `agent_memory_stores` table (pinned by `test_agentkit_dreams.py`)
- Operator-trigger UI button, per-agent webhook auto-fan-out, Infisical vault refresh
- Closed per `docs/active-work.md`; left here as a pointer so the changelog doesn't read as still-open.
