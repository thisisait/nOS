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

**Blank/uninstall drift → manifest of managed resources (OPEN, 2026-07-19).** Operator
caught a blank-run drift: a 2026-04-20 screenshot + a duplicate `face-controls` KEAP
table survived `blank=true`. Root cause: `tasks/blank-reset.yml` `_blank_dirs` is a
hand-maintained allowlist that NEVER wipes `nos_data_root/tenants` (Bone class-3
user-files) and misses services (no `install_keap`), and is create-only not
reconciliation. Fix direction (KEAP agent's guidance): a manifest of managed resources
+ user-files managed + reconciling seeders + idempotence acceptance test; KEAP two-layer
(derived `/data` vs source `/user-files`; FS cleanup first, KEAP self-reconciles).
Plan: [`docs/plans/blank-uninstall-managed-resources.md`](plans/blank-uninstall-managed-resources.md).
**SHIPPED (2026-07-19):** uid stability (username-keyed trees, Czech-safe slug,
KEAP contract locked byte-for-byte) · blank wipes derived KEAP /data · **P1
`uninstall`** (`-e uninstall=true` dry-run → `+ confirm_uninstall=true` execute; removes
source + anatomy runtime dirs; live dry-run verified) · KEAP pin → v1.14.1 (list-all +
framing). **NEXT (operator, supervised WITH agent):** run `-e uninstall=true
-e confirm_uninstall=true` then a fresh `-e blank=true` install to validate end-to-end
(uid stability + clean tree). Remaining: P1.5 managed-resource manifest (disabled-legacy-dir
gap); KEAP uid-alignment lands ≥v1.15.0.

**nOS-face companion v0.8 — PAUSED, live-verified, UNCOMMITTED (2026-07-19).** F2 iframe
windows (`ServiceFrame` → hub services open as real windows; fixed the always-empty dock
= Wing `id`-vs-`slug` bug → 37 services) + F1a create-table UI (`CreateTableModal` for
KEAP DataTables) + a fixed `each_key_duplicate` crash on live KEAP rows. Gates green
(svelte-check 0/0, 113 vitest, lint). Handoff:
[`docs/plans/nos-face-companion-wip.md`](plans/nos-face-companion-wip.md).
**NEXT:** commit the 13 face files; KEAP-side list-all (≥v1.14.1) + `/explore` framing.

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
| Remediation queue | ~13 pending / 104 resolved / 4 vendor-blocked / 1 wontfix (pin wave dominant) |

## Update protocol

1. Refresh **Now** + **Snapshot** after every meaningful session.
2. Closed items: delete here; the narrative goes to a devlog entry
   (`/devlog new`), decisions to the O-log, release notes to RELEASE.md.
3. Keep ≤150 lines — the gate fails the suite otherwise.
4. Commit as `docs(roadmap): refresh active-work pointer`.
