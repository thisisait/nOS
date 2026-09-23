# Active work — what to do right now

> **Pointer doctrine:** this file = NOW only, hard ceiling 150 lines (pinned by
> `tests/anatomy/test_active_work_slim.py`). History/narrative → devlog
> (`docs/devlog/README.md`, `/devlog` skill). Decisions → append-only O-log in
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md). Release narrative →
> [`RELEASE.md`](../RELEASE.md). Completed plans → [`docs/archive/`](archive/).
>
> Last updated: 2026-09-23.

## Now (current track)

1. **The consulting-firm desk, then the v0.13-beta cut** (dtt `rel-013`).
   Invoice identity is closed in SOURCE (`invoice_slug`, absorb gate, ledger
   one-per-invoice, `tools/invoice-identity-scan.py`). **Operator, first and
   destructive:** the live money rows still carry pre-identity ids —
   `tools/digest-teardown.py --tables invoice,invoice-line,journal-entry,posting`
   (dry) then `--confirm`, BEFORE the next keap converge, or the re-seed forks
   them again. Then converge, re-run the vision intake, and the scanner must
   read clean. Ceremony order lives in the dtt row, not here.

2. **First always-on PoC: `git-origin-watcher`** (dtt, parent
   `loop-definition-model`) on DGX Spark / Qwen3 8B. Slice 1 is reader-only
   (npm+composer graph). Constraint A: model proposes, judges authorize.
   Do not re-research agent memory — rows `work-corpus-not-seed`,
   `cortex-rows`, `keap-row-vector-search`, `fs-project-tree`,
   `share-grants-agents`, `rsi-ops-loop`.

3. **SOURCE pins await the operator `nos`.** Ask `tools/estate-status.py`
   and `tools/rem-status.py`. Do **not** land the judged `MINIO_ROOT_PASSWORD`
   alias for REM-249 (mint+persist already shipped). RustFS rotation breaks
   S3 clients until they re-read `~/.nos/secrets.yml`.

4. **[`docs/doctrine/agentkit.md`](doctrine/agentkit.md) is DRAFTED as proposed**
   (`1e263377`). Operator still settles §6 before anything cites the file.

5. **Do not pick `loop-steps-match-run`.** Graph-follows-run vs
   runner-follows-graph is still queued design.

**Voice → caddy → AgentKit → cortex.** Five wires gated; fee
[43](hidden_fees/43-a-tool-with-no-door.md) paid. KEAP SOURCE pin is
`v2.0.0-rc.1` (`9a86ea09`) — not what is running; ask `tools/estate-status.py`.
**Next (operator):** converge (mint, KEAP re-seed, first real `exec`);
`caddy-entity-resolve` probe 2 — whether cortex `resolve` covers the taxonomy half.

## Open follow-ups

The general fix for the class below — a per-service `verify.yml` hook plus the
loader change that lets it fail — is in
[`nos-genome-and-organelles.md`](archive/nos-genome-and-organelles.md) §Thread D.

- **`genome-codegen.py` emits 2 of B1's 4.**
- **Euro-office: full role swap after first stable** — pilot via `onlyoffice_image`
  flip; rename role+plugin+manifest once stable lands. Documenso stays.
- **D1 `{{ vars }}` retirement flip** — design LOCKED (O25); the flip needs a
  dedicated pre-2.24 wet-test lane. Hard-breaks on ansible-core 2.24.
- **Linux smoke fail-ratio floor still open** — `hidden_fees/08`. Wait honesty
  shipped (`3713a926`): wait fails on FAILED/UNKNOWN; Bone-out-of-compose was
  already closed. Do not re-open a `0/0 ready` story.
- **KEAP contract v2 — typed skill→service relations (undecided since 07-22).**
  They wait on us for the verb set. Decide against what the generator can derive:
  a verb we cannot populate from the manifest is a verb that ships empty.
- **Removal vocabulary shim is DUE.** `tasks/run-mode.yml` is "DEPRECATED — delete
  after v0.10" and v0.10 is tagged; removal tasks still carry `tags:['blank','reset']`.
- **R5 verify misses best-effort teardown.** `failed_when: false` tasks can
  survive a removal silently; the absence assert only stats the path set.
- **FS doctrine P3** — AgentKit tool-layer FS path-scoping; P1/P1b shipped
  (`docs/doctrine/filesystem.md`).
- **Version-pin drift wave:** counts from `tools/rem-status.py`, never inherited.
  Gitea closed via the agentic recipe path — the template. `validate_record` still
  lacks `security` in `_SEVERITY_VALUES` (schema has it).
- **PG 16→17 cutover** — pg17 verified live beside pg16; operator-gated. Security
  backlog: `tools/rem-status.py`; Phase C + D remain.
- **Gov P0 (profile-gated):** ISDS + NIA/eIDAS federation (greenfield),
  retention enforcement (metadata only) — `docs/compliance/gov-readiness-audit-2026q2.md`.

## Operator to-dos

- **Hidden fees backlog** — [`docs/hidden_fees/`](hidden_fees/). `ls` is the count.
  **Still operator:** 01 disabled-service overrides · 02 DB-blind healthchecks
  (closed for miniflux only, not the class) · 03 leading-digit slugs ·
  04 `docs/systems` drift · **07 messages that outlive their mode** (class unpaid;
  a step that cannot do its job must not exit 0).
- **KEAP techNosIdeas row `openworker`: `planned` → `applied`.** Evidenced
  (`agent_questions` shipped `aa8a234c`, 31 answered rows live, gate green).
  `KEAP_AGENT_TOKEN_RO` is read-only by design, so no agent can apply it.
- **Rotate `restic_password` (needs Full Disk Access)** — the last unfreed crown
  jewel, still at the OLD derived value. `restic key add` under the old password
  FIRST, then persist the new one.
- **TCC grant for /Volumes/SSD1TB** — restic off-site leg fails `operation not
  permitted`, blocking the backup DR round-trip verify.
- **Uptime Kuma: wizard no longer blocking, monitors unproven.** `/api/entry-page`
  answers `entryPage:null` (08-18). Whether any monitor exists is NOT established —
  the healthcheck is a TCP connect. Open `127.0.0.1:3001`, confirm, then
  `--tags uptime_kuma`.
- **`s3://backups/2026-08-03/` opens with no key.** Decide whether to delete —
  unreadable ciphertext reads as a backup. 07-26..08-02 still open with
  `{prefix}_pw_backup_encryption` (`7f4907ac`).
- One-time (devlog epic Phase C): repo Settings → Pages → Source = GitHub Actions.

## Deferred (one-liners)

- OpenClaw (Ollama/CUDA) + Hermes runtimes on Linux — `docs/linux-port.md`.
- Host-nginx per-service vhosts on Linux (Traefik is the Linux edge).
- Fleet provisioning (p2p/server-client/mesh) — `docs/archive/fleet-review-2026q2.md`.
- Inspektor + Librarian runners (contract-only; need trivy/grype resp. Qdrant).
- ansible-core 2.24 jump (~4h once upstream ships stable) — CLAUDE.md tech debt.
- Agent actor_id naming normalization across the two upgrade agents.
- Architect at-target recipe drafts (freescout/gitlab/grafana).

## Snapshot — ask, don't inherit

A copied state table stood here and went stale in the reassuring direction.
A row is a copied value; the reader is the value. Roster: CLAUDE.md ("The repo
is not the running system"); `gh run list --branch dev --limit 5` for CI;
`tools/rem-status.py` for the queue.

Knowledge, not state: storage lever is `nos_data_root` (NOT
`configure_external_storage`); Authentik engine=tofu + reconcile preflight;
face `forceLayout` determinism is ISA-bound.

## Update protocol

1. Refresh **Now** after every meaningful session. Never write a copied
   state value here — link the reader that answers it.
2. Closed items: delete here; the narrative goes to a devlog entry
   (`/devlog new`), decisions to the O-log, release notes to RELEASE.md.
3. Keep ≤150 lines — the gate fails the suite otherwise.
4. Commit as `docs(roadmap): refresh active-work pointer`.
