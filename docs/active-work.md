# Active work — what to do right now

> **Pointer doctrine:** this file = NOW only, hard ceiling 150 lines (pinned by
> `tests/anatomy/test_active_work_slim.py`). History/narrative → devlog
> (`docs/devlog/README.md`, `/devlog` skill). Decisions → append-only O-log in
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md). Release narrative →
> [`RELEASE.md`](../RELEASE.md). Completed plans → [`docs/archive/`](archive/).
>
> Last updated: 2026-07-09 • v0.7-beta ready to tag (arc 1 idempotency +
> arc 2 security/converge-green/first-agent-recipe; CI green, e2e 10/10).

## Now (current track)

**v0.7-beta — ready to tag, pending operator validation converge.** Two arcs on
`dev` (`5bd11c8c`), CI green on all jobs:
- **Arc 1 (2026-06-15):** tofu self-reconcile preflight (idempotent non-blank
  converge) + Portainer SSO verify-via-public. Validated live (3-converge arc).
- **Arc 2 (2026-07-09):** security cluster closed (REM-118 FreeScout CVSS-9.4,
  REM-110 Bone scope-gate, REM-107 Alloy loopback); stacks converge-green (qgis/
  gitlab/puter; 61 containers, 0 unhealthy); **first agent-authored upgrade recipe**
  Gitea 1.25→1.26.4 (REM-099) via upgrade-architect + migration-author; CI red→green
  (module-shadow + contracts drift).
- **NEXT (operator):** run `ansible-playbook main.yml` (or blank) to live-apply +
  validate the Gitea 1.26.4 upgrade under STRICT health-wait → if `failed=0`,
  `dev→master` PR + tag `v0.7-beta` (admin bypass, see memory `nos-release-flow`).

## Open follow-ups

- **Infisical MTI render fix (S-track):** the aggregator still emits an oauth2
  identity for infisical, so the orphan OAuth2Provider sharing the Provider
  base row with the ProxyProvider reappears on apply; deleting it cascades the
  shared base and kills the proxy (live-proven). Fix: suppress oauth2 render
  for `provider_type: forward_auth`, or make the main.yml MTI reconcile skip
  `o.delete()` when the base row has a proxy child. See memory
  `autologin-coverage-ceilings`.
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
- **Tofu non-blank desync — CLOSED 2026-06-15** (durable). Provider PKs churn
  out from under the state every non-blank converge (providers are `managed=None`,
  no single churner) → the guard refused every re-run. Fix: a drift-conditional,
  identity-only **self-reconcile preflight** before `tofu plan`
  (`tools/tofu-authentik-reconcile.sh --preflight`, via the stable
  `application.slug → provider` bridge). PROVEN live (3-converge arc). The
  destroy-guard now also catches dangerous in-place UPDATEs (`d4647b49`).
- **Version-pin drift wave (post-Gitea):** ~28 pending, 1 CRITICAL (REM-002
  Woodpecker). Gitea (REM-099) closed first via the agentic recipe path — the
  template for the rest (GitLab REM-016 → 18.11.7, etc.). Mechanical same-org bumps.
- **Architect at-target refresh drafts (2026-07-09 sweep, uncommitted):** the
  upgrade-architect also drafted `freescout-2.1-current`, `gitlab-18-to-current`
  → 18.10.8, `grafana-12-current` → 12.4.4 (installed ahead of the recipe `to:`).
  Low priority — commit when touching those services. Report: event 105 in wing.db.
- **Migration engine severity-enum drift:** `nos_migrate_engine.validate_record`
  accepts only `patch|minor|breaking`, but `migration.schema.json` (+ recipes)
  allow `security` — the Gitea migration was recorded as `minor` as a workaround.
  Add `security` to `_SEVERITY_VALUES` so security migrations keep the signal.
- **PG 16→17 cutover** — pg17 verified live beside pg16 on the coexistence
  track; queued by upgrade-advisor this session (`coexistence_planned`); the actual
  cutover (logical dump/restore + atomic switch) is still operator-gated.
- **Security backlog:** ~36 pending / 79 resolved / 3 vendor-blocked
  (`docs/llm/security/remediation-queue.json`); dominated by the pin wave above.
  Phase C hardening + Phase D architectural remain.
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
| Release | `v0.7-beta` ready to tag on `dev` (`5bd11c8c`); pending operator validation converge |
| Last verified | converge `ok=1321 failed=0`, 61 containers / 0 unhealthy; e2e 10/10 live |
| Suites | anatomy 1753 passed; CI-exact 2301 passed / 0 errors; syntax + yamllint clean |
| CI | **all jobs green** on dev HEAD (pytest + contracts drift were red 3 commits, now fixed) |
| Authentik | engine=tofu; self-reconcile preflight = idempotent non-blank converge |
| Upgrades | Gitea 1.26.4 armed (agent-authored recipe+migration); PG17 coexistence queued |
| Remediation queue | ~36 pending / 79 resolved / 3 vendor-blocked (pin wave dominant) |

## Update protocol

1. Refresh **Now** + **Snapshot** after every meaningful session.
2. Closed items: delete here; the narrative goes to a devlog entry
   (`/devlog new`), decisions to the O-log, release notes to RELEASE.md.
3. Keep ≤150 lines — the gate fails the suite otherwise.
4. Commit as `docs(roadmap): refresh active-work pointer`.
