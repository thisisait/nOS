<!-- Filed 2026-08-17, late. This was produced by the six-dimension research
workflow of 2026-08-16 and cited by tools/workflows/anatomy-root-site.js as
`docs/idea/17` for two days while existing only in a workflow transcript.
The operator acted on parts of it — the v0.11 descope, the adapter freeze —
so it was already load-bearing when it was unfiled. Sections 1 and 2 are
partly superseded: the operator has since chosen `nos-mandate` for the
tenant surface and returned nos-lang to the control-centre abstraction.
Kept verbatim; corrections belong in a later doc, not in a rewrite. -->

# 17 — The loop split, the refactor, the graph

**Status: decision record, 2026-08-16.** Follows `16-orchestrator-question.md` (written yesterday) and answers the operator's three-part proposal: split the loop into an end-user half and a self-enhancement half; refactor AgentKit to TS or Python; adopt a library for the anatomy graph.

Six dimensions were researched and each was adversarially reviewed. **Where a review objected, I follow the review** — in five of six cases the objection was independently reproducible, and I re-verified the load-bearing ones myself. Those re-verifications are marked ✅ below. Everything else is inherited and labelled.

Doc budget: `docs/idea/` holds 17 ideas across 18 files against a hard ceiling of twenty (`00-index.md:7`). This is the 17th. Two slots remain.

---

## 1. The loop split

### The instinct is right. The shape and both names are wrong.

The operator is distinguishing two things that genuinely differ, and the difference is not audience — it is **who approves, who is the data subject, and whether a judge can exist**.

| | the maintenance loop | the customer-facing path |
|---|---|---|
| unit of change | `target_paths` + `tree_sha` | a row about a person |
| approver | the operator, on `gate-add` only | the company, in writing, on every write |
| data subjects | `operators` (+ `commit_authors`, `automation_identities`) | the company's customers — a new subject class |
| legal basis | `legitimate_interests`, nOS as controller | nOS as **processor**, on documented instructions |
| oracle | five judges, deterministic, proposer cannot touch them | **none today** |

That last row is the real cut, and it is the one the operator's naming does not express.

### What I keep

**`nos-loop` stays exactly as it is.** It is not a proposed name — it is a shipped identifier across `files/anatomy/bone/bin/nos-loop`, 5,335 LOC in `{weaknesses,judges,ledger,budget,looproutes,loopauth}.py`, `.claude/plugins/nos-loop/`, four `loop_*` tables in `wing.db`, and ~10 gate files. Renaming it costs a sweep for zero gain. Its `intent_class` CHECK stays a closed six-value enum. `budget.py:78-85` `ALLOWED_ROOTS` stays six repo paths. **No tenant column, ever.**

### What I reject: "nos-spine"

"Spine" already carries four live meanings, and the two most-live ones name **the components the business path must SHARE**:

- `w-agentkit-spine` — "every agent run goes through AgentKit", i.e. *one* agent runtime
- `docs/idea/14-notification-spine.md` — "THE SPINE", the notification abstraction
- the KEAP L0-2 taxonomy spine (`tools/keap-fable-bundle.py`, `tools/anatomy-graph-gen.py:174`)
- a retired "Spine organ" (`docs/roadmap-2026q2.md:1265`)

A fifth meaning would assert *separation* about the things that must not separate. That is inverted, not merely ambiguous.

I also reject the loop-split dimension's counter-proposal, **`nos-work`**. Its review is correct: a literal-string grep returns nothing, but `work_count`, `min_work` and `run.work` are the loop engine's own anti-vacuous-pass vocabulary (`ledger.py`, the `loop_judge_runs` CHECK: *a PASS that cannot show its work is not storable*). A collision test that would have cleared "spine" is the wrong test.

### The names I propose

> **`nos-loop`** — the maintenance engine of the box. Repo-scoped, six intents, five judges, single host, `tree_sha`-pinned. Self-improvement.
>
> **`nos-mandate`** — the tenant-scoped execution surface. Every action runs under a written mandate from a controller who is not us. Not a loop.

`mandate` has zero identifier collisions in the repo ✅ (three hits, all unrelated prose). It is also the GDPR term of art for exactly this relationship — Art 28(3)(a), *"processes the personal data only on documented instructions from the controller"* — so the name carries the constraint rather than decorating it. Alternative if `mandate` reads too legal: **`nos-errand`** (zero hits of any kind ✅).

The pairing is deliberately **asymmetric**: one is a machine, the other is a scope. That asymmetry is the honest part. `nos-mandate` becomes a loop the day it has a deterministic judge its proposer cannot touch — and not before.

### Two corrections to the research that change the price

**(a) The business cut is NOT "already made and one string wide."** The loop-split dimension claimed `CortexCapability(verbs × namespaces × tenants)` already carries it. I verified the live surface ✅:

```
api_tokens:  cortex-executor | tenants=default | namespaces=tax,rel
CortexExecutorPresenter.php:113-114
  if (!empty($body['commit'])) sendError('mutating execution is
    not available in P1; `commit` must be false', 403)
```

The one tenant-scoped token is **read-only over KEAP taxonomy**, `db:` deliberately absent. Adding a company as a second value grants ontology reads and nothing else. It is not the business cut.

**(b) The estate already priced this and the research missed it.** `docs/roadmap-2026q2.md:1267` ✅: *"Multi-tenant fleet mode (per-tenant-on-one-host) … ~5× more work — Authentik tenants, Wing /hub multi-tenant view, per-tenant secret namespaces, per-tenant data segregation. Postponed."* Any plan premised on "one string wide" must reconcile with that row.

**(c) I do not claim the business side "cannot have an oracle."** The research asserted that as its thesis while conceding in its own unestablished list that it never tried to design one. `15-business-fixture.md:98` names *"the loop — a question whose right answer changed since the last time it was asked"* as a fixture surface, and `cortex-corpus-diff` is already a judge of exactly the derivation-checking shape. The honest statement: **a deterministic judge over given business data is plausible and unbuilt.** Finding one is the gate for promoting `nos-mandate` to a loop.

### What is refused outright

No second daemon, second ledger, second budget, second judge registry. `11-agentic-loop-contract.md` §6 DECISION 6 already settles ownership: *"HTTP is the only implementation… No shared library, ever. Three runtimes exist and a fourth is planned"* — AgentKit is designated a **client** of the Bone engine. Bone's `budget.py`/`judges.py` are not a rival regime that accidentally re-derived three properties; they are that engine, built to that contract.

And no tenant rows anywhere near the chained tables until `wing-events-chain-aware-retention` closes. Art-17 erasure against a WORM hash chain is unsolved; walking into it holding customer data is the worst possible order.

---

## 2. The refactor

### Neither port nor wrap. New code in Python. `16-orchestrator-question.md` is CONFIRMED, not overturned.

Both of doc 16's operative decisions survive. One of them survives an attack that failed on its own terms.

### The deciding evidence: the veto count is smaller than anyone thought

The governance inventory catalogued 52 behaviours and concluded "6 vetoes at 3 hook points". Its review corrected the third hook point away, and the correction reproduces:

- `assertSessionCeiling` is called at **exactly two sites** — `Runner.php:495` (before every model call) and `:681` (top of every outcome iteration).
- `Runner.php:589` (tool execute) has **no veto gate**. `MigrationWriteTool` and `BashReadOnlyTool` fail *soft* into `ToolResult::error` — they refuse nothing at the host level. The capability-scope refusal that does abort is `ToolRegistry::forAgent`, called at `:176`, **before the session UUID exists** — i.e. pre-loop.
- The third host-dependent property is not a hook at all: `LLMCapabilityError` must **propagate**, and its enforcement is the *catch ordering* at `:815` above `:828`.

So the acceptance test for any orchestration host is four items, not three, and only two are hooks:

> 1. Can a callback **abort before a model call**?
> 2. Can a callback **abort at an iteration boundary**?
> 3. Does an exception from the model call **propagate** without the framework's own retry/fallback swallowing it or silently re-sending to another provider?
> 4. Does an abort at (1) **still record what was spent**?

**This is the deciding evidence, and what it decides is that veto capability does not decide anything.** Six of eleven surveyed hosts can refuse a model call in 2026 (LangChain `wrap_model_call`, Pydantic AI `SkipModelRequest`, CrewAI `@before_llm_call`, Google ADK, Mastra `abort()`, OpenAI Agents guardrails). A four-item test that most candidates pass is not a discriminator. The 2024 folklore that "LangChain callbacks are observational" — repeated in doc 16 §2 — **is stale and should be corrected there.**

### Do not port Runner (doc 16 decision 2 — confirmed, and now priced higher)

The measured bill for a port:

- 7,635 LOC of PHP across 44 files, with **zero direct PDO** — every DB touch routes through six `App\Model` repositories (1,902 LOC).
- **38 of 374** anatomy gates reference AgentKit, and a material share assert by regex over PHP source (string indices, `const NAME` presence, catch-clause *ordering*). Those are rewrites, not retargets, and the properties are unpinned while they are rewritten — which is the exact state that produced four defects in one week.
- `Tools/` is **1,454 LOC** the research omitted and which no framework supplies: verb allowlist, per-verb argv guards, two-arm path allowlist, realpath containment, 256 KiB/null-byte guards, the reply-token drop.
- The **approval queue** is missing from the inventory of 52 entirely, and it is the most-exercised governance mechanism on the estate: `agent_approval_request` 33 rows, `agent_approval_decision` 31 rows — more than `agent_message` (27). `AskOperatorTool` blocks inline for `MAX_WAIT_SECONDS = 90` against Pulse's 300s `max_runtime_s`, with `ttl_seconds` + `default_on_expiry` and an explicit *"pending is not permission"*. That timing constraint is a port requirement nobody had written down.

Doc 16's arithmetic (≈1.5 of 4 defects avoidable, 2–4 weeks plus revalidation) holds. Note the 2–4 weeks is doc 16's assertion and remains underived; the 38-gate half reproduces exactly.

**One argument I withdraw from the sequencing dimension:** "all four graded AgentKit sessions failed on rubric/task mismatch, therefore no port." Two of those four rows graded a connectivity smoke probe (*"Reply with the single word: ok"*), so the real sample is two. And grader failures are orthogonal to the operator's stated reason for a port, which was library compatibility. The refusal stands on the LOC and gate arithmetic. It does not need the non-sequitur.

### Do not wrap yet either

The inventory proposed extracting the 19 pre-loop gates as `wing/bin/resolve-binding.php --agent=<n>` returning JSON, priced at ~1 day. Its review kills that price: `BindingResolver::resolve()` returns a `Binding` carrying a **live bearer token** dereferenced from `nos:minimax_api_key`. A JSON subprocess must either emit that secret across a process boundary — contradicting the estate's own "the Factory is the only place a secret is touched" rule — or omit it, in which case the two unnumbered post-arm refusals (empty tier model-id env; unresolvable auth_secret) cannot be evaluated by the caller and must be reimplemented host-side.

The seam is a good idea with an unsolved secret boundary and **no second caller yet**. Build it when the spike produces one. Then it returns a *decision* (backend, `model_effective`, refusal reason, credential-resolvable boolean) and never a credential.

### The language: Python, for the right reason

Python — but not for the reason the language dimension gave. Its central claim, *"TypeScript has ZERO SQLite access anywhere in the estate"*, is false. `files/anatomy/cortex` declares `libsql: ^0.5.29` ✅, is 18,600 LOC of TS, and runs as launchd daemon `eu.thisisait.nos.cortex`. A node daemon with its own SQLite store already runs on this ARM64 Mac. The differential TS cost the recommendation rested on is largely already paid.

The reason that survives is simpler and stronger: **`loop-driver` is new code that drives 5,335 LOC of Python living in the same process.** Bone is FastAPI, the ledger's role-scoped `sqlite3` authorizer is Python, and `clients/wing.py` already carries a byte-parity, gate-pinned mirror of PHP's `AuditChain` — so a Python driver writes chain-valid audit rows on day one with no new work.

Price it honestly. This makes **five** LLM- or agent-capable runtimes: PHP AgentKit, Python Hermes (whose venv already holds `anthropic 0.120.0` and `openai 2.48.0`), node OpenClaw, node Cortex, and the new driver. And Bone's dependency surface is **29 resolved packages**, not the 6 declared in `requirements.txt` — size the CVE argument off the resolved count.

### The spike stays LangGraph-in-Bone (doc 16 decision 3 — confirmed)

The orchestrators dimension recommended substituting Pydantic AI. I decline, and its review is why:

- It **moved the goalposts**. Doc 16 §4.3's spike target is *"LangGraph-in-Bone driving the weakness→propose→judge cycle"*. The substitute target was *"Pydantic AI on nos-spine"* — a different loop. Nothing in the survey evaluated Pydantic AI on the only loop that has a written contract.
- It **strawmanned §4.3**. §4.3 reads *"the loop driver (`loop-driver`, queued — the self-improvement engine's missing piece) does not exist yet"* ✅ — that sentence presupposes an existing engine. "nos-loop is not greenfield" agrees with §4.3; it does not falsify it.
- The **§7 argument is a category error**. §7.2 (no scheduler), §7.5 (no auto-apply) and §7.6 (no new daemon/port/organ) describe things LangGraph is not and does not ship; a library imported into the existing Bone process is not a new organ. Only the checkpointer-vs-ledger duplication has bite, and LangGraph's durability is a parameter, not a requirement.
- It **lost on its own announced discriminator**. Having declared that veto no longer decides and that churn and dependency surface do, it picked the candidate that shipped 57 releases and crossed a major in 90 days over the one that shipped 11, all inside 1.2.x. The tiebreaker actually used was an instinct-match.
- Its pick **rested on a property it could not establish** — whether `SkipModelRequest` is auditable as a refusal — which was also its own acceptance test. The spike would have been justified by the thing the spike exists to find out.

Two corrections to carry into the spike anyway: the "LangChain callbacks are observational" premise in doc 16 §2 is stale and should be struck; and `langsmith` is **inert by default** (`tracing_is_enabled()` returns False with no env var), so the sovereignty objection reduces to "one more package the CVE scan carries" — true of `logfire-api` equally.

**Add one item to the spike's pass/fail, written before it starts**: the four-item acceptance test above, verbatim, with item 4 (an abort must still record the spend) as a hard fail. That item is what `Runner.php:364-369` and commit `0c84b92b` ("a ceiling is not an error") were both written to fix.

### One defect this research found that nobody was looking for

`serveFallback` (`Runner.php:919`) builds the fallback client as `$this->llmFactory->fromUri($agent->modelFallbackUri)` — **no `Binding` argument, no `BindingResolver` call**. Gates 4 (Article-30 processor agreement), 7 (protocol) and 8 (residency, including the no-degrade half) therefore never apply to whatever actually answers when the primary fails. There is no live exposure today only because all nine agents' fallback is a local model. But the estate's headline claim — *EU residency enforced by the record, not a config flag* — is true of the primary binding and **not of the serving set**, which is precisely the distinction `state/llm-backends.yml:69-74` draws.

**This is a defect, not a design question. Fix it before anything else in this document.** It is a one-line change plus a gate.

### Spike result (2026-08-17)

Run per this clause: `langgraph==1.2.11` in an isolated `.spike-venv/`, adapter `tools/orchestrator_hosts/langgraph_host.py` driving a real `StateGraph` loop (boundary → gate → model, iteration edge back, no checkpointer), judged by the pre-committed `tools/orchestrator-acceptance.py`.

- **All four items PASS**, including the hard item 4: `actually spent in/out 20/10; ledger recorded 20/10; finished=True`. Reference pair behaved (null 4/4 PASS; broken 3 FAIL + 1 HARD FAIL). A `Refusal` raised in a gate node propagates out of `invoke()` before the model node runs; `ModelBroke` escapes unretried (default `retry_policy` is none).
- **Checkpointer is a parameter, not a requirement** — VERIFIED: `StateGraph.compile(checkpointer=None)` is the default and every probe ran without one. Corollary, measured: on an exception, `invoke()` yields no state and checkpointer-less partial state is unrecoverable — the spend tally must be written by the caller that owns the ledger (the adapter's `finally`), not by a node. The ledger/checkpointer duplication objection does not arise; the ledger stays outside the graph.
- **`langsmith` is inert by default** — VERIFIED: under `env -i`, `langsmith.utils.tracing_is_enabled()` → `False` (langsmith 0.11.0).
- **No phone-home at import or first run** — VERIFIED by a raising socket guard (`socket`, `create_connection`, `getaddrinfo`) around import + a 4-iteration run: zero external attempts. The single socket constructor call is urllib3's import-time IPv6 capability probe against loopback `::1` (`urllib3/util/connection.py:137`).
- **Dependency arithmetic** — 1 declared package resolves to **35** (pip freeze). Licences: MIT/BSD/Apache/PSF throughout; MPL-2.0 on `certifi` and (file-level, with Apache/MIT) `orjson`; no copyleft beyond that. Bone's live venv measures **26** resolved today (this doc said 29 at research time); name-overlap is 13, so LangGraph-in-Bone's-venv would add **22 packages (26 → 48)**. One real conflict: `langgraph-sdk` pins `websockets<16`; Bone runs `websockets 16.1.1` under uvicorn — co-installation forces a downgrade.
- Two adapter-layer facts for the eventual `loop-driver`: node/branch callables must not annotate a method-local state schema (`get_type_hints()` forward-ref `NameError` under `from __future__ import annotations`); and the operator's pyenv **global** site-packages already carries an undocumented `langgraph 1.1.10` + `langchain 1.2.18` stack, which also passes 4/4 — the spike venv exists precisely so that stray install is not what got measured.

**Verdict: LangGraph fits the four-item contract.** The open question from §5 — veto *between tool calls inside a prebuilt agent node* — remains unmeasured; this spike used a hand-built graph, where the gate-node seam is trivially available.

---

## 3. The visualisation

### `d3-force@3.0.0` (ISC), as a second layout mode. Not a replacement, not a renderer swap.

### Was "techNosIdeas" found? Yes — and it holds no candidate

It is a live KEAP DataTable (`d237570c-52ee-4fe0-9c37-51923d50ac5d`, 50 rows, created 2026-07-31) with a 40-file research corpus on the SSD. **Every graph-adjacent row is a tool, not a drawing library**, and every one was decided `watch` or `refuse`: `ai-knowledge-graph` (watch, *"Inspirace?"*), `graphify` (watch), `CanvasMind` (refuse), `canvasui.dev` (refused, no summary), `xyops` (postpone), `circle` (implement).

Two gaps could hold the operator's memory and neither is recoverable from the estate: `nexu-io/open-design` is `status=new`, never researched; `canvasui.dev` was refused with an empty decision and no summary. **If the memory is of a capture that never reached the table, it is gone.**

The only libraries the estate ever named in `docs/` are elkjs and dagre, both rejected in `docs/archive/nos-anatomy-graph.md:531-535`. **Both facts in that rejection are now stale**: `dagre@0.8.5` is dead (2019), but `@dagrejs/dagre@3.1.1` shipped 2026-08-08; elkjs is `EPL-2.0 OR GPL-3.0-or-later` and **469 KB gzipped**, not "~1.4 MB". The force/stress family was never evaluated at all.

### What the graph actually is

The graph-viz dimension benchmarked a picture the face does not draw — it fed all 235 raw edges including the 56 pairwise `mutex` lines that `filterForCanvas` explicitly excludes, which is the exact noise `tests/anatomy/test_a_claim_is_drawn_as_a_claim.py` was written to stop. Its review re-measured through the real pipeline:

| view | nodes | connectors | canvas | crossings |
|---|---|---|---|---|
| **default** (what the operator opens) | 60 | 71 | 1368×1390 | 308 |
| all kinds, connected | 153 | 192 | 1808×3106 | 2409 |
| the artifact | 207 | 235 | — | — |

The "124-wide layer" that anchored the *"no layered library can fix this"* argument does not exist in either real view — widest column is 30 (default) and 69 (all-kinds). And the hand-rolled justification (`graphLayout.ts:3-4`, *"for ~40 visible nodes"*) is stale by 1.5×, not by 5×.

**Force still wins, on both measurements.** The review's own replica: 398 crossings on all-kinds (matching the original's 399) and **75 vs 308 on the default view** — a 4× improvement on the picture the operator actually complains about.

### The decision

Add `forceLayout()` beside `layout()` in `graphLayout.ts` (~70 lines), a mode toggle in `GraphView.svelte`, and a vitest that sha256s the output positions to pin determinism (verified reproducible bit-for-bit across fresh processes). Run the sim once per filter change, not per frame — 400 ticks on 151 nodes is 118 ms.

**Keep the layered mode.** It is the right picture for the 8-rank temporal/trigger spine.

**Rejected:** elkjs (469 KB gz for 8% better than d3-force; 8 MB unpacked; dual EPL/GPL); `@dagrejs/dagre` (canvas 81% *taller*); cytoscape/sigma/vis-network/viz.js (renderer swaps that destroy the keyboard-focusable `<g role="button" tabindex="0">` nodes whose aria-labels carry *"— layer withheld, upstreams never surveyed"*, `GraphView.svelte:278-296`); `@xyflow/svelte` (a renderer with no layout, 2 runtime deps, and an attribution link — re-open it for the *loop* graphs later, where handles and minimap earn their keep).

### What it costs

- **+4 runtime packages** (d3-force, d3-dispatch, d3-quadtree, d3-timer — all ISC), ~12 KB gzip. This ends *"the face has exactly ONE runtime dependency"*. That is a doctrine price needing the operator's assent, not a benchmark's. Do **not** cite `test_npm_installs_are_script_hardened.py` here — that gate is about `--ignore-scripts` and is untouched.
- **Lines go UP, ~+70.** The "642 lines of hand-rolled layout" is `graphLayout.ts` (129 lines, the layout) plus `graph.ts` (513 lines, a *projection*: node kinds, glyphs, live-pulse tone joins, temporal debt, service coverage, mutex spokes, governing-paragraph citations). No library has an opinion about any of that. Anyone promising fewer lines is promising a renderer swap, and that swap costs the a11y.
- ~0.5 day.
- One more package in the security queue. `d3-force@3.0.0` has not been published since 2021-06-05 — stable, zero transitive surface beyond three ISC micro-packages.

### Do NOT bake positions into `state/anatomy-graph.json`

The graph-viz dimension's step 2. Three reasons to refuse it:

1. It collides with three live gates — `test_the_graph_is_byte_stable`, `test_the_committed_graph_matches_a_fresh_build`, `test_the_face_vendored_copy_is_identical`. The generator is Python (74 KB); the layout is TS. Baking means a bit-identical Python d3-force or shelling node out of the generator.
2. It puts a rendering concern inside a **measurement artifact** compiled from manifests.
3. **The KEAP precedent argues the opposite of what it was cited for.** `graphify.md:138`: *"Hash-frozen deterministic bake — galaxies on a fixed ring, children on Fibonacci-sphere directions, jitter seeded by SHA-256(salt:id) … d3-force exists but taxonomy stars arrive fx/fy/fz-pinned with charge 0, so the engine never moves them."* KEAP's answer to force instability was to place **analytically** and pin the simulator out — not to persist a simulation result.

If insertion instability bites (one new node moves the other 151 by mean 254 px; 225 px with hash-seeded starts), do it KEAP's way.

### The larger readability win is not a library

56 of 207 nodes have degree 0. The default view already hides 147. **Semantic clustering** — `authentik:X` under `service:X`, services under their stack — will do more than any layout swap, needs no dependency, and is where compound-layout support would finally be worth buying. ~2–3 days, separate piece.

### Built (2026-08-17)

The operator assented to the dependency cost; `forceLayout()` shipped beside `layout()` in `graphLayout.ts`, mode toggle in `GraphView.svelte`, layered mode stays the default. Everything below was measured through the real `filterForCanvas` pipeline (straight-segment proxy for the drawn connectors), not inherited from this document.

| view | nodes | connectors | layered crossings | force crossings |
|---|---|---|---|---|
| default | 60 | 71 | 330 | 50 |
| all kinds, connected | 153 | 192 | 2418 | 219 |

- **The node/connector counts reproduce this doc's table exactly; the crossing figures do not** (this doc: 308 → 75 on default). Same conclusion, different numbers: layered measured 330 (anchor/proxy sensitivity vs the review's replica), force measured 50 with the shipped tuning (link 140 / charge −460 / collide 58, 400 ticks, seeded). 6.6× on the picture the operator opens.
- **Packages: +4 runtime, exactly as predicted** — `d3-force 3.0.0`, `d3-dispatch 3.0.1`, `d3-quadtree 3.0.1`, `d3-timer 3.0.1`, each ISC per its installed `package.json` and LICENSE — plus `@types/d3-force 3.0.10` (MIT), devDependencies only. Installed `--ignore-scripts`; the 6 `npm audit` findings on the tree predate this change (toolchain deps, none d3).
- **Bundle delta from a real build:** client JS 114,824 → 120,757 bytes gzip (**+5.9 KB**, against the ~12 KB predicted); total built JS +16.1 KB uncompressed (client + server).
- **Simulation wall-clock** (once per filter change, never per frame): default view ~29 ms; all-kinds 153 nodes ~100 ms for 400 ticks (this doc: 118 ms / 151 nodes — consistent).
- **Determinism — re-verified, not inherited.** Even the UNSEEDED (Math.random-sourced) simulation hashed bit-for-bit identical across fresh node processes and across Node 22.23.1 / 24.19.0 (two V8 majors) on this host — the doc's claim holds, but as a property of the input (phyllotaxis initial placement never coincides two nodes, so `jiggle()` never draws), not of the library. `forceLayout()` therefore pins `simulation.randomSource()` to a constant-seeded mulberry32, making determinism constructional; the sha256 of the default-view positions is pinned in `graphLayout.force.pin.json` and asserted by `graphLayout.test.ts` (the hash lives outside the test file because the fixture-secret gate refuses 64-hex literals in `*.test.ts`). Linux equality was NOT locally established; CI's ubuntu vitest job is the arbiter.
- **A11y survives in both modes, gated:** both layouts place the identical node id set through the single `role="button" tabindex="0"` markup path (`{#each placed.nodes}`); `graphLayout.test.ts` pins the id-set equality and the one-markup-path source contract, and pins force < layered crossings on the default view so the mode's justification cannot rot silently.

---

## 4. The implementation workflow shape

**This is the part to act on.**

### Build FIRST: one honest attended `nos-loop` cycle

Not a split, not a port, not a library. Every downstream question in this document is a claim about **per-cycle cost, latency and refusal rate**, and nobody has a datum.

The engine is complete and deployed: `/api/v1/loop/weaknesses` answers **401**, `/judge` answers **405** — mounted and auth-gated, not absent. It returns 66 live weaknesses (11 high / 36 medium / 19 low), `complete: true`. And it has **never been driven for real**: 9 proposals, all from test identity `agent:x`, all created within 50 seconds on 2026-08-02 ✅; last verdict 2026-08-03; `loop_forgets` empty; `loop_attempts` does not exist.

### Preconditions — one of them is not what the research said

**P0. Fix the ungated fallback** (§2 above). One line plus a gate. It is a live governance hole and it is cheap.

**P1. Pause two nightly jobs for the cycle window.** `conductor:vulnerability-scan` (`0 2 * * *`) and `conductor:scan-state-record` (`30 3 * * *`) execute scripts that write tracked files under `docs/llm/security/` into this checkout. A `repo`-set cycle needs a clean tree for its sandbox (contract §2.7). **Committing the three dirty files once does not hold** — the tree re-dirties at 02:00 and 03:30 every night. The sequencing research reported "only 2 unpaused pulse jobs"; the real count is **21 unpaused / 9 paused** ✅.

**P2. Commit or stash the three dirty security files.**

**P3. Do NOT cut v0.11-beta first.** No finding requires it. It is an independent release ceremony with its own gate (`tools/ci-local.sh`, a `dev→master` PR needing `--admin`, dev re-sync, tag, release). Cutting a tag in the same week four AgentKit runtime defects shipped and HEAD is a same-day fix is a preference. It must not run *concurrently* with a cycle; that is the whole constraint.

### Sequential trunk — one worker, owns the tree

- **S1 — one attended cycle**, end to end via the existing `/loop-improve` plugin, against a real item from the live 66, with a real proposer identity. No new code, no new language, no new organ.
- **S2 — `loop_attempts`.** `state/roadmap-probes.yml:76` makes `grep -q "CREATE TABLE IF NOT EXISTS loop_attempts" files/anatomy/wing/db/schema-extensions.sql` the literal closing probe for `loop-forget`. The first cycle will show you need it.
- **S3 — per-skill rubrics for librarian.** Two of the four `agent_iterations` rows are a real skill/rubric mismatch (*"rubric applies to 'Recall brief' … but agent performed [taxonomy-brief]"*); the other two graded a smoke probe. Zero sessions have ever graded `satisfied`. Cheapest agent-side fix available; costs no architecture.

### Parallel — provably disjoint

- **P-A: d3-force second layout mode.** Disjoint by construction: `files/anatomy/face/**` is outside `budget.py`'s positive `ALLOWED_ROOTS` whitelist, so the loop cannot reach it; separate suite (vitest vs pytest); separate build. **Single-commit PR**, because it ends the one-dependency posture.
- **P-B: this doctrine page + the naming.** Prose only. No slug, table-column, plugin-id or roadmap-row rename.
- **P-C: `15-business-fixture` increment 2 — synthetic people only.**
- **P-D: the semantic clustering piece** (`authentik:X` under `service:X`), if a fourth worker exists.

### Must NOT run in parallel — each is a measured collision

1. **A cycle and any bare `pytest tests/anatomy`.** Only `judges.py` acquires `nos-loop-<resource>.lock`; a human's pytest acquires nothing, and `test_genome_contract.py` mutates a tracked file in place and restores it in a `finally`.
2. **A cycle and any edit under** `roles/`, `tasks/`, `apps/`, `upgrades/`, `default.config.yml`, `files/anatomy/plugins/`. The verdict stores `tree_sha`; the replay guarantee dies if the tree moves.
3. **A cycle and the two nightly repo-writing conductor jobs.** (P1 above.)
4. **A cycle and the v0.11 tag.**
5. **Anything and real personal data.**

Two cycles in parallel are safe (they take the lock). A cycle plus a worker's test run is not.

### CHECKPOINT — ask the operator again

**When the first real verdict exists.** Pass, fail, or indeterminate — all three count. That is the moment a per-cycle cost, latency and refusal rate exist for the first time, and it is the input to every remaining question here.

Do not proceed past it into:

- an unattended Pulse job running the loop (contract §7.2 requires attended runs first; there have been **zero**)
- the LangGraph spike
- any language port
- any slug / roadmap-row / KEAP-table-column rename
- any real person in the fixture
- the multi-tenant work the roadmap prices at ~5×

**Standing tripwires — stop and ask before the checkpoint:** a face PR adding more than one dependency, or any dependency with transitive deps; a diff touching `app/AgentKit/**` for language reasons rather than a named defect; a `gate-add` proposal (the engine flags it `requires_operator` by design); a proposal whose `target_paths` reach outside the six `ALLOWED_ROOTS`.

### First irreversible commitments, in encounter order

1. **The face dependency.** Revertible by one `git revert`, but it ends a stated posture. Own PR.
2. **Renaming into slugs, roadmap rows or KEAP table columns.** *First materially irreversible.* Per `docs/idea/10`, a roadmap row is a live KEAP DataTable migration seeded by `tools/roadmap-seed.py` — "a live migration of the operator's board, not a converge side-effect". The estate has a documented year of `tier` carrying four meanings. **This is why §1 stops at prose.**
3. **Deleting PHP AgentKit.** Not on any list in this document.
4. **Loading a real person into the fixture.** Irreversible in law, not in git. There is no Article-30 register entry for the fixture's processing of customer data; the 88 records shipped 2026-08-13 are the agent ceremonies', a different register.

### What this shape gives up

It defers the operator's two most interesting asks — the framework answer and the loop split as *machinery* — by roughly a week. It accepts that the AgentKit plumbing stays hand-owned in the interim. The KEAP brief backlog does not move while the librarian ceremony stays paused. Those are the costs, and they are affordable; an unbounded architecture migration argued from zero cycles is not.

---

## 5. What is still unestablished

Carried up, not swallowed. Each is stated as a gap, not a guess.

**On the split**

- **Who may set `cortex_tenants`, and how an Authentik identity maps to a tenant value.** There *is* a pinned issuer — `roles/pazny.wing/tasks/post.yml:247-258` with a hardcoded `--cortex-tenants=default`, and `provision-token.php:44-53` refuses a partial axis set. The gap is narrower than the research said and worse for its conclusion: the only issuer is an Ansible task, so a second tenant is a converge or a new issuer, not a string edit.
- **Whether a deterministic oracle over business data exists.** Nobody attempted to design one. Until someone does, `nos-mandate` is a scope, not a loop.
- **Whether `~/nos/tenants` exists as a runtime concept on this host.** CLAUDE.md and memory reference it; `ls ~/nos` returned nothing.
- **SQLite writer contention** when Wing, Bone and a judge runner write concurrently. Contract §9.5 records it as unmeasured; nobody measured it. wing.db is 740 MB / 337,937 events in WAL, so readers are safe; the single-writer path is not characterised.
- **Whether any current ceremony already reads tenant-shaped data.** The nine Art-30 records name only operator-facing categories, but librarian/curator KEAP reads were not traced against `state/keap-tables/party*.table.yml`.

**On the refactor**

- **Whether LangGraph can veto between tool calls *inside* a prebuilt agent node**, as opposed to at node boundaries. This is the single fact the spike turns on and it is unmeasured on both sides. No framework was installed or tested by any dimension.
- **Whether the 38 AgentKit-scoped gates express language-independent properties.** Their assertion style (string indices into PHP source, `const NAME` presence, catch-clause ordering) was read; how many could be re-expressed rather than rewritten was not estimated.
- **The "2–4 weeks" port figure.** Inherited from doc 16, traceable to no measurement anywhere. The 38-gate half reproduces; the calendar half does not.
- **Whether the shell-bridge path is a deliberate carve-out or an unclosed gap.** `pulse-run-agent.sh` bypasses every one of the 52 behaviours; `AgentSessionRepository::synthRow` synthesises rows with `model_uri='cli:unrecorded'`, no trace_id, no ceilings, no binding gates — and the most recent conductor session on this host is one. The sentinel's docblock explains the *value*; no document states the *intent*.
- **Whether the Anthropic Python SDK runs under the frozen CI toolchain.** It is proven on this host (Hermes venv, `anthropic 0.120.0`, Python 3.13.13, live under launchd) — but the GitHub runner's import path is a documented separate universe.
- **Whether repo↔runtime parity holds for Bone.** `estate-status.py` reports Bone and Wing as reachable but version-less; the loop routes answer 401/405, so the loop *is* mounted, but "the deployed binary is at the commit I read" is not establishable with present tools.
- **Whether `SkipModelRequest` (or any framework's refusal) is auditable as a refusal** — i.e. whether the run record distinguishes "governance refused" from "the model answered". Unresolved for every candidate.

**On the visualisation**

- **Nobody built the face with d3-force and looked at it.** Every crossing figure is a Node/Python reimplementation of the drawing inputs, using straight segments as a proxy for the horizontal-control-point bezier the face actually draws. Faithful proxy; not a screenshot.
- **Whether semantic clustering helps.** One clustered run (grouping by node *kind*) made the canvas *larger* — 3270×7006. The useful grouping is semantic and was never built.
- **`elk.radial` crashed** with a stack overflow on this graph. Untested, not rejected.
- **Whether `@xyflow/svelte` renders under this app's SSR.** Only the peer range and installed Svelte version (5.56.6 against `^5.25.0`) were checked.
- **Whether the offline/portable-SSD ambition tolerates `npm ci` reaching the registry at image-build time.** Today's single dependency already needs it, so this adds no new class of problem — but nobody has recorded a decision.

**On sequencing**

- **What one real cycle costs** in tokens, wall-clock or refusal rate. No datum, which is why S1 is S1 — and which means "2–3 days for the trunk" is an estimate with no prior.
- **The "1277 KEAP nodes lacking a brief" figure** was never confirmed against the live API; the pacing argument inherits it.
- **Whether last night's 7 proposed briefs were accepted into KEAP moderation.** Only the session's grade (`failed`) was measurable. "Ran successfully" and "produced useful output" are separable here.
- **Whether a `repo` cycle's sandbox is a git worktree or an APFS clone.** Contract §9.2 leaves it explicitly undecided; if it turns out complex, the S1 estimate is low.

---

### One-line summary for the roadmap

> Keep `nos-loop`; name the business half `nos-mandate` in prose only; do not port AgentKit (doc 16 confirmed, now priced at 7,635 LOC + 1,454 in Tools + 38 gates + an unrecorded 90s approval block); put new orchestration in Python inside Bone and keep doc 16's LangGraph spike with a corrected four-item acceptance test; add `d3-force` as a second face layout mode and do not bake positions; and **before any of it, run one attended loop cycle**, because the engine has answered 401 for two weeks and has never once been asked a real question.