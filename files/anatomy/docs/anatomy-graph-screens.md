# Anatomy graph screens — definition, run, and the on-demand surfaces

Status: BUILT (first pass), 2026-08-06 evening. The graph layer is live
(`state/anatomy-graph.json` + `tools/anatomy-graph-gen.py` +
`tools/anatomy-measure-margins.py` +
`tests/anatomy/test_anatomy_graph_is_sound.py`) and both screens now exist:
`GraphView.svelte` (definition) + `RunsView.svelte` (runs), tabs 4 and 5 of
the Anatomy app. Survey + measurement this rests on:
`docs/archive/nos-anatomy-graph.md` (§1 edges, §2 schema, §4 screens).
Corrections found while building are marked **[corrected]** inline; the
per-surface "which converge makes it live" list is §8.

Doctrine constraints that bind everything below:

- **Projection, never proxy.** `face/src/lib/anatomy/*.ts` are allow-list
  projections — `pulse.ts:8` records why: `/api/v1/pulse_jobs` carries 57
  live credential values in `env_json`. No new BFF route may forward an
  upstream body unfiltered, in either direction.
- **Changes propagate via commits** (machinery doctrine). No browser surface
  may mutate the repo, a manifest, or a schedule. A button may RUN something
  already declared; it may never ALTER what is declared.
- **Success markers are written by a reader.** A button records the request;
  the executor records the run. The UI never stamps an outcome.
- **Read-only face**: both screens render; neither edits. The definition
  screen is explicitly an n8n-LOOK, not an n8n.

---

## 1. The contract: `state/anatomy-graph.json`

Compiled by `tools/anatomy-graph-gen.py` (regenerate-and-diff; CI red on
drift). Byte-stable: no timestamps, sorted keys/edges.

```
counts    — node/edge tallies per kind (2026-08-06 after the core-substrate
            extension: 179 nodes, 134 edges)
warnings  — union-kind cycles (real feedback loops, e.g. the corpus-diff halt)
nodes     — id → {kind, source, anchor, description, …per-kind facts}
edges     — [{from, to, kind, …}] sorted by (kind, from, to)
```

Address space (kind-prefixed, local ids verbatim — survey §2b):
`pulse:<owner>:<job>` (= wing.db `pulse_jobs` id), `judge:<name>`,
`gateset:<name>`, `weakness:<id>`, `daemon:<launchd label>`,
`service:<manifest id>`, `resource:<name>` — plus, since the 2026-08-06
core-substrate extension (operator ask): `repo:<name>` (the four git surfaces:
github-origin, gitea-forge, gitlab-forge, scan-data), `tofu:<name>`
(terraform state roots), `authentik:<slug>` (the 43 registry rows from
`state/tofu-authentik-services.yml`, each bound to its manifest service where
one exists), `table:<name>` (the six `state/keap-tables/*.table.yml`
definitions — **[corrected]** there is no `ideas` table; the brief's mention
of one was stale).

Two declaration channels now, both consumer/actor-side in the job's own
manifest: `depends_on:` (what a job READS — upstream → job) and `writes:`
(what a job WRITES — job → target). A writes edge requires `via:` AND
`measured:`, its target must resolve, and each shipped one is pinned by a
code-backed test (scan-state-record → repo:scan-data; contradiction-scan →
table:roadmap, valid only while `--file` is in its args; promote-migration →
repo:gitlab-forge). `repo:github-origin` deliberately has NO automated
writer and a gate asserts the absence — promote-public.sh is gh-auth-gated
operator-only, and a job silently gaining a push to the public trunk is
exactly what `test_github_origin_has_no_automated_writer` refuses.

Every node also carries `anchor` (a KEAP taxonomy anchor id, validated
against `state/fable/taxonomy-bundle.json` — a dangling anchor is refusal
class 1 applied to the import) and `description` (a one-line body worth
embedding). See §7 for why.

Edge kinds and their screen glyphs:

| kind | declared vs derived | fields | glyph |
|---|---|---|---|
| `data` | declared (`depends_on` in the job manifest) | `via` (mandatory artifact), `expects`, `on_findings`, `measured` | solid arrow |
| `temporal` | declared | `margin_min` (measured), `schedules`, `gap_min`, `declared_margin_min`, `can_invert`, `measured` | dashed arrow, margin label; red accent when `can_invert` |
| `trigger` | declared (the halt) + derived (`daemon-dispatch`) | `via`, `derived?` | dotted arrow |
| `mutex` | ALWAYS derived from node `claims` | `resource`, `derived: "claims"` | double-bar, non-directional |

Manifest edge field is **`upstream:`**, not the survey's `on:` — YAML 1.1
parses a bare `on` key as boolean `True` (`yaml.safe_load("on: x")` →
`{True: "x"}`); the generator refuses the trap by name.

---

## 2. DEFINITION screen — the static graph

New view in the existing Anatomy app: extend
`face/src/lib/anatomy/focus.ts` `AnatomyView` union with `'graph'`; add the
tab in `face/src/lib/apps/native/anatomy/AnatomyApp.svelte` (it already owns
view + thread selection); new `GraphView.svelte` beside
Pulse/Wing/BoneView.

**Data path: build-time import — [corrected] via a vendored copy.** The face
container's build context is `files/anatomy/face/` ONLY (the
`roles/pazny.face` synchronize task copies just that tree), so an import of
`state/anatomy-graph.json` cannot resolve in the image build. The generator
therefore writes a byte-identical second copy to
`face/src/lib/anatomy/anatomy-graph.json`; `--check` and
`test_the_face_vendored_copy_is_identical` refuse drift between the two.
Otherwise as designed: stale between converges, honest and cheap, zero new
credential surface. A fresh-serving endpoint stays deliberately unbuilt.

**Rendering: hand-rolled inline SVG** (survey §4.0 decision, grounds
re-verified: face runtime deps = `html-to-image` only; xyops itself ships NO
graph library — its editor is hand-rolled jQuery). Layout = longest-path
layered DAG in pure TS, `face/src/lib/anatomy/graphLayout.ts`, vitest beside
it (`graphLayout.test.ts`): rank by longest path over `data|trigger|temporal`
edges, order within rank by barycenter, one pass, no iteration cap needed at
this size (~125 nodes; the view filters by kind so a typical canvas shows
< 40). `elkjs`/`dagre` remain named and rejected at this node count.

Panels (survey §4.1, all data already available):

| panel | data | notes |
|---|---|---|
| Graph canvas | graph.json | nodes shaped by kind; edges per the glyph table; pan via viewBox drag, zoom via wheel; keyboard focus cycling for a11y |
| Node inspector | graph.json + `/bff/pulse` snapshot | live state chips (last exit, next fire) join on the `pulse:` id — the BFF projection already serves this |
| Temporal debt | graph.json `edges[kind=temporal]` | the §1.4 table rendered: `margin_min` vs `declared_margin_min`, `can_invert` rows first. 4 of 5 chain edges are permitted to invert by their own declared budgets — this panel is the reason the screen exists |
| Warnings strip | graph.json `warnings` | the halt feedback loop, named, with both edges highlighted on hover |
| Unreached | graph nodes ∩ pulse snapshot `state==='never'` | declared, scheduled, never ran |

**No editing.** No drag-to-connect, no schedule field. The graph is authored
in manifests, measured by `tools/anatomy-measure-margins.py`, reviewed in a
diff.

---

## 3. RUN screen — live watch + replay over `pulse_runs` + `loop_*`

Second new view: `'runs'` in the same union, `RunsView.svelte`. Dense
terminal aesthetic; reuse `Panel`, `StateDot`, `Badge`, `tone.ts exitTone()`,
`StatusNote` (`face/src/lib/components/ui/`).

| panel | data | surface today | missing piece (owner) |
|---|---|---|---|
| Night timeline — lanes per category, bars fired→finished, exit-tone fill; temporal-edge margins drawn as inter-lane gaps | `pulse_runs` windowed by time | Wing `listRuns` (`PulsePresenter.php:252`) supports `job_id`+`limit≤500`+`failed` — **no time window**; BFF caps 25/job (`bff/pulse/+server.ts:44`) | **Wing**: `since`/`until` params on `GET /api/v1/pulse_runs` (index exists: `idx_pulse_runs_fired_at`). **BFF**: pass-through `?since&until` on `/bff/pulse`, projection stays allow-list. **Face**: timeline component |
| Live tail — stdout/stderr tails (already redacted daemon-side, `daemon.py:183-198`) | `pulse_runs` tails | exists end-to-end via `/bff/pulse?job_id=` | none |
| Loop ledger — proposals → judge runs → verdicts | `loop_proposals`, `loop_judge_runs`, `loop_verdicts` | **BUILT — and [corrected]: these are BONE surfaces, not Wing.** The ledger schema lives in `bone/ledger.py` and its auth is the loop's own scope channel (`loopauth.py`), so the reads landed as `GET /api/v1/loop/{proposals,judge_runs,verdicts}` (read scope) with explicit column lists — `diff_text` excluded at the SQL, refused AGAIN by the face projection (two locks). Gate: `test_loop_ledger_lists.py` | live on the next Bone restart (launchd daemon reload), not a Wing converge |
| Judge panel — per gate set: outcome, `work_count` vs `min_work` ratchet | `loop_judge_runs` | BUILT — the verdict RINGS in `RunsView.svelte` (see the ring note below) | same Bone restart |
| Thread follow — run → events → notifications | `actor_action_id` | exists: `/bff/wing?thread=` | none |
| Edge overlay on replay — what the graph said should precede this run vs what did | graph.json × runs window | computable client-side | label honestly **"derived, not recorded"** until Phase-1 dispatch annotation (survey §2d) lands |

**"Live" means polling and must say so.** Nothing in the estate streams;
the face polls at 60 s (`PulseView.svelte:40`). The run screen may poll at
10 s while visible — cheap against Wing's read path — and renders a "polled
Ns ago" stamp instead of pretending to stream. SSE on Wing is a real feature
with real cost; it stays on the named-missing list, not assumed.

**Replay** is the same screen with a time cursor over the windowed query —
the cheaper 80% of "live". Cursor scrubbing re-filters loaded runs
client-side; no new surface.

**The radial figure (operator refinement, 2026-08-06): spokes are
EXECUTIONS, not workers, and each finding opens another ring.** Ring 0 the
run, ring 1 its units (judges in a set / components in a batch), ring 2
findings, ring 3 what each finding spawned. Measured ring sizes run 5 (gate
set `full`) to 125 (the contradiction scan's pairs) — both are the same
component and neither is padded. Model: `face/src/lib/anatomy/rings.ts`,
with the two invariants enforced in code and tested: (1) the arc count is
driven by the RECORDED denominator, so 100 skipped pairs render as 100 unlit
spokes rather than a footer nobody reads; (2) depth is bounded by data —
`ring()` returns null for an empty level. Three spoke states minimum:
judged-good, judged-bad, **NOT JUDGED** (hatched, distinct from both — an
INDETERMINATE judge or an absent container is not a faded pass), plus
`unaccounted` (declared scope with no row: hollow outline). An unjudged
spoke with no reason is refused by the model. What is built today renders
ring 1 (verdict → declared judges); rings 2–3 (findings → spawned rows)
await list surfaces for scan batches and weakness sweeps and are named
missing, not simulated.

---

## 4. On-demand runs — the one write, precisely bounded

Two distinct acts, two existing/one new surface. Neither mutates the repo;
both RUN something already declared. Both buttons render only for Tier-1
callers and both re-check server-side (a hidden button is not access
control).

### 4a. Run a gate set (loop judges) — the surface ALREADY EXISTS

Bone `POST /api/v1/loop/judge` (`bone/looproutes.py:258`): 202 + job id,
async; `GET /api/v1/loop/judge/{job_id}` for status. Its refusals are
already right, server-side: unknown gate set → 404; the ONLY input that
selects work is the gate-set NAME ("no parameter that supplies, hints at, or
overrides a result"); proposal/gate-set mismatch → 409. Auth is the
loop's third credential channel (`loopauth.py`): the face BFF uses
`BONE_LOOP_JUDGE_TOKEN` (evaluator identity — "Pulse / operator").

Face work: `POST /bff/loop/judge` with body allow-list of exactly
`{gate_set}` — `proposal_uuid` is deliberately NOT forwarded (judging a
proposal is the loop engine's ceremony, not a browser act), plus a status
poll passthrough. Verdicts land in `loop_judge_runs`/`loop_verdicts`, so the
run screen's ledger panel shows the result — the reader records the outcome,
the button only requested it.

Refusals the BFF adds: caller below Tier-1 → 403; any body key other than
`gate_set` → 400 (refuse, don't strip — a stripped key trains callers to
send garbage); `unattended: false` sets (today: `full`) → 409 with the
reason (it contains judges that require an attended host).

### 4b. Run a pulse job now — ONE new Wing endpoint

`POST /api/v1/pulse_jobs/<id>/run-now` (Wing, new). Semantics: set
`next_fire_at = now` on the row and append an `events` row
(`pulse_run_requested`, `actor_id` = forward-auth identity, fresh
`actor_action_id`). **The daemon remains the only executor** — the request
is picked up on the next 30 s tick with every existing guard intact:
re-entrancy (`daemon.py:117-129`), the 4-slot cap, `max_concurrent`, and the
agent-run-lock for claude spawns. No new spawn path, no synchronous
execution, no env/command override — a run-now that can alter env is remote
code execution with extra steps, so the body is EMPTY.

Refusals (Wing, server-side): unknown id → 404; `paused` job → 409 carrying
`paused_reason` (unpausing is a separate deliberate act, not a side effect
of impatience); caller below Tier-1 → 403 (`$minAccessTier` /
`requireTier`, the RBAC surface Wing already has). Jobs with
`category: agents` spawn a claude with `--permission-mode
bypassPermissions`; they are NOT excluded, because Tier-1 is already the
operator — but the 409-on-paused rule bites here first (all 9 paused jobs
are agent runners, paused for a reason).

Face work: `POST /bff/pulse/run`, body allow-list `{job_id}`, forwarding
with the edge token + forward-auth headers. The button then just watches the
runs feed — the run appearing there is the daemon's statement, not the
button's.

**Sequencing note:** the deployed Wing at `~/wing/app` lags the repo (its
`init-db.php` is dated 2026-08-02). Everything in §4b and the two Wing read
surfaces in §3 becomes live only on the converge that redeploys Wing — any
plan that assumes them must name that converge.

---

## 5. Grafana vs the face — which question each answers

**Grafana** answers: *"how has the estate behaved over weeks, across
services, and should something page me?"* Long-horizon retention,
cross-service joins (wing_sqlite datasource beside Prometheus/Loki/Tempo),
threshold alerting through the relay. The pulse-run history that belongs
here is the AGGREGATE: runs/day by exit class, duration trends, margin-trend
per temporal edge (a panel over the margins the graph declares — fed by the
existing wing_sqlite datasource, no new pipeline).

**The face (Anatomy/SERE)** answers: *"what is the estate doing right now,
what happened last night, and run it again while I watch."* Identity-joined
(`actor_action_id` thread follow), sub-minute polling, replay cursor,
on-demand runs. Nothing here needs retention beyond wing.db's own.

**No duplication rule:** the face gets no long-range trend charts (that is
Grafana's question); Grafana gets no run-now buttons and no live tail (the
face's question — and tails are redacted-but-sensitive, which a shared
Grafana dashboard must not carry). The one deliberate overlap is "last
night's chain": the face shows it as a timeline with margins; dashboard
22-ai-agents shows its aggregate success rate. Different questions, same
rows.

---

## 6. Observability wiring — measured state, 2026-08-06

Re-measurement of the genome survey's "~95% dead metadata" claim, this tree,
denominators stated. 75 plugin manifests; **42 declare `observability:`**.

| atom | declarers | live consumer | verdict |
|---|---|---|---|
| `loki.labels.stack` | 42 | `load_plugins.py:421-428` `_plugin_stack` (stack_filter routing) | ALIVE |
| `loki.labels.app` / `.tier` | 42 | none — only `stack` is read | dead |
| `metrics_of_interest` | 4 (grafana-keap, portainer, qdrant, vaultwarden) | none (repo-wide grep) | dead |
| `observability.grafana.dashboards` | 3 (qdrant non-empty; portainer, vaultwarden `[]`) | none — grafana-base's live `copy_dashboards` reads its OWN `provisioning.dashboards`, a different key | dead |
| `observability.alerts` | 1 (vaultwarden) | none — live alert rules are static files (`prometheus-base/provisioning/rules/*.yml`) | dead |
| `observability.prometheus.scrape` | 1 (qdrant) | `topological_order` implicit DAG edge ONLY — **fixed 2026-07-31 (`0f8beccf`)**, the survey brief's "fires for 0 of 41" is stale: it now fires for 1 of 42. Still never rendered into any scrape config | ordering-only |

So the corrected claim: **1 of 6 atom families has a live consumer, and of
the 3 label keys only 1 is read** — "~95% dead" was directionally right;
the precise statement is the table.

Found while measuring, not previously recorded:

- **`qdrant-base` post_compose lifecycle is largely decorative**: of its 8
  actions, `ensure_secret` (×2), `bootstrap_collections`,
  `register_bone_client`, `register_wing_client`,
  `register_prometheus_scrape`, `import_grafana_dashboard` are ALL unhandled
  by the action dispatcher (`load_plugins.py:899-1095` handles 11 named
  actions; unknown actions return `unknown:<name>` and nothing fails). Only
  `wait_health` runs.
- **The estate's only live qdrant/gitea/firefly scrapes 401/401/404** and
  have fired `NosWarningServiceDegraded` since 2026-07-26: Alloy
  (`files/observability/alloy/config.alloy.j2:93-147`) scrapes
  `localhost:6333` (qdrant → 401, `/metrics` now requires the API key — the
  manifest comment "unauthenticated" is stale), `localhost:3003` (gitea →
  401, token required), `localhost:3014` (firefly → 404). Plus
  nginx/php-fpm exporter targets that are down because `install_nginx:
  false` is the default. **All five firing alerts are permanently-red
  wiring, not service incidents** — and since the alert relay landed they
  now reach Bone nightly, which will train the operator to skim exactly the
  channel that was just unmuted. Fixing them means touching the live Alloy
  config/playbook vars — written up here, deliberately not changed in this
  commit.

What landed 2026-08-05/06 and is NOT re-derived here: the Prometheus→Bone
alert relay (`prometheus-alert-relay.py`, `alert-relay-base`), the CVE drift
metric via the Alloy textfile collector, `findings_exit_codes` + `category`
per pulse job.

---

## 7. KEAP import shaping — what the artifact now carries, and what must NOT be built yet

Intent (operator, 2026-08-06): the graph should be indexable and renderable
inside KEAP so custom views can SCOPE it — by service (anchor), by string
(hybrid/FTS over the body), by entity (kind). Two of those were missing from
the artifact and are now in it:

- **`anchor` per node** — a KEAP taxonomy anchor id from the committed
  362-anchor spine (`state/fable/taxonomy-bundle.json`). Without one every
  imported node is an `orphan-object` — measured: keap-lint reported 26/27
  fixture findings as exactly that, "invisible in the universe". Per-kind
  defaults refined per category where the branch is unambiguous
  (security → 02.02.08, agents → 02.02.09, knowledge → 09, notification →
  03.08, compliance → 04.06, databases → 02.02.05, …), honestly-generic
  Software Engineering (02.02.04) otherwise. The soundness gate refuses an
  anchor the bundle does not hold — a dangling anchor IS a dangling
  reference.
- **`description` per node** — a one-line body worth embedding, composed
  from the node's own facts (and a curated map for the 12 daemon labels,
  which carry no prose anywhere else in the repo). This doubles as the
  LLM-readability deliverable; it is one piece of work, not two.

What already worked by luck and is now pinned: kind-prefixed ids.
`cortex-corpus-diff.py` classifies any object id not starting with `fs:` as
not-a-mirror-row (withdrawn from the fs clause), so an anatomy import cannot
zero the agree-streak — bare ids would have. `test_kind_prefixed_ids_survive`
keeps it that way.

**Preconditions of the actual import — named, deliberately NOT built:**

1. **The nightly-diff fold.** A neutral object still gets its own line in
   the corpus diff, so 179 nodes means 179 benign findings per night until
   the harness folds them into a single counted line (the same fold already
   needed for `table-*` row objects). Harness changes land AFTER a streak
   completes, never during one. Do not import before the fold exists.
2. **The route is runtime state, not corpus.** The graph changes every
   converge; pushing it through the canonical git taxonomy tree would cost a
   KEAP tag + pin bump + re-vendor + converge per change. Recommended
   surface: a **KEAP DataTable** (`anatomy-nodes`, one row per node, upserted
   by a converge-time task the way the `systems` table is fed from the
   service registry) — cost: one table definition + one idempotent seeder
   task + the fold above; the anchor column then drives panel placement and
   the description feeds hybrid search with no /ingest ceremony. `/ingest
   capture` is the wrong shape (it is for preservation-reviewed corpus
   items, and 179 review-queue entries per converge is the orphan problem
   with extra steps). Not built in this pass.

## 7b. The constitution layer (operator ask, 2026-08-06 evening)

The doctrine has a taxonomy and an ontology now, in the same address space as
everything else:

- **`doctrine:<doc>#<section>`** nodes — minted only for paragraphs a graph
  node's own manifest block actually cites (12 on 2026-08-06); each carries
  the real heading as its body and anchor `09`, so KEAP scoping works on the
  law shelf like on everything else. A paragraph invented to give a citation
  somewhere to point would be the same defect as a picture-filling node —
  none were.
- **`governed_by` edges** — node → paragraph, derived by
  `anatomy-graph-gen.py::derive_doctrine` from `tools/doctrine-cite.py`, the
  ONE resolver the gate also runs. Attribution is per manifest BLOCK, with
  the comment-above-the-key convention honoured (the naive ranges handed
  cortex-corpus-diff's DECISION 2e to nos-smoke — caught and gated by
  `test_attribution_is_per_block_not_per_file`). 17 edges on 2026-08-06.
  File-header citations are deliberately NOT edges (they attribute to a
  file, not a block). Weakness-source attribution (per-function in
  weaknesses.py) is named, not built — it needs an AST walk.
- **The resolver** (`tools/doctrine-cite.py`) covers the full estate, not
  just graph sources. Measured 2026-08-06 after repairs: **1061 citations,
  929 resolved (87.6%), 124 unqualified (bare § with no declared authority
  — reported, never guessed), 2 external (RFC), and a 4-item verified
  residue** (a line-number §205, two cross-repo KEAP spec paths, the phantom
  REM-088). Nine stale addresses were REPAIRED at the citing site (pointer
  fixes, no law authored): five citations of framework-plan.md's pre-A1 docs/
  location now name `files/anatomy/docs/framework-plan.md`,
  2× the archived adjustments-design, 2× cortex nickname-qualifiers, plus
  the grafana §6.2/§6.3 conflation qualified to bones-and-wings-refactor.md.
  Gate: `test_doctrine_citations_resolve.py` — frozen residue (both
  directions), bare-citation ceiling 124, resolved floor 925.
- **UI**: doctrine kind + `governed_by` styling in GraphView (`§` nodes, the
  green dashed edge IS the highlight), and per-gate-set paragraph chips in
  RunsView's committed-definition block with citing lines in the tooltip.

## 8. Which converge makes each surface live

| surface | ships in | becomes live when |
|---|---|---|
| graph artifact + anchors + new kinds | this commit (repo state) | immediately for repo readers; face copy at next face rebuild |
| GraphView / RunsView / projections | `files/anatomy/face/` | next converge that runs `roles/pazny.face` (sync + image rebuild) |
| Bone loop list reads (`/api/v1/loop/*` GET) | `files/anatomy/bone/` | next Bone daemon restart (`launchctl` reload via `roles/pazny.bone`) |
| `/bff/loop` + `/bff/loop/judge` | face tree | face rebuild |
| face loop credential | **WIRED** (`01e44916`, 2026-08-06 evening) | `roles/pazny.face/templates/compose.yml.j2:66` carries `BONE_LOOP_JUDGE_TOKEN`; live after the converge that redeploys the face |
| Wing `since`/`until` on `GET /api/v1/pulse_runs` | BUILT (`PulsePresenter::timeParam` — canonicalised, garbage → 400; `PulseRepository::listRuns` range on `idx_pulse_runs_fired_at`) | next Wing converge; until then the deployed Wing ignores the params and the face's replay hint says so |
| Wing `run-now` (§4b) | BUILT to spec (`Pulse:runNow` route; row edit + `pulse_run_requested` event only; 404/409-paused/400-body refusals; gate `test_pulse_run_now_and_window.py` pins "not a spawn path") | next Wing converge |
| `/bff/pulse/run` + PulseView run-now button | face tree | face rebuild |
| doctrine layer (nodes + `governed_by` + resolver + gate) | this commit | immediately for repo readers; UI at face rebuild |
| Phase-1 dispatch annotation (survey §2d) | NOT BUILT — deliberately | it changes the DAEMON's dispatch path, which this pass does not touch (scheduler semantics deserve their own review); replay edge overlay stays "derived, not recorded" and is therefore not drawn |
| rings 2–3 data (scan batches → findings → spawned rows; weakness sweeps) | NOT BUILT | needs list surfaces over scan batches + weakness runs that do not exist; building the rings against re-derived client-side joins would render claims nothing recorded |
| night-timeline lanes panel | NOT BUILT | honest only once the DEPLOYED Wing honours `since`/`until` — lanes drawn over the unwindowed 25-run default would draw a lie; build it the converge after Wing redeploys |

## 9. Build order (updated)

1. ✅ graph layer: generator + artifact + soundness gate + margins tool +
   nightly chain declared (incl. the halt trigger edge — `97abdb7c`).
2. ✅ core-substrate extension: repo/tofu/authentik/table kinds, `writes:`
   channel, anchors + descriptions, vendored face copy (2026-08-06 evening).
3. ✅ Face definition screen: `graph.ts` + `graphLayout.ts` + `GraphView`.
4. ✅ Bone ledger list reads + `/bff/loop` + `/bff/loop/judge` + `loop.ts`
   + `rings.ts` + `RunsView` (ring 1).
5. Face compose env for `BONE_LOOP_JUDGE_TOKEN` (one line, §8) — first
   converge-facing change on this list.
6. Wing: `since`/`until` on runs list; `run-now` (§4b).
7. Phase-1 dispatch annotation (survey §2d) — turns the replay edge overlay
   from "derived" into "recorded". Phase-2 defer stays parked until an
   incident asks for it.
8. Rings 2–3 data: list surfaces for scan batches (components → findings →
   REM rows) and weakness sweeps (sources → weaknesses → proposals).
9. KEAP import: the §7 fold + the `anatomy-nodes` DataTable seeder — only
   after a streak completes.
