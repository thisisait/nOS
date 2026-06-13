# Active work — what to do right now

> **Pointer doctrine:** this file = NOW only, hard ceiling 150 lines (pinned by
> `tests/anatomy/test_active_work_slim.py`). History/narrative → devlog
> (`docs/devlog/README.md`, `/devlog` skill). Decisions → append-only O-log in
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md). Release narrative →
> [`RELEASE.md`](../RELEASE.md). Completed plans → [`docs/archive/`](archive/).
>
> Last updated: 2026-06-12 • v0.6-beta released (re-cut same day after the
> grant_types trap #6); OpenTofu Authentik cutover (ADR-0001 Phase 1) live.

## Now (current track)

**Devlog platform + docs consolidation epic** (plan:
`~/.claude/plans/federated-hugging-snowflake.md`, approved 2026-06-12):
- A: docs/archive/ + this file slimmed (done in this pass) + doctrine rule
- B: `docs/devlog/` tree + bundle compiler + WP bot/app-password + sync engine
  + `/devlog` skill + Bone event types + `nos-devlog` agent identity + backfill
- C: `tools/devlog-release.sh` ceremony + GH Pages publishing of nos-core devlog

## Open follow-ups

- **Infisical MTI render fix (S-track):** the aggregator still emits an oauth2
  identity for infisical, so the orphan OAuth2Provider sharing the Provider
  base row with the ProxyProvider reappears on apply; deleting it cascades the
  shared base and kills the proxy (live-proven). Fix: suppress oauth2 render
  for `provider_type: forward_auth`, or make the main.yml MTI reconcile skip
  `o.delete()` when the base row has a proxy child. See memory
  `autologin-coverage-ceilings`.
- **Tofu adopt-path attachment import id** (existing-tenant migrations only) —
  `docs/opentofu-authentik-cutover.md` § Open items.
- **Euro-office: full role swap after first stable** (summer 2026) — pilot
  runs via `onlyoffice_image` flip (operator config.yml); rename
  `pazny.onlyoffice` → eurooffice + plugin + manifest row once stable lands.
  Documenso stays (euro-office has no e-signing). See devlog
  `2026-06-13-euro-office-pilot`.
- **D1 `{{ vars }}` retirement flip** — design LOCKED (O25, generated-namespace
  plan + `tools/loader-vars-report.py`); the flip needs a dedicated pre-2.24
  wet-test lane. Hard-breaks on ansible-core 2.24.
- **Advisor/architect actor-id naming inconsistency** (scout side-find,
  2026-06-11) — normalize agent actor_id naming across the two upgrade agents.
- **NC OIDC post-blank discovery race + broken IPv6 host-gateway
  (2026-06-13)** — right after a blank, `user_oidc`'s discovery job failed
  ~1/min with "Could not detect any host" until an NC restart cleared a
  transient resolver state. The `auth.<tld>:host-gateway` extra_hosts
  (nextcloud-base plugin) adds BOTH a working IPv4 (192.168.65.254) and a
  DEAD IPv6 (`fdc4:..::254`, "could not connect") gateway. Self-recovered, so
  not confirmed as the cause — but the dead IPv6 entry is a dual-stack
  landmine. If it recurs, disable IPv6 in the NC container (sysctl) or pin the
  extra_host to IPv4. Affects any server-side-OIDC service using the
  host-gateway alias (wordpress/gitea pick IPv4 and are unaffected).
- **Portainer SSO unverified read-only (2026-06-13 SSO audit)** —
  `/api/settings` needs an admin JWT, so the OAuth2 config couldn't be
  confirmed headlessly; the live converge also logs "FAILED to obtain admin
  JWT" on the OAuth setup. Confirm `AuthenticationMethod==3` with a Portainer
  admin token, and root-cause the JWT-obtain failure in
  `roles/pazny.portainer/tasks/post.yml`.
- **PG 16→17 cutover** — pg17 verified live beside pg16 on the coexistence
  track; the actual cutover (logical dump/restore + atomic switch) is still
  operator-gated.
- **Security backlog:** 14 pending / 71 resolved / 2 vendor-blocked
  (`docs/llm/security/remediation-queue.json`); Phase C hardening + Phase D
  architectural remain.
- **Gov P0 (profile-gated, not blocking non-gov):** ISDS + NIA/eIDAS federation
  (greenfield), retention enforcement (metadata only today) —
  `docs/compliance/gov-readiness-audit-2026q2.md`.

## Operator to-dos

- **TCC grant for /Volumes/SSD1TB** — restic off-site leg fails `operation not
  permitted`; blocks the backup DR round-trip verify (S4 leftover).
- Optional: fire the uptime-kuma 2.2.1 upgrade recipe (D3; breaking schema,
  recipe shipped, apply stays operator-gated).
- One-time (Phase C of devlog epic): repo Settings → Pages → Source = GitHub
  Actions.

## Deferred (one-liners)

- OpenClaw (Ollama/CUDA) + Hermes runtimes on Linux — `docs/linux-port.md`.
- Host-nginx per-service vhosts on Linux (Traefik is the Linux edge).
- Fleet provisioning (p2p/server-client/mesh) —
  `docs/archive/fleet-review-2026q2.md` teed up push-vs-pull.
- Inspektor + Librarian agent runners (contract-only; need trivy/grype substrate
  resp. Qdrant corpus pipeline) — `docs/sso-and-attribution.md` agent matrix.
- ansible-core 2.24 jump (~4h once upstream ships stable) — CLAUDE.md tech debt.

## Snapshot

| Surface | State |
|---|---|
| Release | `v0.6-beta` (2026-06-12, re-cut; tofu Authentik cutover) |
| Last verified | tofu-engine blank `failed=0`; smoke 48/48; authorize probe 18/18 |
| Suites | anatomy 1225 passed; ansible-lint production clean; syntax clean |
| CI | dev light lane green; `Integration (ubuntu-24.04)` = gating wet-test |
| Authentik | engine=tofu owns providers/apps/attachments; 6 blueprints imperative |
| Remediation queue | 14 pending / 71 resolved / 2 vendor-blocked |

## Update protocol

1. Refresh **Now** + **Snapshot** after every meaningful session.
2. Closed items: delete here; the narrative goes to a devlog entry
   (`/devlog new`), decisions to the O-log, release notes to RELEASE.md.
3. Keep ≤150 lines — the gate fails the suite otherwise.
4. Commit as `docs(roadmap): refresh active-work pointer`.
