# Active work — what to do right now

> **Pointer doctrine:** this file = NOW only, hard ceiling 150 lines (pinned by
> `tests/anatomy/test_active_work_slim.py`). History/narrative → devlog
> (`docs/devlog/README.md`, `/devlog` skill). Decisions → append-only O-log in
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md). Release narrative →
> [`RELEASE.md`](../RELEASE.md). Completed plans → [`docs/archive/`](archive/).
>
> Last updated: 2026-07-20 • v0.9-beta docs staged (RELEASE + devlog + roadmap);
> tag pending operator gate.

## Now (current track)

**v0.9-beta release cut — DOCS STAGED, operator gate next (2026-07-20).** 175 commits
since `v0.8-beta`: nOS face as a real WM + native apps over Bone's VFS · KEAP self-model
+ git-SoT ingest + semantic lens + linked data (v1.6.2→v1.17.2) · `uninstall` closes the
lifecycle · `docs/doctrine/` constitution + `nos_data_root` resolver · telemetry/mount/DNS
wedge-proofing · healthcheck coverage gate · **security 0 CRITICAL pending**. Written up in
RELEASE.md `## v0.9-beta` + devlog `2026-07-20-release-v0-9-beta` (bundle recompiled).
**Release-debt note:** NOW #0 in the roadmap (master 480 behind, beta tags dev-only) was
**stale** — `origin/master` is at 2026-07-13 with both beta tags reachable; only the local
`master` branch lagged. **NEXT (operator):** commit the staged docs + security rescan →
push `dev` (7 unpushed) → `tools/ci-local.sh` → `dev→master` PR (`gh pr merge --rebase
--admin`) → tag `v0.9-beta` → `gh release create` (`nos-release-flow`).

**Blank/uninstall drift → managed-resource manifest (PARTIALLY SHIPPED, 2026-07-19).**
Operator caught blank drift: a 2026-04-20 screenshot + a duplicate `face-controls` KEAP
table survived `blank=true`. Root cause: `tasks/blank-reset.yml` `_blank_dirs` is a
hand-maintained allowlist that never wipes `nos_data_root/tenants` (Bone class-3
user-files), misses services, and is create-only rather than reconciling. Plan:
[`docs/plans/blank-uninstall-managed-resources.md`](plans/blank-uninstall-managed-resources.md).
**Shipped:** uid stability (username-keyed, Czech-safe slug) · blank wipes derived KEAP
`/data` · P1 `uninstall` (dry-run default). **Remaining:** P1.5 managed-resource manifest
(disabled-legacy-dir gap) + the supervised end-to-end validation run
(`nos --remove=all --confirm --leave` → fresh `nos --remove=data --confirm`).

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
- **Version-pin drift wave (post-Gitea):** ~13 pending, 0 CRITICAL (REM-002
  Woodpecker resolved). Gitea (REM-099) closed first via the agentic recipe path — the
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
- **Security backlog:** ~13 pending / 104 resolved / 4 vendor-blocked / 1 wontfix
  (`docs/llm/security/remediation-queue.json`); dominated by the pin wave above.
  Phase C hardening + Phase D architectural remain.
- **Gov P0 (profile-gated, not blocking non-gov):** ISDS + NIA/eIDAS federation
  (greenfield), retention enforcement (metadata only today) —
  `docs/compliance/gov-readiness-audit-2026q2.md`.

## Operator to-dos

- **Hidden fees backlog** — [`docs/hidden_fees/`](hidden_fees/) now holds the
  deferred-cost items that fail silently rather than loudly (disabled-service
  overrides, DB-blind healthchecks, leading-digit slugs, `docs/systems` drift).
  Not urgent by construction; revisit when touching the surface each names.
- **miniflux — FIXED 2026-07-20, verified live** (14 tables, healthy). Its schema
  had vanished when Postgres was reinitialised under a container that was never
  restarted, and a DB-blind healthcheck certified it healthy for 19h while every
  request 500'd. The probe is DB-aware now; the *class* is
  [`hidden_fees/02`](hidden_fees/02-db-blind-healthchecks.md).
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
| Release | `v0.9-beta` docs staged on `dev` (`bab25cd3`); 10 unpushed; tag pending operator |
| Last verified | converge `ok=1321 failed=0`, 61 containers / 0 unhealthy; e2e 10/10 live |
| Suites | anatomy **1840 passed / 1 failed** — the 1 is `test_hub_url_audit` (live-host only, skips in CI): miniflux 500 |
| CI | green after clearing **6 pre-existing reds** on dev (the prior "all jobs green" snapshot was wrong): woodpecker gate matched a pre-`84649c17` URL · vaultwarden dead pin · tileserver/spacetimedb allowlist rot · archive link rot · `meta: end_play` `\| bool` filter trap |
| Authentik | engine=tofu; self-reconcile preflight = idempotent non-blank converge |
| Upgrades | Gitea 1.26.4 armed (agent-authored recipe+migration); PG17 coexistence queued |
| Remediation queue | ~13 pending / 104 resolved / 4 vendor-blocked / 1 wontfix (pin wave dominant) |

## Update protocol

1. Refresh **Now** + **Snapshot** after every meaningful session.
2. Closed items: delete here; the narrative goes to a devlog entry
   (`/devlog new`), decisions to the O-log, release notes to RELEASE.md.
3. Keep ≤150 lines — the gate fails the suite otherwise.
4. Commit as `docs(roadmap): refresh active-work pointer`.
