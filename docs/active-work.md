# Active work — what to do right now

> **Pointer doctrine:** this file = NOW only, hard ceiling 150 lines (pinned by
> `tests/anatomy/test_active_work_slim.py`). History/narrative → devlog
> (`docs/devlog/README.md`, `/devlog` skill). Decisions → append-only O-log in
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md). Release narrative →
> [`RELEASE.md`](../RELEASE.md). Completed plans → [`docs/archive/`](archive/).
>
> Last updated: 2026-08-23 • hedgedoc + mariadb rung 3 written; both await a converge.

## Now (current track)

**Transport converge LANDED 2026-08-23** (`failed=0`, 1557 tasks). Each claim
names its reader.

| what | before | after | read with |
| --- | ---: | ---: | --- |
| PostgreSQL clients encrypted | 38.5% | **every one, incl. hedgedoc** | `tls-uptake.py` self-test |
| MariaDB app clients encrypted | 0 of 5 | **5 of 5** | `tls-uptake.py` self-tests |
| FreeScout app version | 1.8.230 | **1.8.235** | `tools/app-version.py` |

`sec-transport-pg`, `-hedgedoc`, `-mariadb-clients`, `notify-supersede`: all four
probes **DONE**, each echoing `encrypted` / `wired` as its own evidence.

**Sampling was the wrong question, twice** (`docs/hidden_fees/29`). HedgeDoc
appeared in **0 of 319** samples over 100s — its pool lives a millisecond — and
MariaDB's `--window` read `partial-0.62` with every client provably encrypted,
because the healthcheck opens a unix socket every 10s and no counter separates
it from plaintext TCP. Both now ask the client about its OWN session.

**A sixth MariaDB client**, found in `information_schema.processlist`, not in
the ladder's survey of *applications*: `mysqld-exporter`, ~4×/min with the
credential in clear. Row `sec-transport-mysqld-exporter` — TLS only via
`--config.my-cnf`, whose file a non-root user must read, so a row not a patch.

**A converge died on my own change**: an index in `schema-extensions.sql` naming
columns the ALTER sweep adds later, and `CREATE TABLE IF NOT EXISTS` is a no-op
on an existing DB. Invisible to every local test, which builds fresh tables.
Gated; 9 latent siblings ratcheted.

**Next:** (1) `sec-transport-redis` — AUTH secret on the argv, no TLS listener.
(2) `sec-backrest-auth` — reachable from 23 containers. (3) the exporter.
(4) MariaDB rung 4 — waits on the exporter alone now.

**Reds (4), none new.** `loop:drive` predates the forge sync (REM-214 re-judges
tonight); the orphan clears on the next agent run; `notify-supersede` retires
nothing until its emitters fire — tonight's backup is the first test.

**48 commits ahead of GitHub** — promotion is the operator's act (`tools/forge-sync.py --apply --push-github`).

## Open follow-ups

The general fix for the class below — a per-service `verify.yml` hook plus the
loader change that lets it fail — is in
[`nos-genome-and-organelles.md`](archive/nos-genome-and-organelles.md) §Thread D.

- **FreeScout has no SSO** (08-02): both `freescout-oauth` sources 404, so the
  `FREESCOUT_OIDC_*` env is inert. Find a source, or reclassify as forward_auth.
- **`drift-watch.sh` `exit 0`s regardless of the Bone POST**, swallowing a
  CRITICAL when the HMAC secret is unset. `genome-codegen.py` emits 2 of B1's 4.
- **Infisical MTI render fix (S-track):** the aggregator still emits an oauth2
  identity, so the orphan OAuth2Provider sharing the Provider base row with the
  ProxyProvider reappears on apply; deleting it cascades the base and kills the
  proxy (live-proven). Fix: suppress oauth2 render for `forward_auth`.
- **Euro-office: full role swap after first stable** — pilot via `onlyoffice_image`
  flip; rename role+plugin+manifest once stable lands. Documenso stays.
- **D1 `{{ vars }}` retirement flip** — design LOCKED (O25); the flip needs a
  dedicated pre-2.24 wet-test lane. Hard-breaks on ansible-core 2.24.
- **Linux wet-test proves nothing yet — `hidden_fees/08` (HIGH).** Infra compose
  is not rendered on Linux → `up infra` rc=1 → the STRICT probe passes
  `0/0 ready (stack empty)`. Three pieces: render it (cause undiagnosed — do not
  guess), make the probe read the bring-up rc, give the smoke an enabled floor.
- **KEAP contract v2 — typed skill→service relations (undecided since 07-22).**
  They wait on us for the verb set. Decide against what the generator can derive:
  a verb we cannot populate from the manifest is a verb that ships empty.
- **Removal vocabulary shim is DUE.** `tasks/run-mode.yml` is "DEPRECATED — delete
  after v0.10" and v0.10 is tagged; removal tasks still carry `tags:['blank','reset']`.
- **R5 verify misses best-effort teardown.** `failed_when: false` tasks can
  survive a removal silently; the absence assert only stats the path set.
- **FS doctrine P3** — AgentKit tool-layer FS path-scoping; P1/P1b shipped and the
  plan header still says "DESIGN (P0) — we are here" (`docs/archive/fs-doctrine.md`).
- **Version-pin drift wave:** counts from `tools/rem-status.py`, never inherited.
  Gitea closed via the agentic recipe path — the template. `validate_record` still
  lacks `security` in `_SEVERITY_VALUES` (schema has it).
- **PG 16→17 cutover** — pg17 verified live beside pg16; operator-gated. Security
  backlog: `tools/rem-status.py`; Phase C + D remain.
- **Gov P0 (profile-gated):** ISDS + NIA/eIDAS federation (greenfield),
  retention enforcement (metadata only) — `docs/compliance/gov-readiness-audit-2026q2.md`.

## Operator to-dos

- **Hidden fees backlog** — [`docs/hidden_fees/`](hidden_fees/). `ls` is the count;
  carried forward stale twice ("7", then "16"). 05 + 06 closed.
  **Open:** 01 disabled-service overrides · 02 DB-blind healthchecks (closed
  for miniflux only, not the class) · 03 leading-digit slugs · 04 `docs/systems` drift ·
  **07 messages that outlive their mode** (4 instances paid, class unpaid; carries an
  UNDETERMINED mechanism, recorded deliberately without a guessed remedy). 07 now owns
  a wider rule too: *a step that cannot do its job must not exit 0* — three instances
  (drift hook parsing nothing · its POST 401ing · Linux wet-test `0/0 ready`).
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
  the healthcheck is a TCP connect and read `healthy` through nine days of an
  unfinished wizard. Open `127.0.0.1:3001`, confirm, then `--tags uptime_kuma`.
- **`s3://backups/2026-08-03/` (14 objects, 351 MB) opens with no key.** Decide
  whether to delete — unreadable ciphertext reads as a backup. 07-26..08-02 still
  open with `{prefix}_pw_backup_encryption` (`7f4907ac`).
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

A 12-row state table stood here; on 2026-08-23 a review found 7 rows stale,
including "CI green on `dev`" through four days of red (every push since
08-20: face `graphLayout` sha pin + 2 CI-only pytest fails) — wrong in the
REASSURING direction. A row is a copied value; the reader is the value. The
reader roster lives in CLAUDE.md ("The repo is not the running system");
add to it `gh run list --branch dev --limit 5` for CI and
`tools/rem-status.py` for the queue.

Knowledge, not state, survives: storage lever is `nos_data_root` (NOT
`configure_external_storage`); Authentik engine=tofu + reconcile preflight;
face `forceLayout` determinism is ISA-bound — its sha pin is red AGAIN, so
"closed by whole-px coordinates" was not the end of it.

## Update protocol

1. Refresh **Now** after every meaningful session. Never write a copied
   state value here — link the reader that answers it.
2. Closed items: delete here; the narrative goes to a devlog entry
   (`/devlog new`), decisions to the O-log, release notes to RELEASE.md.
3. Keep ≤150 lines — the gate fails the suite otherwise.
4. Commit as `docs(roadmap): refresh active-work pointer`.
