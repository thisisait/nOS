# Active work — what to do right now

> **Pointer doctrine:** this file = NOW only, hard ceiling 150 lines (pinned by
> `tests/anatomy/test_active_work_slim.py`). History/narrative → devlog
> (`docs/devlog/README.md`, `/devlog` skill). Decisions → append-only O-log in
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md). Release narrative →
> [`RELEASE.md`](../RELEASE.md). Completed plans → [`docs/archive/`](archive/).
>
> Last updated: 2026-08-03 • v0.10-beta shipped; estate converged `failed=0`.
> One night of archives lost to an unpersisted key — see Operator to-dos.

## Now (current track)

**Now: three reds, in this order.**

1. **CI is RED on `dev`** (runs 32065150345, 32071719508 — 08-17). One job:
   Face vitest, one test, `forceLayout` determinism. macOS hashes
   `d5a6dc4a…`, Linux hashes `565b17ce…`. The test's own comment named CI as
   the arbiter for exactly this and said a disagreement is a determinism
   finding, not flake — so it is one: d3-force reproduces per-platform, not
   across platforms. Seed-pinning `randomSource` was not enough. Decide
   whether the pin should tolerate float drift (round the emitted
   coordinates) or whether cross-platform bit-identity is a claim we drop.
2. **The audit chain is broken.** `audit-chain-verify` rc=2 on 08-17 and
   08-18: `ok:false, checked 337462, unsigned 37`. All 37 unsigned rows were
   written by `agent:librarian` via `source=agentkit` on 2026-08-16
   11:49–11:50 — AgentKit's in-process write path is outside the signing
   discipline the rest of the spine obeys. Last passing verify 08-16 04:19.
   Re-anchoring a tamper-evident log is the operator's act, not an agent's.
3. **The nightly security scan has not run for two nights.** rc=1 =
   "Claude Code scan exited non-zero — NOT stamping components as scanned".
   The honest-marker fix works: 5 components sit at `scan_failed` and
   `last_full_scan` is still 2026-08-16 rather than a fabricated today.

**Shipped 2026-08-17** (narrative → devlog): public apex site at the root
domain, signed ruling, 1.9 MB → 596 kB (`afaa56ec`, `43076e48`); d3-force
second layout, face v0.8 (`07d9d826`); surveyor agent + first survey
(`6b960b47`, `f781f42d`); LangGraph harness + spike 4/4, NOT adopted
(`0d926671`, `b38a5057`). AgentKit's bound loop is **unproven** — 14 sessions,
0 completions, gated by `test_the_bound_agent_loop_is_unproven.py`.

## Open follow-ups

The general fix for the class below — a per-service `verify.yml` hook plus the
loader change that lets it fail — is in
[`nos-genome-and-organelles.md`](archive/nos-genome-and-organelles.md) §Thread D.

- **FreeScout has no SSO** (survey, 08-02): both `freescout-oauth` sources 404,
  so the `FREESCOUT_OIDC_*` env is inert and `/login` is local-form-only. Tasks
  now report it instead of claiming `changed`. Open: find a reachable module
  source, or reclassify FreeScout as forward_auth.
- **`drift-watch.sh` `exit 0`s regardless of the Bone POST**, swallowing a
  CRITICAL when the HMAC secret is unset. `genome-codegen.py` emits 2 of B1's 4.
- **Infisical MTI render fix (S-track):** the aggregator still emits an oauth2
  identity for infisical, so the orphan OAuth2Provider sharing the Provider
  base row with the ProxyProvider reappears on apply; deleting it cascades the
  shared base and kills the proxy (live-proven). Fix: suppress oauth2 render
  for `provider_type: forward_auth`, or make the main.yml MTI reconcile skip
  `o.delete()` when the base row has a proxy child. See memory
  `autologin-coverage-ceilings`.
- **Euro-office: full role swap after first stable** (summer 2026) — pilot via
  `onlyoffice_image` flip; rename role+plugin+manifest once stable lands.
  Documenso stays (no e-signing). Devlog `2026-06-13-euro-office-pilot`.
- **D1 `{{ vars }}` retirement flip** — design LOCKED (O25, generated-namespace
  plan + `tools/loader-vars-report.py`); the flip needs a dedicated pre-2.24
  wet-test lane. Hard-breaks on ansible-core 2.24.
- **Linux wet-test proves nothing yet — `hidden_fees/08` (HIGH).** Infra compose
  is not rendered on Linux → `up infra` rc=1 → the STRICT probe passes
  `0/0 ready (stack empty)`, green for weeks on an estate with no DB at all.
  Three pieces: render it (cause undiagnosed — do not guess), make the probe read
  the bring-up rc, give the smoke a manifest-enabled floor.
- **KEAP contract v2 — typed skill→service relations (undecided since 07-22).**
  They wait on us for the verb set (`provided-by`/`documents`/`depends-on`).
  Decide against what the generator can derive: a verb we cannot populate from
  the manifest is a verb that ships empty.
- **Removal vocabulary shim is now DUE.** `tasks/run-mode.yml` is marked
  "DEPRECATED — delete after v0.10" and v0.10 is tagged; removal tasks still
  carry `tags: ['blank','reset']`. A dated obligation that has come due.
- **R5 verify misses best-effort teardown.** `failed_when: false` tasks can
  survive a removal silently; the absence assert only stats the path set.
- **FS doctrine P3** — AgentKit tool-layer FS path-scoping; P1/P1b shipped and
  the plan header still says "DESIGN (P0) — we are here" (`docs/archive/fs-doctrine.md`).
- **Version-pin drift wave:** counts in Snapshot (re-derive, never inherit).
  Gitea closed via the agentic recipe path — the template for the rest.
  `validate_record` still lacks `security` in `_SEVERITY_VALUES` (schema has it).
- **PG 16→17 cutover** — pg17 verified live beside pg16; operator-gated.
- **Security backlog:** counts in Snapshot; Phase C + D remain.
- **Gov P0 (profile-gated):** ISDS + NIA/eIDAS federation (greenfield),
  retention enforcement (metadata only) — `docs/compliance/gov-readiness-audit-2026q2.md`.

## Operator to-dos

- **Hidden fees backlog** — [`docs/hidden_fees/`](hidden_fees/), 7 entries; 05 + 06
  closed. **Open:** 01 disabled-service overrides · 02 DB-blind healthchecks (closed
  for miniflux only, not the class) · 03 leading-digit slugs · 04 `docs/systems` drift ·
  **07 messages that outlive their mode** (4 instances paid, class unpaid; carries an
  UNDETERMINED mechanism, recorded deliberately without a guessed remedy). 07 now owns
  a wider rule too: *a step that cannot do its job must not exit 0* — three instances
  (drift hook parsing nothing · its POST 401ing · Linux wet-test `0/0 ready`).
- **Rotate `restic_password` (needs Full Disk Access)** — the last unfreed crown
  jewel, still at the OLD derived value. `restic key add` under the old password
  FIRST, then persist the new one.
- **TCC grant for /Volumes/SSD1TB** — restic off-site leg fails `operation not
  permitted`, blocking the backup DR round-trip verify.
- **Uptime Kuma: the wizard is no longer blocking, the monitors are unproven.**
  `/api/entry-page` now answers `entryPage:null`, not `setup-database` (measured
  2026-08-18), so the 07-24 claim is overtaken. What is NOT established is
  whether any monitor exists: the healthcheck is a TCP connect and reported
  `healthy` through nine days of an unfinished wizard, so it cannot answer this.
  Open `127.0.0.1:3001`, confirm monitors, then `--tags uptime_kuma`.
- **`s3://backups/2026-08-03/` (14 objects, 351 MB) opens with no key.** Decide
  whether to delete — unreadable ciphertext reads as a backup. 07-26..08-02 still
  open with `{prefix}_pw_backup_encryption` (`7f4907ac`).
- One-time (Phase C of devlog epic): repo Settings → Pages → Source = GitHub
  Actions.

## Deferred (one-liners)

- OpenClaw (Ollama/CUDA) + Hermes runtimes on Linux — `docs/linux-port.md`.
- Host-nginx per-service vhosts on Linux (Traefik is the Linux edge).
- Fleet provisioning (p2p/server-client/mesh) — `docs/archive/fleet-review-2026q2.md`.
- Inspektor + Librarian runners (contract-only; need trivy/grype resp. Qdrant).
- ansible-core 2.24 jump (~4h once upstream ships stable) — CLAUDE.md tech debt.
- Agent actor_id naming normalization across the two upgrade agents.
- Architect at-target recipe drafts (freescout/gitlab/grafana) — commit when next
  touching those services.

## Snapshot

| Surface | State |
|---|---|
| Release | `v0.10-beta` tagged and published (the "tag pending" line was stale) |
| Last verified | converge 2026-08-18 `failed=0`; 63 containers, 0 unhealthy |
| Suites | anatomy **3558 passed / 33 skipped**; face 302 passed locally — **but face vitest is RED on CI** (see Now #1) |
| Estate | `nos_data_root` = `/Volumes/SSD1TB/nOS/data` (one lever; NOT `configure_external_storage`) |
| CI | **RED on `dev`** — Face vitest, `forceLayout` determinism pin, macOS vs Linux |
| Authentik | engine=tofu; self-reconcile preflight = idempotent non-blank converge |
| Upgrades | PG17 coexistence queued |
| Remediation queue | cycle-31: 49 pending (6 HIGH) / 143 resolved / 5 vendor-blocked / 4 wontfix / 1 obsolete of 202. REM-152 is CLOSED — it was carried here as the headline HIGH after it stopped being one |
| Audit chain | **BROKEN** — 37 unsigned rows (agentkit, 08-16); nightly verify rc=2 |
| Security scan | 5 components `scan_failed`; `last_full_scan` 2026-08-16 |

## Update protocol

1. Refresh **Now** + **Snapshot** after every meaningful session.
2. Closed items: delete here; the narrative goes to a devlog entry
   (`/devlog new`), decisions to the O-log, release notes to RELEASE.md.
3. Keep ≤150 lines — the gate fails the suite otherwise.
4. Commit as `docs(roadmap): refresh active-work pointer`.
