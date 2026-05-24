# nOS — Release notes

`nOS` is the open-source Ansible engine behind [**This is AIT — Agentic IT**](https://thisisait.eu): one command turns an Apple Silicon Mac into a reproducible, self-hosted, self-managing cloud of ~50 FOSS services behind one SSO.

Versioning is by git tag `v<semver>` cut from `master`. The prior tag was `v0.1-beta`.

---

## v0.2-beta (2026-05-23)

Bundle **A19** — plugin-wiring unification, orchestration health-wait, single-run autowiring — on top of the A1–A18 anatomy + security hardening that landed since v0.1-beta.

### Security

- **A1–A18 hardening** carried forward: ANSSI/GDPR baseline, per-service recovery posture catalog (SEC-15), Pulse stdout/stderr scrub before forwarding to Wing (SEC-9).
- **CSRF** — Wing Latte templates now emit a CSRF token on every browser POST form (SEC-14).
- **HMAC** — Bone event ingestion validates Standard-Webhooks-shaped HMAC; bash-built JSON bodies are canonicalized (`jq --sort-keys -c`) so signatures verify.
- **Secret lifecycle** — `agent_credentials.secret_ref` stays a pointer (`env:` / `infisical:`), resolved only in function-local memory; per-user invite credentials provisioned into Infisical + Stalwart (A18).

### Plugin wiring

- **Notification unification** — every service plugin now carries the canonical A9 severity-routing block (`on_critical` / `on_high` / `on_medium` / `on_low` / `on_info` → channels `wing-inbox` | `ntfy` | `mail`). **55/55 plugins** conform.
- **Wiring contract** — new CI gate `tests/anatomy/test_plugin_wiring_contract.py` pins the shape; `tools/plugin-wiring-report.py` measures coverage; `files/anatomy/docs/plugin-wiring-capabilities.md` documents which manifest blocks have a live consumer vs. forward-ready metadata.
- **Conformance fixes** — qdrant-base gained a `feature_flag`; gitleaks gdpr/schema blocks conformed.

### Orchestration

- **In-stream health-wait heartbeat** — stack bring-up changed from blocking `docker compose up --wait` to `docker compose up -d` plus a non-blocking health-wait (`tasks/stacks/wait-stacks-healthy.yml`, `tasks/stacks/health-tick.yml`, `files/anatomy/scripts/stack-health-probe.py`). Each ~15s tick prints a per-stack readiness line into the main `ansible.log` (e.g. `iiab: 17/18 ready (waiting: jellyfin[starting])`), so a long bring-up no longer freezes the log. Applied across core-up, stack-up, and apps-up. The wait is **STRICT** — every container must reach healthy, no tolerance escape hatch.
- **Sequential cold-blank** — new `default.config.yml` vars: `stack_up_parallel` (default `true`; set `false` to bring stacks up one at a time and avoid Docker-daemon saturation when enabling everything on a cold blank), `stack_up_wait_timeout` (default 540s; per-stack health budget), `stack_wait_tick_interval` (default 15s). Slow services (GitLab cold init ~12 min) just need a generous timeout.
- **All-on test profile** — `profiles/all-on.yml` enables every known-good service (excludes `erpnext` / `freepbx` / `spacetimedb`), forces sequential bring-up and a 1200s timeout: `ansible-playbook main.yml -e @profiles/all-on.yml [-e blank=true]`.
- **Sudo-free stack runner** — `tools/nos-stacks.sh [tag]` runs the Docker stack layer autonomously, without sudo and without the interactive prompt (compose-up tasks carry zero `become:`; `-e nos_sudo_password=''` skips the vars_prompt). For agent / CI-driven dev; refuses `blank=true`.

### Autowiring

- **Single-run bootstrap** — `authentik_bootstrap_token` is now playbook-generated and pinned as the Authentik blueprint token key, so Wing /users + invitations work on a single blank run (no fetch-tool second pass).
- **Woodpecker OAuth2** — the Woodpecker↔Gitea OAuth2 client is auto-created during provisioning.

### Blank-run hardening (2026-05-24)

End-to-end fixes surfaced while validating the STRICT all-on blank — each pins a tendon the heartbeat / strict-wait exposed:

- **Health-wait early-exit** — a `when:` on a *looped* `include_tasks` does not short-circuit, so the heartbeat ran the full time budget every time (and a flap on the final tick could false-timeout). Each tick task is now gated on `not _wait_done` so the loop genuinely stops at first all-ready.
- **Core-up ordering** — DB setup (MariaDB / PostgreSQL roles) now runs *before* the infra health-wait, so Authentik's Postgres role exists on a cold blank (was a deadlock: the strict wait blocked on a DB user that hadn't been created yet).
- **Blank-safe autowiring** — gitea repo + Woodpecker wiring uses Gitea **admin Basic auth over 127.0.0.1** (a pre-provisioned `gitea_api_token` is wiped by `blank=true` → 401); Woodpecker activation skips gracefully when its OAuth-derived PAT cannot yet exist. Post-config container checks resolve the running container by compose **label** — the old `-f <base> ps -q <svc>` returned "no such service" (base composes are `services: {}`), silently skipping every admin/OIDC task on a blank, so gitea had no admin user → 401.
- **Bone telemetry** — `app.deployed` HMAC timestamp uses the current epoch (`date +%s`), not `ansible_date_time.epoch` (frozen at gather_facts → >300 s stale on an hour-long blank → "timestamp out of window" 401). The play-level Bone restart handler now `bootout`+`bootstrap`s (env reload) instead of `kickstart -k`.
- **Uptime Kuma** — monitor setup tolerates Socket.IO event-delivery starvation under peak load: a larger per-event timeout, fail-fast after 3 consecutive timeouts (was a ~30-min hang), and a role-level retry until the load settles. A heavily-loaded blank may still defer monitor creation to a host-idle `--tags uptime_kuma` re-run (non-fatal — monitors/events are never lost).
- **Traefik** — Tier-1 routing resolves upstreams by container name on the shared network (the IPv6 host-gateway path produced 502s).

### Security review + hardening (2026-05-24)

A 5-agent audit (`docs/llm/security/2026-05-24-multiagent-review.md`) against the SEC-1..15 baseline — solid, no true CRITICALs after reconciliation. New hardening:

- **SEC-16** — weak-prefix gate: refuse `global_password_prefix` in {`changeme`, '', <12 chars} on a public tenant (it seeds DB roots, OIDC/agent secrets, admin pws). Lenient on `dev.local`; `-e allow_weak_prefix=true` bypass. Dead prefix-derived `NOS_DEPLOY_HMAC_SECRET` fallback + retired `BONE_SECRET` dropped from the launchd plists.
- **SEC-17** — Pulse execution-boundary command allowlist: the SEC-8 allowlist now enforces in the runner that spawns the process (not just the PHP create path), so *any* `pulse_jobs` row is gated. Child env scoped — secrets stripped (`WING_API_TOKEN`, …), job-supplied loader/PATH overrides (`DYLD_*`/`LD_*`) refused; `max_runtime_s` clamped.
- **SEC-18** — 83 `no_log: true` across 30 task files (admin pws/tokens were persisting in Wing's SQLite via the telemetry callback, which redacted by key-name only); the callback now scrubs by value too; every shell pipe gets `set -o pipefail`; the Bluesky bridge `| quote`s the Authentik-sourced email (injection).
- **portainer** — `--http-enabled` (2.19+ 303-redirects plain HTTP → HTTPS, which silently skipped admin-init + OAuth setup).

Deferred (tracked in the review): the OIDC/agent-secret compartmentalization refactor (mitigated now by SEC-16), deploy-trigger edge-gating, askpass-on-failure cleanup.

### Validated by

- STRICT all-on blank (`-e @profiles/all-on.yml -e blank=true`): **`failed=0`, zero fatal**, with the hardening live (M-SEC1 gate passes on a ≥12 prefix; `no_log`/pipefail post-config unaffected), **Kuma creating all 48 monitors in-context**, and **Bone `app.deployed` returning HTTP 200** (the timestamp fix).
- Gate suite green: `pytest` (1120 passed, 4 skipped — incl. the SEC-17 Pulse-allowlist tests), plugin-loader smoke (63 ok / 0 failed / 0 schema), wiring contract (DAG / gate-parity / notification), ansible-lint (`risky-shell-pipe` fixed, not skipped), `composer validate`, `--syntax-check`. `tests/e2e` runs in CI with a live tester identity.
