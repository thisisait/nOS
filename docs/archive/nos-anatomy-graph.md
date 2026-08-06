# nOS anatomy graph — the edges the estate already has, declared

**Status: design + measurement, 2026-08-06. Nothing here is applied.**

> **Placement, resolved 2026-08-06.** Written to `docs/plans/`, which was retired
> 2026-08-02 (`docs/plans/README.md`: "Do not add a plan here") — the commissioning
> brief named that path and predates the retirement. Moved here on the same day,
> per that README's own split: the long form lives in `docs/archive/`, the living
> surface is `docs/idea/`. The pointer is `docs/idea/06-genome.md` §Next, since
> this works out the "Ordering" and "A job is an organelle" items of the genome
> plan's Thread D (`docs/archive/nos-genome-and-organelles.md:1042-1049`).
>
> **Two of its findings are already closed** (commits `97abdb7c`, `ba7a9471`):
> the cortex halt that three documents described and no code performed, and the
> claude-CLI mutex that only one of two spawners took.

Every claim below carries a source: `file:line`, a command, or a query against
`~/wing/app/data/wing.db`. Claims that could not be verified are marked
**unverified**. Measurement day: 2026-08-06, on the live estate.

---

## 0. Corrections to the brief — what the substrate actually is

The brief's own description of "what exists today" was checked first, per the
one rule. Two claims needed correction:

1. **`pulse_jobs` in the live wing.db does NOT have `category` or
   `findings_exit_codes` columns.**
   `sqlite3 ~/wing/app/data/wing.db ".schema pulse_jobs"` (2026-08-06) shows
   neither. The truth is three-layered:
   - *Declared in git:* every job manifest carries `category:`
     (e.g. `files/anatomy/plugins/keap-base/plugin.yml:113,142,162,185`;
     `files/anatomy/plugins/cortex-base/plugin.yml:131,154`), two carry
     `findings_exit_codes` (`plugins/gitleaks/plugin.yml:65`,
     `plugins/discovery/plugin.yml:97`), pinned by
     `tests/anatomy/test_every_job_declares_what_it_is.py:80-99` against the
     closed six-category set (line 42).
   - *Harvest path exists:* `roles/pazny.wing/tasks/post.yml:495-496` POSTs
     both fields to `/api/v1/pulse_jobs`, and the repo Wing schema has the
     column (`files/anatomy/wing/db/schema-extensions.sql:328`).
   - *Live Wing predates it:* the live `pulse_jobs` rows were re-upserted
     2026-08-06T08:26 (`SELECT updated_at FROM pulse_jobs`) and the columns
     still do not exist — the deployed Wing dropped the fields. The face
     already anticipates this: `PulseJobView.category` is nullable, "absent on
     Wing < 2026-08-06" (`files/anatomy/face/src/lib/anatomy/pulse.ts`).
   So: **the unified declaration layer is git-only until the next Wing
   converge.** Any graph model must treat the manifests, not wing.db, as the
   node source of truth — which is also what the genome doctrine requires.
2. **Observed fire lateness is +0.2 to +10.1 minutes, not 0.9–7.4.** Measured
   over 2026-07-28→08-06 (query in §1.4): dominated by each job's own declared
   `jitter_min` (2–10 min on the nightly chain) plus the 30 s tick
   (`files/anatomy/pulse/pulse/config.py:37`). The brief's range was close but
   not this window's.

Verified as stated: 29 unpaused+paused jobs (9 paused, all agent-runner);
`PULSE_MAX_CONCURRENT` default 4 (`config.py:40`); 17k+ runs (18 415 on
2026-08-06); `duration_ms` NULL before ~2026-08-05; 5 judges + 4 gate sets
(`state/judge-sets.yml:29-224`); loop ledger tables present with 9 proposals /
13 judge runs / 19 verdicts; 11 `eu.thisisait.nos.*` launchd plists
(`ls ~/Library/LaunchAgents/`); 63 `id:` entries in `state/manifest.yml`.

---

## 1. Deliverable 1 — the edges that already exist implicitly

**Counting convention.** An edge is a writer→reader pair over a *named*
artifact (file, table, endpoint), between automated actors. Where a reader
consumes a whole table fed by many writers (notifications, events), the
fan-in is listed per writer for `data` but the WORM-table read is one
aggregate edge. Structural dispatch (daemon→its jobs, launchd→its daemons)
is counted per target under `trigger`.

**Totals: data 28 · trigger 38 live + 1 dead · mutex 2 resource claims
(→ 46 derived exclusion pairs) + 2 self-locks · temporal 7.**

### 1.1 Data edges (28)

The nightly knowledge chain (writers and readers all verified in script
source; ports: KEAP `127.0.0.1:8091`, cortex `:8098`, Ollama `:11434`, Bone
`:8099`, Wing `:9000`):

| # | writer → reader | artifact | evidence |
|---|---|---|---|
| 1 | keap-consolidate → keap-embed-sync | new datapoints via `POST /ingest/v1/capture` → `GET /agent/v1/embeddings/pending` | `keap-consolidate.py:208-216`; `keap-embed-sync.py:113,127` |
| 2 | keap-consolidate → cortex-corpus-diff | feeder ledger `~/.nos/keap-consolidate-state.json` (referee 3) | writer `:303-307`; reader `cortex-corpus-diff.py:1582-1583,638-652` |
| 3 | cortex-fs-sync → keap-embed-sync | cortex mirror rows needing vectors (`POST /agent/v1/fs/sync` → pending diff) | `cortex-fs-sync.py:70-73`; `keap-embed-sync.py:97-100,127` |
| 4 | cortex-fs-sync → cortex-corpus-diff | organ corpus read over `/agent/v1/*` | reader `:344-445` |
| 5 | keap-embed-sync → keap-features-sync | embeddings → `GET /agent/v1/features/vectors` | writer `:166`; reader `keap-features-sync.py:67` |
| 6 | keap-embed-sync → keap-lint | fresh vectors for the container lint pass | `keap-lint.py:55`; ordering claim `keap-base/plugin.yml:181-183` |
| 7 | keap-embed-sync → cortex-corpus-diff | settled embeddings, `GET /agent/v1/embeddings/pending?limit=500` | reader `:433` — and this read **prunes** (`:74-81`), the harness's one non-pure read |
| 8 | cortex-corpus-diff → weakness:corpus-diff | ledger `~/.nos/cortex-corpus-diff.json` | writer `:1552-1554`; reader `bone/weaknesses.py:1125-1151` |
| 9 | vulnerability-scan → security-drift-watch | `docs/llm/security/scan-state.json`, via the hook's stdout JSON | writer `scan-runner.sh:188-243`; `drift-watch.sh:42` reads `hooks/playbook-end.d/20-cve-drift-check.sh`, which reads the file at `:36` |
| 10 | vulnerability-scan → scan-state-record | scan-state.json + remediation-queue.json → git ref `refs/heads/scan-data` | `tools/scan-state-snapshot.py:82-85,268` |
| 11 | vulnerability-scan → weakness:scan-state | scan-state.json, corroborated against `~/.nos/events/scan.jsonl` | `weaknesses.py:800-812,627-634` |
| 12 | vulnerability-scan (its claude) → weakness:remediation-queue | remediation-queue.json | written per prompt `scan-runner.sh:133-137`; read `weaknesses.py:670-675` |
| 13 | vulnerability-scan → discovery:contradiction-scan | scan-state + remediation-queue vs `git show HEAD:` + `docker ps` | `tools/discovery-scan.py:65-68,348-357,124-127` |
| 14 | vulnerability-scan → weakness:scan-state (corroborator) | `~/.nos/events/scan.jsonl` via `lib-jsonl.sh:69-70` | reader `weaknesses.py:634` — the independent check on the self-report |
| 15 | 20-cve-drift-check → service:prometheus | `~/.nos/metrics/textfile/nos_security_drift.prom` via Alloy textfile collector | writer `:160-175` |
| 16 | service:prometheus → alert-relay | `GET /api/v1/alerts` + seen-ledger `~/.nos/prom-alerts-seen.json` | `prometheus-alert-relay.py:74,103-105,126-137` |
| 17 | service:prometheus → weakness:prometheus-alerts | same endpoint | `weaknesses.py:1244-1250` |
| 18 | daemon:pulse → weakness:pulse-runs | `wing.db pulse_runs`, opened read-only | `weaknesses.py:1318-1336` |
| 19 | weakness sources → loop engine | `loop_proposals.weakness_id` + `weakness_evidence_sha` | live schema `.schema loop_proposals` |
| 20 | judges → loop ledger | `loop_judge_runs` (outcome/work_count/min_work) → `loop_verdicts` per `gate_set` | live schema; 13 runs / 19 verdicts on 2026-08-06 |
| 21–27 | {keap-consolidate, keap-lint, cortex-fs-sync, cortex-corpus-diff} via `nos-notify.sh`; {drift-watch, alert-relay, gitleaks, tofu-drift} via direct HMAC POST → wing:dispatch-notifications | Bone `POST /api/v1/notifications` → `wing.db notifications` → `dispatch-notifications.php fetch_pending()` | landing chain `nos-notify.sh:53` → `bone/main.py:782-838` → `bone/clients/wing.py:511`; reader `dispatch-notifications.php:108-131`. 8 active writers = 8 edges (paused agent jobs add more when unpaused, via `pulse-run-agent.sh:181-187`) |
| 28 | everything → wing:audit-chain-verify | `wing.db events` WORM chain (aggregate fan-in) | reader `verify-audit-chain.php:72`, writes verdict to `audit_chain_meta` only under `--write-verdict` (`:140-161`) |

Also real but reader-less: `scan-runner.sh` writes `docs/llm/security/scan.log`
(`:21,:35`) — no reader found. `run-gitleaks.sh` ingests findings to Wing
(`POST /api/v1/gitleaks_findings`, `:165-170`) whose reader is the Wing UI,
not an automated actor.

### 1.2 Trigger edges (38 live, 1 dead)

| trigger | targets | evidence |
|---|---|---|
| daemon:pulse dispatches | 20 unpaused jobs | `daemon.py:103-164`; catalog query 2026-08-06 |
| launchd starts | 11 `eu.thisisait.nos.*` daemons | `ls ~/Library/LaunchAgents/` |
| pulse-run-agent.sh → claude CLI | 1 active job (conductor:self-test-001; +9 paused) | `pulse-run-agent.sh:284-305` (`--permission-mode bypassPermissions` — relayed as a finding: the agent chokepoint runs claude with permissions bypassed) |
| scan-runner.sh → claude CLI | vulnerability-scan | `scan-runner.sh:164-166` (`--dangerously-skip-permissions` — same finding, second site) |
| drift-watch.sh → 20-cve-drift-check.sh | script→script | `drift-watch.sh:27,42` |
| keap-lint → KEAP container lint pass | `POST /agent/v1/lint/run` reconciles state + fans A9 | `keap-lint.py:55`; why judge-sets refuses it as a judge: `judge-sets.yml:206-210` |
| cortex-fs-sync → organ FS pass | `POST /agent/v1/fs/sync` (the walk happens service-side) | `cortex-fs-sync.py:70-73` |
| dispatch-notifications → ntfy, SMTP | `:2586` / `:1025` | `dispatch-notifications.php:47-49` |
| **cortex-corpus-diff → halt cortex-fs-sync** | **DEAD.** `--halt-cmd` exists (`cortex-corpus-diff.py:1573,1657-1658`) but the production job sets neither `CORTEX_DIFF_HALT_CMD` nor the flag (`cortex-base/plugin.yml:153-168`); `CORTEX_DIFF_HALT_CMD` appears exactly once repo-wide (its own default). `cortex-fs-sync.py` reads **no file at all** (env + HTTP response only, `:54-57,:76`), so no flag-file path exists either. Three claims assert the halt works: `cortex-base/plugin.yml:129` ("the job §5.3's --halt-cmd disables"), the halt notification text ("The cortex organ's fs-sync is stopped", `cortex-corpus-diff.py:1659-1661`), and `weaknesses.py:1143-1151` (a `critical` weakness titled "fs-sync was stopped"). All three describe wiring that does not exist. | — |

### 1.3 Mutex — resource claims, not edges

| resource | claimants | evidence + leak |
|---|---|---|
| `~/.nos/agent-run.lock` (mkdir mutex) | ALL `pulse-run-agent.sh` jobs — one lock dir, no agent name in the path, estate-wide (10 jobs; 45 derived exclusion pairs) | `pulse-run-agent.sh:97-117`; stale-holder reclaim via `kill -0` at `:106-113`. **Leak:** `scan-runner.sh:164` runs claude WITHOUT this lock (own `/tmp/nos-vulnscan.lock` only, `:22`) — so "one claude at a time" (`:85-89`) does not hold against the 02:00 scan. `pulse-run-agent.sh:85-89` claims the "single chokepoint every agent goes through"; the scan does not go through it |
| `nos_entity` | judge:genome-codegen + judge:pytest-anatomy (1 pair) | `state/judge-sets.yml:87,124` — both mutate `files/anatomy/module_utils/nos_entity.py` |
| self-locks (not pairwise) | scan-runner PID lock `/tmp/nos-vulnscan.lock`; daemon per-job re-entrancy guard | `scan-runner.sh:22,45-53`; `daemon.py:117-129` (the guard that ended the measured 2026-07-28 double-dispatch storm) |

Judge `requires:` (`live_estate`, `keap_token_ro`, `cortex_token_ro` —
`judge-sets.yml:170,199`) are capability requirements, not mutex — modelled as
`data` edges to `resource:*` nodes in the graph, satisfied or not, never
exclusive.

### 1.4 Temporal edges — the nightly chain, measured

The six-job chain is real, and the only thing encoding it is cron minutes plus
per-job jitter. The comments claim the ordering outright:

- `plugins/cortex-base/plugin.yml:127-129` — *"04:30 UTC — after the
  consolidator (04:15), before keap-embed-sync (04:45), so the night's new
  mirror rows have vectors by the time the diff reads both corpora at 05:30."*
- `plugins/cortex-base/plugin.yml:151-152` — *"05:30 UTC — after
  keap-embed-sync (04:45) has run BOTH passes, so the diff sees two corpora in
  their settled state rather than mid-embed."*
- `plugins/keap-base/plugin.yml:145` — *"05:00 UTC — between embed-sync
  (04:45) and lint (05:15)"*; `keap-base/plugin.yml:188` — *"05:15 UTC — after
  keap-embed-sync (04:45+jitter)"*; `keap-base/plugin.yml:159-160` — *"Night
  order: consolidate 04:15 -> embed-sync 04:45 -> lint 05:15 -> librarian."*

Nothing enforces any of it. The daemon has no dependency concept — its whole
dispatch decision is `list_due_jobs()` + a per-job re-entrancy guard + a
4-slot cap (`files/anatomy/pulse/pulse/daemon.py:95-164`).

**Measured margins** (wing.db, 10 nights 2026-07-28→08-06, night runs only;
margin = downstream `fired_at` − upstream `finished_at`):

```sql
SELECT ... round(min((julianday(b.fired_at)-julianday(a.finished_at))*1440),1) ...
```

| temporal edge | cron gap | observed margin min/avg | worst-case *declared* margin¹ | what breaks when it inverts |
|---|---|---|---|---|
| keap-consolidate → cortex-fs-sync | 15 min | **12.1** / 13.1 min | 15 − 5(jitter) − 10(max_runtime) = **0, minus lateness → can invert** | fs-sync mirrors the filesystem before the night's new items are registered; corpus-diff sees `only_in_keap` noise and the 3-night agree clock stalls (`cortex-base/plugin.yml:121-125`) |
| cortex-fs-sync → keap-embed-sync | 15 min | **15.1** / 19.2 min | 15 − 2 − 15 = **−2 min → can invert** | embed-sync runs before the mirror settles; new mirror rows carry no vectors that night |
| keap-embed-sync → keap-features-sync | 15 min | **6.3** / 12.3 min | 15 − 10 − 15 = **−10 min → can invert badly** | features projected from stale embeddings; GraphCanvas colour/size channels lag a day |
| keap-features-sync → keap-lint | 15 min | **12.0** / 14.8 min | 15 − 5 − 10 = **0** | lint runs on pre-features state; findings fan into A9 against vectors it claims are fresh (`keap-base/plugin.yml:181-183`) |
| keap-lint → cortex-corpus-diff | 15 min | **11.3** / 14.5 min | 15 − 5 − 5 = **+5 min** (the only positive one) | diff reads mid-lint state; a DISAGREE night against a settling corpus |

¹ gap − upstream `jitter_min` − upstream `max_runtime_s`, all from the
manifests (`keap-base/plugin.yml:118-120,145-147,165-167,188-190`,
`cortex-base/plugin.yml:134-136,157-159`). Every edge but the last is already
*permitted* to invert by its own declared budgets; only observed runtimes far
below `max_runtime_s` (0.9 s avg for consolidate vs a 600 s budget; 5.8 s avg
for embed-sync vs 900 s) keep the chain ordered.

**And it has already scrambled once in the window.** On 2026-07-27,
`cortex-fs-sync` and `cortex-corpus-diff` missed their night slots entirely
and ran at 11:14 and 11:34; `keap-consolidate`/`embed-sync`/`features-sync`
ran twice that day (04:17 night pass + an 11:10–11:24 repeat). The daemon log
shows normal ticking through that morning (`~/pulse/log/pulse.log`,
2026-07-27 11:00–11:02), so the cause is Wing-side `next_fire_at`
recomputation — **unverified** which event triggered it. The measurable fact:
that day's corpus-diff (11:34) diffed a mirror synced at 11:14 against keap
state consolidated at 04:17 *and again* at 11:10 — the ordering the comments
promise did not hold, and nothing noticed.

**Two more temporal edges outside the chain** (total 7):

| temporal edge | gap | margin arithmetic | evidence |
|---|---|---|---|
| vulnerability-scan (02:00) → scan-state-record (03:30) | 90 min | comment claims "after the 02:00 scan's 1800s ceiling has expired" (`conductor.yml:148-150`); measured scan durations 420 s avg / 945 s max (wing.db, 21 runs) → ~74 min observed margin, 60 min against the ceiling | temporal only — the snapshot deliberately reads "a settled file", nothing enforces settledness |
| vulnerability-scan (02:00) → security-drift-watch (06:00) | 4 h | scan max 945 s → margin ~3.7 h; generous, but a scan that hits its 1800 s ceiling *and* a Wing-side refire (as on 2026-07-27) could still hand drift-watch a mid-write file | data edge #9 rides on this spacing |

Not counted: the anti-collision offsets the manifests mention ("offset from
gitleaks 03:00 + tofu-drift 05:30", `keap-base/plugin.yml:118`) are slot-
hygiene against the 4-slot cap, not dependencies. Noted, not edges.

**Fire lateness** (fired_at − cron minute, same window): consolidate
+1.7…+4.5 min (jitter 5), fs-sync +0.2…+1.6 (jitter 2), embed-sync +1.6…+10.1
(jitter 10), features +0.6…+5.2 (jitter 5), lint +1.0…+4.9 (jitter 5),
corpus-diff +0.2…+4.2 (jitter 5). Lateness ≈ declared jitter, i.e. the chain's
margins are being spent *by design*, nightly.

---

## 2. Deliverable 2 — one anatomy, built on the genome

Ratified direction this builds on (`docs/archive/nos-genome-and-organelles.md`,
distilled in `docs/idea/06-genome.md`):

- *"Facts about an entity → data, declared once, inherited, generated
  everywhere. What may **act** on an entity → code, per runtime,
  hash-compared, never inherited from a manifest"* (`06-genome.md:54-58`).
- An organ declares `consumes` — *"other organs' contracts, at a declared
  version"* — with `requires.plugin` named as the existing precedent
  (`nos-genome-and-organelles.md:576`).
- Thread D item 4 demands exactly this deliverable: *"the nightly feeder chain
  … is load-bearing and encoded only as cron minutes. Make the dependency
  explicit or prove the spacing"* (`:1042-1044`); item 6: *"A job is an
  organelle … the pulse catalog is a natural second consumer of the genome"*
  (`:1047-1049`).
- The delivery vehicle is the estate's existing **regenerate-and-diff**
  pattern, already running in four places (`tools/genome-codegen.py:19-21`).

Nothing below contradicts the ratified direction. One deliberate divergence
from the *brief*: the brief calls a mutex "an edge of a different kind" —
§2(a) argues mutex must be a **resource claim on the node**, not an edge,
because `state/judge-sets.yml:87,124` already models it correctly and pairwise
mutex edges cannot stay sound as members are added.

### (a) Where does `depends_on` live?

**Per job, in the manifest that declares the job — on the CONSUMER side.**

```
files/anatomy/plugins/<p>/plugin.yml → pulse.jobs[].depends_on
files/anatomy/agents/<a>.yml        → pulse.jobs[].depends_on
```

For it, four arguments:

1. It is where `category` and `findings_exit_codes` just went, through a
   harvest path that already exists end-to-end
   (`test_every_job_declares_what_it_is.py` walks both sources at `:44`;
   `discover-pulse-catalog.py` emits the whole job block;
   `roles/pazny.wing/tasks/post.yml:481-510` is the POST allow-list — whose
   own comment at `:491-494` warns that an unmapped field drops in silence, so
   `depends_on` must be added there explicitly).
2. Consumer-side matches the genome's `consumes` and judge-sets' `requires:`
   — the reader declares what it reads. The writer of an artifact cannot know
   who depends on it; the reader always can.
3. It keeps the declaration next to the schedule it constrains — the two
   things that must be reviewed together.
4. The alternative (a central edges file) recreates the retired
   `authentik_oidc_apps` central-list shape that Track Q spent two weeks
   dismantling.

Against it, honestly: cross-plugin edges (cortex jobs depending on keap jobs)
put another plugin's id inside `cortex-base/plugin.yml`, which soft-couples
manifests. Accepted — the coupling is *real* (the comment at
`cortex-base/plugin.yml:127-129` already names keap jobs; the edge just makes
it machine-readable), and the compile gate (§c) catches dangling ids.

**Edge shape** — id + kind + artifact + measurement, no conditions:

```yaml
depends_on:
  - on: "pulse:keap:keap-consolidate"     # node id, one address space (§b)
    kind: data                             # data | trigger | temporal
    via: "keap datapoints (/agent/v1 capture) + cortex mirror rows"
    expects: succeeded                     # succeeded | attempted (default succeeded)
    measured: 2026-08-06                   # when `via` was last verified against code
```

- `kind: temporal` additionally REQUIRES `margin_min` (the measured minimum)
  and `schedules` (the two cron expressions it was measured against) — see §c.
- **No `condition:` field.** A condition is behaviour, and behaviour is code
  per the genome rule; an edge that can express "unless X" is a scheduler DSL
  smuggled into data.
- **Mutex is not an edge.** It is a symmetric property of a *resource*:
  `exclusive_resource: nos_entity` on two judges (`judge-sets.yml:87,124`) and
  the `pulse-run-agent.sh` lock shared by every agent job. Declared as
  `claims: [<resource>]` on the node; the graph *derives* the pairwise mutex
  edges. A pairwise mutex declaration is refused by the gate — with N
  claimants it takes N(N−1)/2 edges to stay truthful and nobody maintains
  triangle counts.

### (b) Node identity — one address space

One address space, kind-prefixed, existing local ids kept verbatim:

| kind | id form | local id source |
|---|---|---|
| pulse job | `pulse:<plugin>:<job>` | `pulse_jobs.id` composite, unchanged (`schema-extensions.sql` comment: "e.g. wing-base:rotate-wing-db-backup") |
| judge | `judge:<name>` | `state/judge-sets.yml` key |
| gate set | `gateset:<name>` | `judge-sets.yml gate_sets` key |
| weakness source | `weakness:<id>` | `files/anatomy/bone/weaknesses.py` source ids |
| daemon | `daemon:<launchd label>` | `eu.thisisait.nos.*` plist names |
| service | `service:<manifest id>` | `state/manifest.yml services[].id` |
| resource (mutex) | `resource:<name>` | judge-sets `exclusive_resource` values + new claims |

Parsing rule: kind is everything before the FIRST colon; the rest is the
existing id verbatim (pulse ids keep their internal colon). One space because
the interesting edges cross kinds — `judge:nos-smoke` requires
`resource:live_estate` (`judge-sets.yml:170`), `loop_proposals.weakness_id`
points at weakness sources and `gate_set` at `gateset:*` (live schema,
`.schema loop_proposals`), a service's health feeds a weakness source. Four
separate namespaces would make every one of those a join with a convention,
which is the current disease. No renames of the underlying ids — the archive
doc already costed the rename at ~1 000 occurrences and 8 breaking
identifiers (`nos-genome-and-organelles.md:1085-1087`).

Compiled artifact: `state/anatomy-graph.json` — generated by a
`tools/anatomy-graph-gen.py` from the manifests + judge-sets + weaknesses
registry + manifest.yml + the launchd template list, in the exact mold of
`tools/tofu-authentik-gen-registry.py` and `tools/genome-codegen.py`
(regenerate-and-diff; CI red on drift). Nodes carry their genome facets when
B1's organelle schemas land; the graph does not wait for that.

### (c) What the schema refuses — and the gate that goes red

Gate: `tests/anatomy/test_anatomy_graph_is_sound.py` (offline, walks the same
SOURCES as `test_every_job_declares_what_it_is.py`). Red when:

1. **Dangling edge** — `on:` not resolvable against the compiled node set
   (all seven kinds). A typo'd `pulse:keap:keap-consolidat` is a graph lying
   at birth.
2. **Cycle** — any cycle through `data`/`trigger`/`temporal` edges. There is
   no legitimate same-night cycle in a cron estate; a real feedback loop
   (corpus-diff verdict → next night's fs-sync) crosses a night boundary and
   is modelled as the halt **trigger** edge in the opposite direction, which
   the check treats as what it is: two nodes, two edges, two *kinds* — flagged
   for human eyes, not auto-refused. Concretely: cycle detection runs per-kind,
   not over the union, and a union-cycle is a warning listing its members.
3. **A `temporal` edge nobody re-measured** — the edge's recorded `schedules`
   pair no longer equals the two jobs' current cron expressions, or
   `margin_min` is absent. Changing a schedule without re-measuring the margin
   is the exact failure the chain lives one `jitter_min` away from; the gate
   makes the edit incomplete until `tools/anatomy-measure-margins.py`
   (the §1.4 SQL, packaged) restamps it. This is deliberately a *schedule-hash*
   staleness check, not a wall-clock one — offline pytest must not depend on
   wing.db, and "14 days old" decays into the drift-baseline lie we already
   fixed once (CLAUDE.md, scan-state 2026-07-28).
4. **Pairwise mutex** — `kind: mutex` on a `depends_on` edge is refused; use
   `claims:` (§a).
5. **Edge without an artifact** — `kind: data` with empty/missing `via:`. An
   edge that cannot name what crosses it is schedule adjacency with better
   clothes.
6. **Self-certified success semantics** — `expects: succeeded` pointing at a
   job whose declared `findings_exit_codes` make "succeeded" ambiguous unless
   the edge says which it accepts. (gitleaks exits 1 *on success with
   findings* — `test_every_job_declares_what_it_is.py:5-11`; a downstream
   edge must not read that as failure.)

### (d) What does Pulse DO with an edge? — honest answer: less than you'd hope, at first

**Phase 0 (this design): nothing.** The daemon does not read the graph. The
declaration is still worth shipping because three things read it immediately:
the two face screens (§3), the soundness gate (§c), and
`tools/anatomy-measure-margins.py` in CI-adjacent use. Declaring-without-
enforcing is the estate's normal first step (plugin-wiring-capabilities.md's
"forward-ready metadata" category) — *provided the reader list is non-empty,
which it is.*

**Phase 1 (cheap, read-only): annotate, don't control.** At dispatch, the
daemon (or Wing at `list_due_jobs` time) looks up the firing job's `data`
edges and records the upstream's latest-run state into the run row / log line:
`upstream_state: {pulse:keap:keap-consolidate: ok@04:17}`. Zero control-flow
change, zero new failure modes, and the run screen gets its edge overlay from
recorded fact instead of re-derivation. This is the "success markers written
by a reader" doctrine applied to edges: the *consumer's run* records what it
observed, not what the producer claimed.

**Phase 2 (opt-in, bounded): defer, never wait.** A per-edge
`defer_max_min: N` lets the dispatcher treat the job as *not yet due* while an
upstream `data` edge is unsatisfied (upstream still running or not yet
succeeded tonight), up to N minutes past schedule, then fire anyway with the
Phase-1 annotation saying so. Implementation is a third early-return in
`_dispatch` next to the existing re-entrancy guard
(`daemon.py:117-129`) — *skip this tick*, the shape the daemon already has —
never a held thread, never a queue. Hard rules, because waiting is where
schedulers go to die:
- upstream `paused` ⇒ edge counts as satisfied (else 9 paused agent jobs
  deadlock their consumers by declaration);
- upstream missing from the catalog ⇒ compile-time refusal, never a runtime
  hang;
- `defer_max_min` is mandatory on any deferring edge — unbounded waiting is
  refused by the gate;
- deferral applies to `data` edges only. `temporal` edges are *documentation
  of measured slack* and never gain enforcement — if an ordering matters
  enough to enforce, its edge must be promoted to `data` by naming the
  artifact, which is exactly the review the promotion forces.

What is deliberately NOT proposed: topological scheduling, a DAG runner, or
making cron minutes derived from the graph. The estate has one scheduler with
17 k runs of behavioural history; replacing its dispatch semantics to save
six jobs fifteen minutes of slack is cost without a customer.

---

## 3. Deliverable 3 — worked example: the nightly chain, declared

Diff-ready snippets — **NOT applied**; the live manifests are untouched.
Target files and anchor lines as of this commit.

`files/anatomy/plugins/cortex-base/plugin.yml` (job at `:130`):

```yaml
    - name: cortex-fs-sync
      category: knowledge
      # ... existing fields unchanged (:131-143) ...
      depends_on:
        - on: "pulse:keap:keap-consolidate"
          kind: data
          via: "night's new datapoints registered via /agent/v1 capture (keap + cortex mirror)"
          expects: succeeded
          measured: 2026-08-06
        - on: "pulse:keap:keap-consolidate"
          kind: temporal
          margin_min: 12.1          # min observed, 10 nights to 2026-08-06
          schedules: ["15 4 * * *", "30 4 * * *"]
          measured: 2026-08-06
```

`files/anatomy/plugins/keap-base/plugin.yml` (jobs at `:112`, `:141`, `:184`):

```yaml
    - name: keap-embed-sync
      # ...
      depends_on:
        - on: "pulse:cortex:cortex-fs-sync"
          kind: data
          via: "settled cortex mirror rows needing vectors (S2 fan-out)"
          expects: succeeded
          measured: 2026-08-06
        - on: "pulse:cortex:cortex-fs-sync"
          kind: temporal
          margin_min: 15.1
          schedules: ["30 4 * * *", "45 4 * * *"]
          measured: 2026-08-06

    - name: keap-features-sync
      # ...
      depends_on:
        - on: "pulse:keap:keap-embed-sync"
          kind: data
          via: "fresh embeddings read via /agent/v1 (projected onto exemplar axes)"
          expects: succeeded
          measured: 2026-08-06
        - on: "pulse:keap:keap-embed-sync"
          kind: temporal
          margin_min: 6.3           # the chain's thinnest measured margin
          schedules: ["45 4 * * *", "0 5 * * *"]
          measured: 2026-08-06

    - name: keap-lint
      # ...
      depends_on:
        - on: "pulse:keap:keap-embed-sync"
          kind: data
          via: "fresh vectors for the container's lint pass (keap-base:181-183)"
          expects: succeeded
          measured: 2026-08-06
```

`files/anatomy/plugins/cortex-base/plugin.yml` (job at `:153`):

```yaml
    - name: cortex-corpus-diff
      # ...
      depends_on:
        - on: "pulse:keap:keap-embed-sync"
          kind: data
          via: "both corpora in settled state (cortex-base:151-152)"
          expects: succeeded
          measured: 2026-08-06
        - on: "pulse:keap:keap-lint"
          kind: temporal
          margin_min: 11.3
          schedules: ["15 5 * * *", "30 5 * * *"]
          measured: 2026-08-06
```

**What the example deliberately does NOT declare:** the reverse-direction
trigger edge (corpus-diff halts fs-sync). §1.2 measured it as dead wiring —
`CORTEX_DIFF_HALT_CMD` is never set, fs-sync reads no file, and three pieces
of prose assert a stop nothing performs. Declaring that edge today would be
the graph committing the estate's signature sin: a declaration describing
something the code stopped (here: never started) doing. The rule this sets:
**repair before declare** — either wire the halt (set `CORTEX_DIFF_HALT_CMD`
to a real command, e.g. a Wing pause of `pulse:cortex:cortex-fs-sync`) and
then declare `kind: trigger`, or delete the three claims. The soundness gate
cannot catch this class (it verifies edges against nodes, not against code
behaviour); only the measurement pass that authors an edge can, which is why
every edge carries `measured:`.

---

## 4. Deliverable 3 — the two screens

### 4.0 xyops, assessed honestly

`github.com/pixlcore/xyops` — verified **BSD-3-Clause** (README), a **full
server application**, ~2 963 commits: scheduler + monitoring + its own web UI.
Its `package.json` (fetched 2026-08-06) shows the UI stack: the author's own
`pixl-xyapp` framework + **jQuery 3.7.1**, `pixl-chart`, `@xterm/xterm`,
codemirror — and **no graph/edge-rendering library at all**: the workflow
editor is hand-rolled inside the app. Consequences:

- **Vendor: nothing.** There is no component to lift into Svelte 5; the
  editor is jQuery-era code welded to pixl-server storage.
- **Reuse: the visual language and the workflow-JSON idea.** Node cards with
  typed ports, orthogonal edges, a left palette, run-state badges on nodes —
  worth imitating in our own SVG. Its data model (events/triggers/actions as
  nodes, connections as id pairs) is congruent with §2's edge shape, which is
  reassuring, not load-bearing.
- **Underlying rendering library: none to name** (that is the finding).

**Rendering decision: hand-rolled inline SVG in Svelte.** Grounds, all
measured by inventory of `files/anatomy/face`: runtime deps today = exactly
one (`html-to-image`); there is no SVG/canvas/graph code anywhere in the face
yet, and `src/lib/components/ui/motion.ts:4-22` records a deliberate rejection
of canvas UI kits. The graph is small (29 jobs + 5 judges + 4 sets + 7
weakness sources + 11 daemons + ~63 services, and the definition screen
filters by view — never all at once). Layout is a ~100-line longest-path
layered DAG in pure TS (vitest-testable). If a dependency were ever wanted:
`elkjs` (EPL-2.0, ~1.4 MB) or `dagre` (MIT, unmaintained since 2018) — named
per the constraint, recommended **against** at this node count.

### 4.1 DEFINITION screen — static graph from manifests

New Anatomy view alongside pulse/wing/bone (`AnatomyView` union in
`face/src/lib/anatomy/focus.ts`; tab added in
`src/lib/apps/native/anatomy/AnatomyApp.svelte`, which already owns view +
thread selection).

| panel | data | served by | missing? |
|---|---|---|---|
| Graph canvas (nodes by kind, edges by kind: solid=data, dashed=temporal w/ margin label, dotted=trigger, double-bar=derived mutex) | `state/anatomy-graph.json` | **missing** — generator `tools/anatomy-graph-gen.py` + one of: (a) build-time import (graph is repo state; `roles/pazny.face` syncs+rebuilds on converge — stale between converges, honest and cheap) or (b) Wing `GET /api/v1/anatomy/graph` (fresh, but a new Wing endpoint + a copy installed host-side). Start with (a); the file IS the contract either way | generator + projection `src/lib/anatomy/graph.ts` |
| Node inspector (schedule, category, claims, findings semantics, margins) | same graph + `/bff/pulse` snapshot for live state chips | `/bff/pulse` exists (`src/routes/bff/pulse/+server.ts:25`) | projection join only |
| Temporal-debt panel ("edges whose declared budgets permit inversion" — §1.4 col 4) | computed in the generator, carried in graph.json | — | part of generator |
| Unreached nodes ("declared, no edges, never ran") | graph ∪ pulse snapshot `state==='never'` | `/bff/pulse` | — |

Look: n8n-like node/edge editor *look*, read-only — panning SVG, kind-shaped
nodes, xyops-style run badges. **No editing.** An editor that writes manifests
is an agent surface (the machinery doctrine: changes propagate via commits),
not a browser feature.

### 4.2 RUN screen — live/replay over pulse_runs + loop_*

Dense-terminal aesthetic: the face already has the vocabulary (`Panel`,
`StateDot`, `Badge`, `tone.ts` with `exitTone()`, `StatusNote` for the four
non-data states — `src/lib/components/ui/`). All new fetches follow the
projection doctrine: allow-listed pure projections in `$lib/anatomy/`, GET-only
BFF gated by `canViewAnatomy` — `pulse.ts:15-18`'s reason is 57 live
credential values sitting in `env_json` upstream; nothing here may proxy.

| panel | data | served by | missing? |
|---|---|---|---|
| Night timeline (lanes per category, run bars fired→finished, exit-tone; the §1.4 margins drawn as gaps) | `pulse_runs` windowed by time | **missing** — `/bff/pulse?job_id=` exists but caps at 25 runs per job (`bff/pulse/+server.ts:41-53`); needs `GET /pulse_runs?since&until` upstream (Wing has the index: `idx_pulse_runs_fired_at`) + a `runsWindow` BFF param | Wing param + BFF passthrough + projection |
| Live tail (stdout_tail/stderr_tail, redacted upstream by `daemon.py:183-198`) | `pulse_runs` tails | exists end-to-end: `upstream.ts pulseRuns()` → `/bff/pulse?job_id=` → `loadRuns()` (`src/lib/api/pulse.ts:36`) | none |
| Loop ledger (proposals → judge runs → verdicts, WORM chain tip) | `loop_proposals`/`loop_judge_runs`/`loop_verdicts` | **missing entirely** — no Wing API surface, no BFF, no projection for loop_* today | Wing endpoint + `/bff/loop` + `loop.ts` projection (allow-list: no `diff_text` to the browser by default — it can carry secrets-adjacent hunks) |
| Judge panel (per gate-set: outcome, work_count vs min_work ratchet) | `loop_judge_runs` | same missing surface | same |
| Thread follow (run → events → notifications) | `actor_action_id` | exists: run rows carry it; `/bff/wing?thread=` (`bff/wing/+server.ts:16`) | none |
| Edge overlay on replay ("what the graph said should precede this run, and what actually did") | graph.json × runs window | Phase-1 annotation (§2d) makes this recorded fact; until then computed client-side from the two feeds | honest label: "derived, not recorded" until Phase 1 |

**"Live" means polling.** Nothing in the estate streams: the face polls at
60 s today (`PulseView.svelte:40`), Wing is a request/response Nette API, ntfy
is the only push channel and it is for humans. An SSE tail on Wing is a real
feature with real cost — named as missing, not assumed. Replay is the same
screen with a time cursor over the windowed runs query; that is the cheaper
80 % of "live".

### 4.3 Build order

1. `tools/anatomy-graph-gen.py` + `state/anatomy-graph.json` +
   `test_anatomy_graph_is_sound.py` (edges exist, gate holds them).
2. `tools/anatomy-measure-margins.py` (the §1.4 SQL, restamps temporal edges).
3. Face: `graph.ts` projection + definition view (build-time import).
4. Wing: windowed runs param; loop_* read surface; then the run screen.
5. Phase-1 dispatch annotation; Phase-2 defer only if a real incident asks
   for it.

---

## 5. Not checked

- Whether the deployed Wing at `~/wing/app` matches the repo's Wing tree
  (only the schema delta was probed, via the live DB).
- The cause of the 2026-07-27 `next_fire_at` recomputation (daemon log rules
  out a restart at that hour; Wing-side trigger unidentified).
- The stale-lock reclaim in `pulse-run-agent.sh:106-113` (`kill -0` on the
  recorded owner PID) was read, not exercised.
- xyops beyond README + package.json — its editor internals were not read;
  "hand-rolled" is inferred from the absence of any graph dependency.
- Whether Wing's `POST /api/v1/pulse_jobs` on the live host errors or
  silently drops unknown fields (observed effect only: columns absent, upsert
  succeeded on 2026-08-06).
- launchd plist contents beyond `eu.thisisait.nos.pulse` (labels enumerated,
  bodies unread).
