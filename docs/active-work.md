# Active work — what to do right now

> **Pointer doctrine:** this file = NOW only, hard ceiling 150 lines (pinned by
> `tests/anatomy/test_active_work_slim.py`). History/narrative → devlog
> (`docs/devlog/README.md`, `/devlog` skill). Decisions → append-only O-log in
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md). Release narrative →
> [`RELEASE.md`](../RELEASE.md). Completed plans → [`docs/archive/`](archive/).
>
> Last updated: 2026-07-22 • v0.9-beta docs complete, pre-flight + ci-local green;
> tag pending operator gate.

## Now (current track)

**v0.9-beta release cut — READY, operator gate next (2026-07-22).** 228 commits since
`v0.8-beta`, TWO arcs. (1) 07-13→20: nOS face as a real WM + native apps over Bone's VFS ·
KEAP self-model + git-SoT ingest + semantic lens · `docs/doctrine/` constitution +
`nos_data_root` resolver · healthcheck coverage gate · **security 0 CRITICAL pending**.
(2) 07-20→22: **`nos` CLI + removal ladder** (`remove=none|data|deep|all` + `--leave`,
dry-run unless confirmed, single-source removal set, post-removal absence assert) ·
**KEAP self-model contract v1** (slug ids, golden fixture, symmetric cross-repo gates,
pins v1.19→v1.24) · `docs/hidden_fees/` ledger. RELEASE.md `## v0.9-beta` + devlogs
`2026-07-20-release-v0-9-beta` and `2026-07-22-nos-cli-and-removal-ladder`.
`tools/devlog-release.sh v0.9-beta` and `tools/ci-local.sh` both GREEN.
**NEXT (operator):** converge `--tags keap` (v1.24.0 pin needs an image rebuild) → push
`dev` → `dev→master` PR → `gh pr merge --rebase --admin` → tag → `gh release create`
(memory `nos-release-flow`).

**Blank/uninstall drift → managed-resource manifest (VALIDATED, P1.5 remains).**
`_blank_dirs` is a hand-maintained allowlist rather than a reconciliation. Plan:
[`docs/plans/blank-uninstall-managed-resources.md`](plans/blank-uninstall-managed-resources.md).
**Shipped:** uid stability · derived KEAP `/data` wipe · `uninstall` → the `remove=` ladder ·
R5 post-removal absence assert. **The supervised end-to-end validation run HAPPENED
2026-07-22** (`--remove=data`, then `--remove=all --leave`, then a clean all-on install:
1531 tasks, `failed=0`, 63 containers, 0 unhealthy) — and it found four defects design +
review had missed (`hidden_fees/06`, `07`). **Remaining: P1.5 managed-resource manifest**
(disabled-legacy-dir gap — a removal set still cannot answer "what did we ever create?").

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
- **Removal vocabulary: `blank`/`reset` TAG rename + shim deletion.** The vars moved
  to `remove=none|data|deep|all`, but every removal task still carries
  `tags: ['blank','reset']` / `['flush','reset']` (`main.yml`, `tasks/blank-reset.yml`)
  and `tasks/run-mode.yml`'s R4 fail message hard-codes those names — deliberately
  deferred so this release changed vocabulary in one layer only. The compat shim
  (`tasks/run-mode.yml`) is marked **DEPRECATED — delete after v0.10**: a dated
  obligation, tracked here so it does not become a permanent shim.
- **R5 verify does not cover best-effort teardown steps.** Tasks with
  `failed_when: false` (e.g. `/etc/resolver/dev.local`) can survive a removal
  silently; the absence assert only stats the path set. Documented in
  `docs/nos-cli.md`, unbuilt.
- **FS doctrine P3** — AgentKit tool-layer FS path-scoping (`docs/plans/fs-doctrine.md`).
  P1/P1b shipped this cycle (`nos_data_root` resolver + per-user tree); the plan header
  still says "DESIGN (P0) — we are here" and is stale.
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

- **Hidden fees backlog** — [`docs/hidden_fees/`](hidden_fees/), 7 entries.
  **Open:** 01 disabled-service overrides · 02 DB-blind healthchecks (closed for
  miniflux only, the class is not) · 03 leading-digit slugs · 04 `docs/systems`
  drift · **07 messages that outlive their mode** (4 instances paid, class unpaid;
  carries an UNDETERMINED mechanism — a TASK banner logged 5 min after the task
  provably started — recorded deliberately without a guessed remedy).
  **Closed:** 05 (2026-07-21, on its own written trigger) · 06 (2026-07-22, removal
  guard vs deploy gate + parity gate). Not urgent by construction — but 07 grew a
  third branch this cycle: anything that runs silent for minutes must say so first.
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
| Release | `v0.9-beta` docs complete on `dev`; pre-flight + `ci-local` GREEN; tag pending operator |
| Last verified | clean all-on install `ok=1531 failed=0`, 63 containers / 0 unhealthy (2026-07-22) |
| Suites | anatomy **1887 passed / 5 skipped**; `test_hub_render_smoke` fails live-host only (nos-face hub, paused epic) |
| Estate | `nos_data_root` = `/Volumes/SSD1TB/nOS/data` (one lever; NOT `configure_external_storage`) |
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
