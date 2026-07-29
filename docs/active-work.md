# Active work — what to do right now

> **Pointer doctrine:** this file = NOW only, hard ceiling 150 lines (pinned by
> `tests/anatomy/test_active_work_slim.py`). History/narrative → devlog
> (`docs/devlog/README.md`, `/devlog` skill). Decisions → append-only O-log in
> [`docs/roadmap-2026q2.md`](roadmap-2026q2.md). Release narrative →
> [`RELEASE.md`](../RELEASE.md). Completed plans → [`docs/archive/`](archive/).
>
> Last updated: 2026-07-29 • v0.10-beta release lane, night 3 of 3 pending;
> CI on `dev` green again, estate not yet converged.

## Now (current track)

**v0.10-beta release lane — A4 is the last gate (2026-07-29).** Order of operations:
[`cortex-s3-s4-workflow-set.md`](plans/cortex-s3-s4-workflow-set.md) · doctrine:
[`cortex-self-core.md`](plans/cortex-self-core.md). `agreeStreak: 2` (nights 07-28 + 07-29,
six clauses each); **A4 fires 07-30 05:30 UTC** and is the first night at a real
denominator — `tools/cortex-seed-fixtures.sh` seeded 26 markdown notes, so `realUserDocs`
went **2 → 28**, `knowledge_objects[fs:]` reads 317/317 exact, and the 07-29 `--no-ledger`
dry run already returned AGREE there. **CI on `dev` is green again** after two reds hiding
behind each other: `risky-shell-pipe` in `pazny.cortex` (sole red since 07-26), then a stale
E2E expecting `/agent/v1/objects` to 404 on the organ — it is ported deliberately and the
corpus diff reads both bases through it. **NEXT (operator):** verify A4 landed → converge
(gitea upgrade recipe FIRST, then a plain run — 7 image pins are ahead of the estate, incl.
REM-137 CRITICAL) → A5 docs review → KEAP tag (rowRef + the row-`slug` bug) + pin bump + one
night → `dev→master` → tag. Release wording is fixed in plan §5, denominator footnote and all.

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
- **Version-pin drift wave (post-Gitea):** ~13 pending, 0 CRITICAL (REM-002
  Woodpecker resolved). Gitea (REM-099) closed first via the agentic recipe path — the
  template for the rest (GitLab REM-016 → 18.11.7, etc.). Mechanical same-org bumps.
- **Migration severity-enum drift:** `validate_record` lacks `security` (schema
  has it); Gitea was filed as `minor` as a workaround. Add it to `_SEVERITY_VALUES`.
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
- Agent actor_id naming normalization across the two upgrade agents.
- Architect at-target recipe drafts (freescout/gitlab/grafana, wing.db event 105)
  — commit when next touching those services.

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
