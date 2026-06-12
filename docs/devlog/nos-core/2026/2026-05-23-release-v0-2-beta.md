---
id: 2026-05-23-release-v0-2-beta
title: "v0.2-beta — The heartbeat release"
date: 2026-05-23
namespace: nos-core
summary: "A19 lands: stack bring-up gets an in-stream health-wait heartbeat instead of a frozen blocking wait, notification routing is unified across all 55 service plugins under a CI-pinned wiring contract, and a single blank run now autowires everything — including the Authentik bootstrap token and the Woodpecker↔Gitea OAuth2 client. Validating the STRICT all-on blank surfaced a chain of tendon-level bugs, each now pinned."
tags: [release, orchestration, plugins, notifications, security, blank-run]
release: v0.2-beta
actors: [pazny, claude]
related: [RELEASE.md]
---
v0.2-beta is the release where nOS learned to bring up ~50 containers without
either freezing the log or lying about readiness — and where "run the blank
once, get a working platform" stopped having asterisks.

## The health-wait heartbeat

The old bring-up was `docker compose up --wait`: correct, but a black box. On
an all-on cold blank, the log would go silent for ten minutes while GitLab cold
inits, and you couldn't tell a slow service from a hung one. The new flow is
non-blocking `up -d` plus an in-stream health-wait: every ~15 seconds a probe
prints a per-stack readiness line into `ansible.log` —
`iiab: 17/18 ready (waiting: jellyfin[starting])`. The wait is **STRICT**:
every container must reach healthy, no tolerance escape hatch. Slow services
don't get excuses; they get a generous `stack_up_wait_timeout`.

Validating it surfaced a beautiful Ansible trap: a `when:` on a *looped*
`include_tasks` does not short-circuit the loop. The heartbeat ran its full
time budget every time, and a health flap on the final tick could
false-timeout. Each tick is now gated on `not _wait_done`, so the loop
genuinely stops at first all-ready.

## 55/55 — the plugin wiring contract

Notification routing had grown organically; some plugins carried the canonical
A9 severity shape, some carried ancestors of it. This tag unifies all 55
service plugins on one block (`on_critical`…`on_info` → `wing-inbox` | `ntfy`
| `mail`) and — more importantly — pins the whole manifest surface with a CI
gate (`test_plugin_wiring_contract.py`) plus a coverage report and a doc that
states which blocks have a *live consumer* versus *forward-ready metadata*.
Honest wiring beats aspirational wiring.

## Single-run autowiring

Two second-pass rituals died: `authentik_bootstrap_token` is now
playbook-generated and pinned as the blueprint token key (Wing /users and
invitations work on the first blank, no fetch-tool round trip), and the
Woodpecker↔Gitea OAuth2 client is auto-created during provisioning.

## What the STRICT blank exposed

A strict wait is a diagnostic instrument — it deadlocks exactly where your
ordering is wrong. The all-on blank validation closed a chain of these:

- **Core-up ordering** — the infra health-wait blocked on Authentik's Postgres
  role, which DB setup hadn't created yet. DB setup now runs before the wait.
- **Compose label resolution** — `compose -f <base> ps -q <svc>` returns "no
  such service" because base composes are `services: {}` (overrides carry the
  real definitions). Every admin/OIDC post-config task had been silently
  skipping on a blank. Containers are now resolved by compose label.
- **Bone telemetry 401s** — the `app.deployed` HMAC timestamp used
  `ansible_date_time.epoch`, frozen at gather_facts. An hour into a blank that
  is >300s stale: "timestamp out of window." Fixed with the current epoch.
- **Uptime Kuma under load** — Socket.IO event starvation turned monitor setup
  into a ~30-minute hang; now fail-fast with retries, never losing monitors.

## Security: SEC-16..18

A 5-agent audit against the SEC-1..15 baseline found no true CRITICALs but
produced three structural upgrades: a weak-password-prefix gate on public
tenants (the prefix seeds DB roots and OIDC secrets), the Pulse command
allowlist enforced in the runner that actually spawns processes (with secrets
stripped from child env and `DYLD_*`/`LD_*` overrides refused), and 83
`no_log: true` additions after discovering admin passwords were persisting
into Wing's SQLite via the telemetry callback — which now scrubs by value, not
just key name.

## Validation

STRICT all-on blank: `failed=0`, zero fatal, Kuma creating all 48 monitors
in-context, Bone `app.deployed` HTTP 200. Gate suite: pytest 1120 passed,
plugin-loader smoke 63/63, ansible-lint clean with `risky-shell-pipe` fixed
rather than skipped.
