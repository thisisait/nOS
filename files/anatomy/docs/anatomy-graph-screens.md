# Anatomy graph screens — definition, run, and the on-demand surfaces

Status: build contract, 2026-08-06. The graph layer it consumes is LIVE in
this commit (`state/anatomy-graph.json` + `tools/anatomy-graph-gen.py` +
`tools/anatomy-measure-margins.py` +
`tests/anatomy/test_anatomy_graph_is_sound.py`); the screens are specified
here precisely enough to build and are NOT yet built. Survey + measurement
this rests on: `docs/archive/nos-anatomy-graph.md` (§1 edges, §2 schema,
§4 screens).

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
counts    — node/edge tallies per kind (measured 2026-08-06: 125 nodes, 90 edges)
warnings  — union-kind cycles (real feedback loops, e.g. the corpus-diff halt)
nodes     — id → {kind, source, …per-kind facts}
edges     — [{from, to, kind, …}] sorted by (kind, from, to)
```

Address space (kind-prefixed, local ids verbatim — survey §2b):
`pulse:<owner>:<job>` (= wing.db `pulse_jobs` id), `judge:<name>`,
`gateset:<name>`, `weakness:<id>`, `daemon:<launchd label>`,
`service:<manifest id>`, `resource:<name>`.

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

**Data path: build-time import.** `state/anatomy-graph.json` is repo state;
`roles/pazny.face` syncs + rebuilds on converge. The view imports the JSON at
build time (Vite JSON import) — stale between converges, honest and cheap,
and zero new credential surface. A Wing `GET /api/v1/anatomy/graph` endpoint
is the fresh alternative and is deliberately NOT chosen for phase 1: the
graph changes only when the repo changes, and the repo reaches the host by
converge anyway. Revisit only if the face ever renders on a host without the
repo.

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
| Loop ledger — proposals → judge runs → verdicts | `loop_proposals`, `loop_judge_runs`, `loop_verdicts` | **no Wing read API, no BFF, no projection** (re-verified: zero mentions in `wing/app/Presenters/`) | **Wing**: read-only `GET /api/v1/loop/{proposals,judge_runs,verdicts}`. **BFF**: `/bff/loop`. **Face**: `loop.ts` projection — allow-list EXCLUDES `diff_text` (secrets-adjacent hunks stay server-side) |
| Judge panel — per gate set: outcome, `work_count` vs `min_work` ratchet | `loop_judge_runs` | same gap | same surfaces |
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

## 7. Build order

1. ✅ graph layer (this commit): generator + artifact + soundness gate +
   margins tool + nightly chain declared (incl. the halt trigger edge, now
   backed by code — `97abdb7c`).
2. Face: `graphLayout.ts` + `GraphView.svelte` (definition screen; no new
   endpoints needed).
3. Wing: `since`/`until` on runs list; loop_* read endpoints; `run-now`
   (§4b). Ships live on the next Wing converge.
4. BFF: runs window passthrough; `/bff/loop` (read + judge POST); `/bff/pulse/run`.
5. Face: `RunsView.svelte` (timeline, ledger, judge panel, replay cursor).
6. Phase-1 dispatch annotation (survey §2d) — turns the replay edge overlay
   from "derived" into "recorded". Phase-2 defer stays parked until an
   incident asks for it.
