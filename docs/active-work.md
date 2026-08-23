# Active work — what to do right now

> **Pointer doctrine:** this file = NOW only, hard ceiling 150 lines (pinned by
> `tests/anatomy/test_active_work_slim.py`). History/narrative → devlog
> (`docs/devlog/README.md`, `/devlog` skill). Decisions → append-only O-log in
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md). Release narrative →
> [`RELEASE.md`](../RELEASE.md). Completed plans → [`docs/archive/`](archive/).
>
> Last updated: 2026-08-23 • transport track prepared on `dev`, awaiting a converge.

## Now (current track)

**Now: datastore transport. The estate has TLS everywhere and uses it almost
nowhere.** REM-217 measured it and `tools/tls-uptake.py` (new, 08-23) is the
reader that will say whether the fix worked — it exists BEFORE the fix so no
rung verifies itself.

Prepared on `dev`, **live effect unverified until a converge**:

1. **PostgreSQL clients.** The 2026-06-14 `require`-pin read
   `postgresql_ssl_enabled` out of scope — it was a `pazny.postgresql` role
   default and the five readers are other roles — so every client rendered
   `prefer` for nine weeks (`docs/hidden_fees/23`). Now at play scope, with the
   spelling each driver family needs: `require` for libpq, `no-verify` for
   node-postgres (`doctrine/foreign-properties.md` §5). Also `ssl_ciphers`
   without 3DES/MEDIUM.
2. **MariaDB rungs 1+2.** A self-signed cert with `mariadb` in the SAN now
   exists on disk — the prerequisite for every later rung, because Laravel's
   `MYSQL_ATTR_SSL_CA` is dropped by `array_filter` when empty.
   `require_secure_transport` is deliberately absent AND gated absent.

**What the converge should show**, read with `tools/tls-uptake.py`:
postgresql moves off **38.5%** toward 100% of fabric backends; mariadb reports
`ssl_cert` present (the ratio is cumulative and will not move fast); redis
unchanged, still RED. **A service that fails to start is the signal to revert
one template** — outline and infisical carry the only genuine risk, both
node-postgres.

**Still open:** redis AUTH secret on the argv, MariaDB clients (rung 3), the
TLS 1.3 floor — held back so a failed converge has one candidate cause.

**Both 08-18 reds are closed.** `audit-chain-verify` is `ok:true` rc=0 (the 37
historical unsigned rows remain recorded); the nightly scan authenticates
again and is at cycle 38. Today's reds are the inbox backlog (13 unread
CRITICAL/HIGH, oldest 28 d) and an orphaned surveyor session at 103 h. The
backup restore-drill row reads red and is not — the carve-out explains it.

## Open follow-ups

The general fix for the class below — a per-service `verify.yml` hook plus the
loader change that lets it fail — is in
[`nos-genome-and-organelles.md`](archive/nos-genome-and-organelles.md) §Thread D.

- **FreeScout has no SSO** (survey, 08-02): both `freescout-oauth` sources 404, so
  the `FREESCOUT_OIDC_*` env is inert and `/login` is local-form-only. Open: find a
  reachable module source, or reclassify FreeScout as forward_auth.
- **`drift-watch.sh` `exit 0`s regardless of the Bone POST**, swallowing a
  CRITICAL when the HMAC secret is unset. `genome-codegen.py` emits 2 of B1's 4.
- **Infisical MTI render fix (S-track):** the aggregator still emits an oauth2
  identity for infisical, so the orphan OAuth2Provider sharing the Provider base
  row with the ProxyProvider reappears on apply; deleting it cascades the shared
  base and kills the proxy (live-proven). Fix: suppress oauth2 render for
  `provider_type: forward_auth`. Memory `autologin-coverage-ceilings`.
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
- **Version-pin drift wave:** counts in Snapshot (re-derive, never inherit). Gitea
  closed via the agentic recipe path — the template. `validate_record` still lacks
  `security` in `_SEVERITY_VALUES` (schema has it).
- **PG 16→17 cutover** — pg17 verified live beside pg16; operator-gated. Security
  backlog: counts in Snapshot; Phase C + D remain.
- **Gov P0 (profile-gated):** ISDS + NIA/eIDAS federation (greenfield),
  retention enforcement (metadata only) — `docs/compliance/gov-readiness-audit-2026q2.md`.

## Operator to-dos

- **Hidden fees backlog** — [`docs/hidden_fees/`](hidden_fees/), **16 entries**
  (the "7" carried here for months counted the first seven filenames); 05 + 06
  closed. **Open:** 01 disabled-service overrides · 02 DB-blind healthchecks (closed
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
  answers `entryPage:null` (08-18), overtaking the 07-24 claim. Whether any monitor
  exists is NOT established — the healthcheck is a TCP connect and read `healthy`
  through nine days of an unfinished wizard. Open `127.0.0.1:3001`, confirm, then
  `--tags uptime_kuma`.
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

## Snapshot

| Surface | State |
|---|---|
| Release | `v0.10-beta` tagged and published (the "tag pending" line was stale) |
| Last verified | converge 2026-08-18 `failed=0`; 63 containers, 0 unhealthy |
| Suites | anatomy **3579 passed / 33 skipped**; face vitest 302; cortex vitest 248 |
| Estate | `nos_data_root` = `/Volumes/SSD1TB/nOS/data` (one lever; NOT `configure_external_storage`) |
| CI | green on `dev` @ `efdd3b5a`. The 08-17 red was real, not flake: `forceLayout` determinism is **ISA-bound, not OS-bound** — closed by emitting whole-px coordinates |
| Authentik | engine=tofu; self-reconcile preflight = idempotent non-blank converge |
| Upgrades | PG17 coexistence queued |
| Remediation queue | cycle-31: 49 pending (6 HIGH) / 143 resolved / 5 vendor-blocked / 4 wontfix / 1 obsolete of 202. REM-152 is CLOSED — it was carried here as the headline HIGH after it stopped being one |
| Audit chain | **BROKEN** — 37 unsigned rows (agentkit, 08-16); nightly verify rc=2. Writer fixed; re-anchor is the operator's |
| Security scan | dead on expired Claude-CLI OAuth (1.7 s, rc=1). 5 components `scan_failed`; `last_full_scan` 2026-08-16 |
| Wing inbox | 138 unread, 68 CRITICAL/HIGH, oldest 24 d — nothing reads it |
| Backups | keap-db present and restorable (347 MB, 08-18). The 08-16 drill failure was transient; a later drill passed |

## Update protocol

1. Refresh **Now** + **Snapshot** after every meaningful session.
2. Closed items: delete here; the narrative goes to a devlog entry
   (`/devlog new`), decisions to the O-log, release notes to RELEASE.md.
3. Keep ≤150 lines — the gate fails the suite otherwise.
4. Commit as `docs(roadmap): refresh active-work pointer`.
