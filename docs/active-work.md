# Active work — what to do right now

> **Pointer doctrine:** this file = NOW only, hard ceiling 150 lines (pinned by
> `tests/anatomy/test_active_work_slim.py`). History/narrative → devlog
> (`docs/devlog/README.md`, `/devlog` skill). Decisions → append-only O-log in
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md). Release narrative →
> [`RELEASE.md`](../RELEASE.md). Completed plans → [`docs/archive/`](archive/).
>
> Last updated: 2026-06-15 • v0.7-beta tag prep (feat/v0.7-overnight validated
> end-to-end; tofu self-reconcile + Portainer SSO durable fixes — converge idempotent).

## Now (current track)

**v0.7-beta tag prep** (feat/v0.7-overnight, validated live; offline suite green):
- **tofu self-reconcile preflight** — `authentik_engine: tofu` is now idempotent
  across non-blank converges (was REFUSING every re-run; PK churn). PROVEN by the
  3-converge arc. `aa6986bd` + tool `tools/tofu-authentik-reconcile.sh`.
- **Portainer SSO** — verify via unauth `/api/settings/public` (password-independent),
  idempotent converge (no false DRIFT), opt-in admin self-heal. `0a49bb8c` `9c5b4e0e`.
- **Overnight review** — ~40 mechanical fixes + 48 plan docs + RAG arch (review-ready,
  NOT implemented). Remaining for the tag: RELEASE.md + devlog, then dev→master.

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
| Release | `v0.7-beta` prep — `feat/v0.7-overnight` validated, `dev→master` pending |
| Last verified | confirm converge `failed=0` (idempotent); blank `failed=0`; tofu no-REFUSE |
| Suites | anatomy 1474 passed; ci-local frozen gate OK; ansible-lint production clean |
| CI | dev light lane green; `Integration (ubuntu-24.04)` = gating wet-test |
| Authentik | engine=tofu; self-reconcile preflight = idempotent non-blank converge |
| Remediation queue | 14 pending / 71 resolved / 2 vendor-blocked |

## Update protocol

1. Refresh **Now** + **Snapshot** after every meaningful session.
2. Closed items: delete here; the narrative goes to a devlog entry
   (`/devlog new`), decisions to the O-log, release notes to RELEASE.md.
3. Keep ≤150 lines — the gate fails the suite otherwise.
4. Commit as `docs(roadmap): refresh active-work pointer`.
