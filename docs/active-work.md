# Active work — what to do right now

> **Pointer doctrine:** this file = NOW only, hard ceiling 150 lines (pinned by
> `tests/anatomy/test_active_work_slim.py`). History/narrative → devlog
> (`docs/devlog/README.md`, `/devlog` skill). Decisions → append-only O-log in
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md). Release narrative →
> [`RELEASE.md`](../RELEASE.md). Completed plans → [`docs/archive/`](archive/).
>
> Last updated: 2026-08-02 • v0.10-beta ready to cut: parity PINNED + AGREE,
> 0 pending CRITICAL (re-derived from live), estate converged `failed=0`.

## Now (current track)

**Cut v0.10-beta.** Gate met after the 08-02 converge (`ok=1431 failed=0`):
verdict **AGREE** on all six clauses (`agreeStreak: 6`), estate on
`keap v1.38.0`, **0 pending CRITICAL** derived from `docker ps`. `RELEASE.md` +
devlog `2026-08-02-release-v0-10-beta` carry the narrative.

**Remaining:** `dev → master` PR (`gh pr merge --rebase --admin`, memory
`nos-release-flow`) → tag `v0.10-beta` → re-sync `dev`.

**Known open at the tag** (all named in RELEASE.md): S-0's Nextcloud uid fix
applies to the *next login* only — the hashed account is live and unmigrated;
**32 of the 76 L1 columns reach the DB**, the other 44 belong to `apps`/`systems`
which no task seeds; FreeScout has no SSO; REM-151/152 HIGH open.

## Open follow-ups

Two adversarial sweeps (26 agents) + a pre-tag promise survey; sharpest findings
fixed. The **general fix** — a per-service `verify.yml` hook plus the loader
change that lets it fail — is in
[`nos-genome-and-organelles.md`](plans/nos-genome-and-organelles.md) §Thread D.


- **FreeScout has no SSO** (survey, 08-02): both `freescout-oauth` sources 404,
  so the `FREESCOUT_OIDC_*` env is inert and `/login` is local-form-only. Tasks
  now report it instead of claiming `changed`. Open: find a reachable module
  source, or reclassify FreeScout as forward_auth.
- **`drift-watch.sh` still `exit 0`s regardless of the Bone POST** and swallows
  a CRITICAL when the HMAC secret is unset — same shape as the 07-28 fix, one
  level up. **`genome-codegen.py` emits 2 of B1's 4 targets.**
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
- **Linux wet-test proves nothing yet — `hidden_fees/08` (HIGH, found in the
  v0.9-beta PR).** `stacks/infra/docker-compose.yml` is not rendered on Linux →
  `compose up infra` rc=1 → the STRICT probe passes `0/0 ready (stack empty)` →
  the run provisions for 8 more minutes on an estate with no MariaDB/PG/
  Authentik/Traefik. It had been GREEN this way for weeks; only the smoke
  noticed, and its 0.5 tolerance hid that until the probe count grew. Three
  pieces: render the infra compose on Linux (cause undiagnosed — do not guess),
  make the probe read the bring-up rc, give the smoke a manifest-enabled floor.
  CLAUDE.md's "it proves the playbook" claim is corrected until then.
- **KEAP contract v2 proposal — typed skill→service relations (2026-07-22, undecided).**
  KEAP asks why skills carry no typed edges to their services (today: tree +
  `[[anchor]]` rays only). Proposed shape: a `relations:` list in card frontmatter
  (`relations: [{type: provided-by, to: nos.iiab.rustfs}]`), emitted by our
  self-model generator, ingested as confirmed edges with pack provenance. **They
  are waiting on us for the verb set** (`provided-by` / `documents` / `depends-on`?)
  before either side builds; KEAP side needs an FM_VERSION bump. Decide the verbs
  against what the generator can derive from real state — a verb we cannot populate
  from the manifest is a verb that ships empty.
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
- **Version-pin drift wave (post-Gitea):** ~15 pending, **1 CRITICAL** (REM-137 gitea;
  REM-144 closed 07-30). The "0 CRITICAL" carried here for two weeks was stale —
  nobody re-derived it. Gitea (REM-099) closed via the agentic recipe path — the
  template for the rest (GitLab REM-016 → 18.11.7, etc.). Mechanical same-org bumps.
- **Migration severity-enum drift:** `validate_record` lacks `security` (schema has
  it); Gitea filed as `minor` to work around. Add it to `_SEVERITY_VALUES`.
- **PG 16→17 cutover** — pg17 verified live beside pg16 on the coexistence track,
  queued (`coexistence_planned`); the cutover itself is still operator-gated.
- **Security backlog:** counts live in Snapshot below (re-derive, never inherit);
  Phase C hardening + Phase D architectural remain.
- **Gov P0 (profile-gated, not blocking non-gov):** ISDS + NIA/eIDAS federation
  (greenfield), retention enforcement (metadata only today) —
  `docs/compliance/gov-readiness-audit-2026q2.md`.

## Operator to-dos

- **Hidden fees backlog** — [`docs/hidden_fees/`](hidden_fees/), 7 entries; 05 + 06
  closed. **Open:** 01 disabled-service overrides · 02 DB-blind healthchecks (closed
  for miniflux only, not the class) · 03 leading-digit slugs · 04 `docs/systems` drift ·
  **07 messages that outlive their mode** (4 instances paid, class unpaid; carries an
  UNDETERMINED mechanism, recorded deliberately without a guessed remedy). 07 now owns
  a wider rule too: *a step that cannot do its job must not exit 0* — three instances
  (drift hook parsing nothing · its POST 401ing · Linux wet-test `0/0 ready`).
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
- Agent actor_id naming normalization across the two upgrade agents.
- Architect at-target recipe drafts (freescout/gitlab/grafana, wing.db event 105)
  — commit when next touching those services.

## Snapshot

| Surface | State |
|---|---|
| Release | `v0.10-beta` gate MET (`agreeStreak: 6`, six clauses); tag pending operator |
| Last verified | converge 2026-08-02 `ok=1431 failed=0`; gitea `1.27.0` + metabase `v0.61.9` live |
| Suites | anatomy **2164 passed / 4 skipped**; face 143 passed, 0 type errors |
| Estate | `nos_data_root` = `/Volumes/SSD1TB/nOS/data` (one lever; NOT `configure_external_storage`) |
| CI | was RED on `dev` (lint / face / contracts-drift / pytest); all four fixed 08-02, re-run pending |
| Authentik | engine=tofu; self-reconcile preflight = idempotent non-blank converge |
| Upgrades | PG17 coexistence queued |
| Remediation queue | cycle-21: 15 pending / 128 resolved / 5 vendor-blocked / 3 wontfix / 1 obsolete of 152 |

## Update protocol

1. Refresh **Now** + **Snapshot** after every meaningful session.
2. Closed items: delete here; the narrative goes to a devlog entry
   (`/devlog new`), decisions to the O-log, release notes to RELEASE.md.
3. Keep ≤150 lines — the gate fails the suite otherwise.
4. Commit as `docs(roadmap): refresh active-work pointer`.
