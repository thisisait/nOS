# The two loops — diagrams and full accounts (companion)

> Companion to [`docs/doctrine/loops.md`](doctrine/loops.md), split out
> 2026-09-03. The doctrine file keeps the rules, refusals and the missing-edge
> ranking under stable section numbers; this file carries the verified Mermaid
> diagrams and the full narratives, verbatim, under the same numbers. Code
> cites the doctrine file's sections, never this one.
>
> **Legend, used in every diagram.** Solid arrow = the edge exists and was
> verified against the repo (the pinning gate or measurement is named in the
> label or the surrounding prose). Dashed arrow = **partial or TARGET** — it
> does not fully exist, and drawing it solid would be the defect class the
> doctrine is about. Where a claim could not be verified, the diagram says so
> in place. Every date is a measurement, not decoration.

## 0. The night of 2026-08-20→21, in full

On the night of 2026-08-20→21 the loop ran unattended for the first time.
`loop:propose` filed a real proposal at 01:38. `loop:drive` at 06:12 reported
"no passed proposal is waiting to land" — and it was right: a fresh proposal
has no verdict, the reader listed only passed rows, and the driver acted only
on those. **Nothing joined the step that makes a proposal to the step that
lands one.** The gap survived a full day of attended use because a human judged
every proposal within a minute of filing it — a person was silently an edge in
the graph, and the omission surfaced only when he went to bed. (Closed the next
afternoon: `f3b34a19`, §3.4 puts judging on the driver; gates
`test_a_passed_verdict_is_never_silent.py`,
`test_the_driver_lands_without_merging.py`.)

## 1. Two loops — the overview diagram

```mermaid
flowchart LR
  subgraph NOS["nOS loop proper — the estate serving its purpose"]
    PULSE[Pulse daemon<br/>owns every cadence]
    SEC[security pipeline<br/>scan → queue → drift watch]
    OBS[evidence organs<br/>Bone · Wing · readers]
    FORGE[forges + CI<br/>Gitea/Woodpecker · GitLab]
    EST[running estate<br/>~50 services]
  end
  subgraph SERE["SERE — the estate improving its own source"]
    W[weakness reader] --> P[proposer] --> J[judge engine] --> D[driver] --> R[reviewer] --> DEV[(dev trunk)]
  end
  OP((operator))

  PULSE -- "schedules propose/drive/review<br/>(loop-base plugin, gate: test_the_loop_has_a_cadence)" --> SERE
  SEC -- "rem:/scan: weaknesses" --> W
  OBS -- "alert:/pulse:/corpus:/git:/fee: weaknesses" --> W
  D -- "branch + MR" --> FORGE
  FORGE -- "CI verdict on the exact sha" --> R
  DEV -. "converge — OPERATOR act,<br/>no automated edge by design" .-> EST
  EST -- "next scan re-measures" --> SEC
  OP -- "converge · forget · dev→master ·<br/>GitHub push · tags · removals · unpause" --> NOS
```

## 2. SERE — the state-machine diagram

```mermaid
flowchart TD
  SRC["weakness reported<br/>7 sources: rem· fee· scan· git·<br/>corpus· alert· pulse (weaknesses.py)"]
  WH["WITHHELD — evidence file ≠ HEAD<br/>(committed-evidence rule; contract §11)"]
  PICK["entry: loop-propose picks worst<br/>unproposed + proposable + fixable"]
  MODEL["one claude run, agent mutex,<br/>proposer identity only"]
  FILED["proposal filed (201) — state: unjudged"]
  JUDGED{"driver judges<br/>(gate set = the proposal's own)"}
  READY["ready — applies to HEAD,<br/>judged base still HEAD"]
  REJ["re-judge — verdict decayed:<br/>the judged tree is gone"]
  DEAD["terminal, reported: fail ·<br/>indeterminate · conflict · unusable"]
  MR["branch fix/loop-* on Gitea+GitLab,<br/>MR on GitLab, CI on the sha"]
  REV{"reviewer: 3 questions<br/>CI? · judges? · same diff?"}
  WAIT["INDETERMINATE — waits for<br/>tomorrow's tick, merges nothing"]
  MERGED["merged into dev on GitLab"]
  PROM["promotion: forge-sync --apply<br/>Gitea + local dev fast-forward"]
  LANDED["landed — reverse patch applies<br/>(git's answer, nobody's claim)"]
  CONV["converged onto the estate"]
  RET["weakness retired — the scanner's<br/>answer, read from the queue"]

  SRC -->|"evidence committed"| PICK
  SRC -->|"scan wrote, nobody committed —<br/>refusal names the unblocking commit"| WH
  WH -.->|"OPERATOR commits docs/llm/security —<br/>no cadence owns this edge"| PICK
  PICK -->|"fee:/vendor-blocked refused, exit 3<br/>= news, not a crash"| MODEL
  MODEL -->|"POST /proposals · 201"| FILED
  MODEL -->|"409 budget/fingerprint/size —<br/>quote the engine, stop"| DEAD
  FILED -->|"gap CLOSED 2026-08-21 f3b34a19:<br/>unjudged is the driver's to pick up"| JUDGED
  JUDGED -->|"pass"| READY
  JUDGED -->|"fail / indeterminate — never conflated"| DEAD
  READY -->|"driver lands: base preflight ×2 forges,<br/>equality both directions"| MR
  READY -->|"base moved since the verdict"| REJ
  REJ -->|"--rejudge against today's HEAD"| JUDGED
  MR --> REV
  REV -->|"any NO"| DEAD
  REV -->|"any unanswerable question"| WAIT
  WAIT -->|"next 06:50 tick re-asks"| REV
  REV -->|"YES ×3"| MERGED
  MERGED -->|"step of the merge, not a memory<br/>(gate: test_forge_sync_owns_the_directions)"| PROM
  PROM --> LANDED
  LANDED -.->|"OPERATOR converge —<br/>deliberate; but the wait has no reader (§7.3)"| CONV
  CONV -.->|"scanner re-scan; the queue does not<br/>learn from a converge (§7.2)"| RET
```

## 3. The unattended night — the cadence as a clock

All times as committed in the manifests (one shared clock; the load-bearing
facts are the *order* and the *margins*, not the wall time). Verified against
`files/anatomy/plugins/*/plugin.yml` and `files/anatomy/agents/conductor/agent.yml`.

```mermaid
sequenceDiagram
  participant PU as Pulse
  participant PR as loop‑propose 01.30
  participant SC as security scans 02.00–03.30
  participant KC as KEAP/cortex chain 04.15–05.30
  participant DW as drift watch 06.00
  participant DR as loop‑drive 06.10
  participant CI as Woodpecker
  participant RV as loop‑review 06.50

  PU->>PR: 01:30 — entry half (unpaused 2026-08-20)
  Note over PR: picks worst weakness, spawns ONE model run<br/>BEFORE the scan dirties the queue (43a6dd08)<br/>exit 3 = refusal, recorded as findings, not a crash
  PU->>SC: 02:00 vulnerability-scan (LLM) → writes docs/llm/security/* UNCOMMITTED
  Note over SC: 03:00 gitleaks · 03:30 scan-state-record<br/>(snapshots queue onto refs/heads/scan-data — local only)
  PU->>KC: 04:15 consolidate → 04:30 fs-sync → 04:45 embed → 05:00 features → 05:15 lint → 05:30 corpus-diff
  Note over KC: the ONE pulse chain with declared, measured<br/>temporal margins (anatomy-graph temporal edges)
  PU->>DW: 06:00 conductor:security-drift-watch (deterministic)
  PU->>DR: 06:10 — evaluator half
  Note over PR,DR: THE EDGE THAT WAS MISSING 2026-08-21 01:38→06:12:<br/>an unjudged proposal fell between propose and drive.<br/>Closed f3b34a19 — drive now judges what nobody ruled on
  DR->>CI: push fix/loop-* to Gitea (webhook count asked, not assumed)
  DR->>DR: open MR on GitLab (local port), stop — never merges
  PU->>RV: 06:50 — 40 min of CI budget for whatever drive pushed
  RV->>CI: Q1 — pipeline on the EXACT sha?
  RV->>RV: Q2 judges passed? · Q3 MR diff == judged diff?
  RV->>RV: YES×3 → merge → forge-sync --apply (never GitHub)
  Note over RV: INDETERMINATE = wait for tomorrow.<br/>No pipeline ≠ nothing failed.
```

Also on the clock, business-loop side: 03:00 the backup itself (launchd
`eu.thisisait.nos.backup.rustfs` — deliberately off the Pulse clock), 04:00 Sun
conductor self-test ceremony, 04:17 audit-chain verify, 04:20 npm-supply-chain,
05:30 authentik-tofu-drift, 06:23 agent-cost tally, 06:40 discovery
contradiction-scan, Sun 07:30 backup-restore drill; every minute the Wing
notify dispatcher, every 15 min alert-relay + inbox reconciler, hourly
breach-deadline scan; 09:00 the mail digest. The loop's three jobs sit
*between* the business jobs and consume their output — which is why the
ordering is part of the contract, and why the loop chain having **no declared
temporal edges** while the KEAP chain has five measured ones is a finding
(doctrine §7), not a style note.

## 4. Identities — the credential diagram

```mermaid
flowchart LR
  subgraph tokens["~/.nos/secrets.yml (0600, minted random — never prefix-derived; runtime-refused if _pw_-shaped)"]
    T1[loop_propose_token<br/>scopes: read + propose]
    T2[loop_judge_token<br/>scopes: read + judge]
    T3[loop_operator_token<br/>scopes: read + forget]
    T4[gitea/gitlab/woodpecker<br/>API tokens]
    T5[GitHub credential —<br/>promote-public.sh ONLY]
  end
  PROP["proposer — the model<br/>(loop-propose spawns it; skills:<br/>weakness-scan, propose)"] --- T1
  DRV["driver / evaluator<br/>tools/loop-pr.py via nos-loop"] --- T2
  OPR((operator)) --- T3
  RVW["reviewer<br/>tools/loop-review.py"] --- T4
  OPR --- T5
  ENG["engine:judge-runner — the ONLY<br/>verdict writer (SQL CHECK on actor;<br/>no endpoint accepts a verdict)"]
  LG[("wing.db loop ledger<br/>WORM chain, replayable")]

  PROP -->|"POST /proposals"| ENG
  DRV -->|"POST /judge (202, async)"| ENG
  OPR -->|"POST /forget — the §4 lift:<br/>held by the one party with<br/>no stake in the verdict"| ENG
  ENG -->|"sole writer, as a byproduct of<br/>a subprocess having exited"| LG
  RVW -->|"holds NO loop scope at all —<br/>reads the ledger file read-only<br/>(questions 2 + 3)"| LG
```

## 5. The nOS loop proper — the organ diagram

```mermaid
flowchart TD
  subgraph CAD["cadence — LIVE"]
    PD["Pulse daemon (30s tick, cap 4)<br/>GET /pulse_jobs/due → spawn →<br/>POST runs + run-finish"]
    WREC["Wing pulse_jobs/pulse_runs<br/>next_fire_at advanced ONLY on finish<br/>= the dead-daemon detector"]
    PD --> WREC
  end
  subgraph KNOW["knowledge — LIVE (two organs, one language)"]
    KEAP["KEAP (Docker, gated_net only)<br/>/agent/v1 loopback :8091"]
    CTX["cortex daemon (host, :8098)<br/>vendored port of KEAP"]
    KJOBS["04:15–05:30 chain: consolidate →<br/>fs-sync → embed → features → lint"]
    CD["corpus-diff 05:30 — do the two<br/>organs still agree?"]
    KJOBS --> KEAP
    KJOBS --> CTX
    KEAP --> CD
    CTX --> CD
  end
  subgraph AG["agents — PARTIAL"]
    BRIDGE["pulse-run-agent.sh (shell bridge):<br/>mutex → OIDC client_credentials →<br/>claude CLI → attributed events"]
    AK["AgentKit runtime (PHP) —<br/>operator-invoked; runner:agent<br/>has NO daemon implementation"]
    BRIDGE -. "the two runtimes never meet<br/>(agentic-night-runbook; TARGET)" .- AK
  end
  subgraph SECP["security pipeline — PARTIAL"]
    SCAN["02:00 LLM scan writes<br/>remediation-queue + scan-state<br/>(UNCOMMITTED; no schema gate)"]
    SNAP["03:30 snapshot → orphan branch<br/>scan-data (plumbing, allow-listed)"]
    DRIFT["06:00 drift-watch: hook →<br/>metric + verdict → notification"]
    DISC["06:40 discovery: queue vs<br/>docker ps — contradictions FILED,<br/>never closed by the reader"]
    SCAN --> SNAP
    SCAN --> DRIFT
    SCAN --> DISC
  end
  subgraph EVN["event → state — LIVE"]
    BONE["Bone :8099 HMAC sink"]
    ROUTE["A9 routing: severity × origin →<br/>wing-inbox / ntfy / mail<br/>(fallback wing-inbox: never silent)"]
    SUPP["repeat-failure suppression:<br/>first failure HIGH, repeats silent,<br/>recovery INFO"]
    REC["inbox reconciler */15 — marks read<br/>only on evidence from the source;<br/>unreadable source = exit 2, not read"]
    RED["red-status.py — the STATE reader;<br/>unreadable = UNKNOWN, never green"]
    BONE --> ROUTE --> SUPP
    REC --> RED
  end
  subgraph BK["backup — LIVE / drill PARTIAL"]
    BKS["03:00 launchd: dumps, volumes,<br/>KEAP via container, AES-256<br/>fail-closed, member-count gate"]
    DRILL["Sun 07:30 restore drill: fetch,<br/>decrypt (key ring), REPLAY —<br/>2 of ~8 source classes only"]
    BKS --> DRILL
  end
  subgraph CVG["converge — LIVE manual / auto DORMANT"]
    MAN["operator: ansible-playbook main.yml<br/>tools/nos-stacks.sh (refuses removals)"]
    AUTO["Woodpecker deploy.yml on dev:<br/>commit footer deploy-tags → HMAC →<br/>Wing DeployTrigger → deploy-from-ci.sh"]
  end
  FACE["face Anatomy app — read-only by<br/>module shape; BFF is an allow-list<br/>PROJECTION (57 secrets stopped here);<br/>one fenced write: run-now {job_id}"]

  CAD --> AG
  CAD --> KNOW
  CAD --> SECP
  CAD --> BK
  WREC --> EVN
  EVN --> FACE
  WREC --> FACE
  CVG -->|"every converge re-registers the<br/>whole job catalog (wing post.yml,<br/>idempotent upsert)"| CAD
```

## 6. The evidence graph — the question→reader→artifact diagram

```mermaid
flowchart LR
  subgraph Q["operator question"]
    q1["what is red RIGHT NOW?"]
    q2["is the loop moving?"]
    q3["what is pending vs exposed?"]
    q4["host vs repo vs origin?"]
    q5["did the agents run, and how did runs end?"]
    q6["do declaration and realm agree?"]
    q7["do the two cortex organs agree?"]
    q8["does the queue contradict docker ps?"]
  end
  q1 --> r1["red-status.py"] --> a1[("wing.db · scan-state.json ·<br/>backup-status.json · loop ledger")]
  q2 --> r2["loop-status.py<br/>--gap / --awaiting"] --> a2[("loop_proposals/verdicts +<br/>git apply --check")]
  q3 --> r3["rem-status.py"] --> a3[("remediation-queue.json")]
  q4 --> r4["estate-status.py"] --> a4[("git refs · resolved config")]
  q5 --> r5["agent-status.py"] --> a5[("agent_sessions · events<br/>joined on actor_action_id")]
  q6 --> r6["identity-status.py"] --> a6[("nos_identities · loopauth ·<br/>realm APIs")]
  q7 --> r7["cortex-drift.py"] --> a7[("files/anatomy/cortex vs ~/keap/src")]
  q8 --> r8["discovery-scan.py"] --> a8[("queue vs live docker ps")]
```

## 7. Missing and weak edges — the full accounts

0. **propose → drive** (`unjudged` fell between the steps) — **CLOSED
   2026-08-21** (`f3b34a19`), exercised the same afternoon: `813d458b` was
   picked up and judged `fail` on the `repo` set. Cost already paid: one
   silent night, plus the day of diagnosis.
1. **`requires_operator` is stamped and consumed by nobody.** The ledger
   marks every `gate-add` proposal `requires_operator=1` (contract §5a:
   "never auto-accepted"), and — verified — neither `loop-pr.py` nor
   `loop-review.py` reads the column. If a gate-add proposal ever passes a
   judge set, the unattended night lands and merges a model-authored gate
   with no operator anywhere in the chain: the "gate you can satisfy by
   editing the gate" class, through the front door. **MISSING refusal edge**;
   cost = the loop's one explicitly-forbidden automation, performed silently.
2. **landed → retired: the queue does not learn from a converge.** The
   scanner is the only retirement writer, twelve rows were already LIVE at
   their fix version, and REM-178 found a recorded fix *below* what runs.
   Cost: the loop re-proposes against fixed weaknesses (each queue edit moves
   the evidence sha, lifting retry ceilings), and the exposure story misleads
   in both directions. `discovery:contradiction-scan` sees part of it and may
   only file. **WEAK** — surfaced, not joined.
3. **The post-merge waits have no standing state.** An MR stuck
   INDETERMINATE (no pipeline, dead webhook) waits politely forever — the
   reviewer is right to wait, but `red-status` reads the ledger and git, not
   open MRs, so day three looks like day one. Same shape one step later:
   nothing counts "merged N days ago, never converged" per item
   (`estate-status` shows aggregate drift only). Cost: last night's class,
   relocated one edge downstream — waiting indistinguishable from done.
4. **The cadence order is enforced by two cron numbers and nothing else.**
   `pulse:loop:{propose,drive,review}` are orphan nodes in
   `state/anatomy-graph.json` — zero `depends_on`, zero temporal edges —
   while the KEAP chain carries five *measured* margins. The
   propose-before-scan ordering (`43a6dd08`) and the drive→review 40-minute
   CI budget are load-bearing and invisible to the margin analyzer. Cost:
   any schedule edit can silently reorder the night; the estate already owns
   the machinery that would catch it.
5. **The withheld-evidence unblock is a human edge with no owner.** The
   02:00 scan dirties `docs/llm/security/*`; the ledger (correctly) withholds
   `rem:` rows until someone commits; `loop-propose` refuses with exit 3 and
   names the fix. Surfaced everywhere, owned nowhere — the deadlock recurs on
   the scan's own cadence. (The 03:30 `scan-data` snapshot commits to an
   orphan branch the ledger does not read — nearby, but not this edge.)
   **WEAK**: cost = the entry half starves on any day the operator forgets.
6. **The security producer is an LLM writing an ungated artifact.** Everything
   downstream — weakness reader, drift watch, rem-status, the loop's own
   entry — consumes `remediation-queue.json`/`scan-state.json`, and no schema
   or cross-field gate validates the write (the reader's freshness
   corroborator catches *some* self-report contradictions — it filed
   `freshness:remediation-queue:not-corroborated` — but that is a spot check,
   not a contract). **WEAK**.
7. **AgentKit and Pulse never meet** (`runner: agent` is schema-only; every
   scheduled ceremony rides the shell bridge, and all but the weekly
   conductor self-test are paused; the bound loop is measured unproven —
   `test_the_bound_agent_loop_is_unproven.py`). Deliberate and documented,
   so **TARGET** rather than defect — but it is the business loop's own
   propose-drive-shaped seam, and it is drawn dashed in doctrine §5.
8. **The restore drill replays 2 of ~8 source classes** (keap-db, wing-db).
   MariaDB/Postgres dumps, volumes, dirs, tofu state, blueprints are fetched
   nightly and never round-tripped; the off-site restic copy has never been
   restore-verified. **PARTIAL**: cost appears exactly once, at the worst
   possible time.

## 8. Edge gates — the first three, in full

1. **The unattended path refuses `requires_operator`** — closes doctrine
   §7.1, the only edge whose absence violates an explicit contract clause.
   Fixture: a passed gate-add proposal in a scratch ledger; assert the driver
   reports it and refuses to land, and the reviewer refuses the MR.
   Retro-verify by removing the refusal and watching a model-authored gate
   sail through.
2. **Every ledger state has an owner** — the generalisation of `f3b34a19`.
   Derive the producible state set from the reader itself (`STATE_GLOSS` /
   `_STATE_ORDER` in `tools/loop-status.py` are literal data) and assert each
   state is either consumed by a named actor (driver, operator surface) or
   declared terminal with a reason. A new state added without an owner goes
   red on the day it is added, not on the first unattended night.
3. **The cadence chain is declared, and its margins are measured** — closes
   doctrine §7.4 with machinery that already exists: declare `depends_on` on
   `loop:drive` (→ propose) and `loop:review` (→ drive) plus the
   propose-before-scan constraint, and let `anatomy-graph-gen` +
   `test_anatomy_graph_is_sound` + the margin analyzer treat the loop chain
   exactly as they treat the KEAP chain. Two manifest lines and one gate
   extension; the night's order stops being two cron numbers.

The standing-state reader for doctrine §7.3 (unjudged/indeterminate/unconverged
items older than one cadence period reaching `red-status`) is the right
*fourth* move — it is a reader plus a fixture gate, and it converts every
remaining wait in the §2 diagram from an event into a state.

## 9. Toward a derived ontology

The doctrine file is hand-drawn and STATIC on purpose — the sequence needed
stating once, by a person, with the false edges left out. But most of what it
draws is already data, and the estate already owns the derivation pattern:
`tools/anatomy-graph-gen.py` → `state/anatomy-graph.json` (213 nodes, 252
edges, five kinds: `data`, `trigger`, `temporal`, `mutex`, `governed_by`),
gated by `test_anatomy_graph_is_sound.py`, rendered by the face's
`GraphView.svelte`, and projected to the public apex only through the signed
ruling (`files/anatomy/apex/ruling.yml`). The loop's steps are already nodes
there; what the unattended night's gap looks like in that artifact is precise:
**three `pulse:loop:*` nodes with no edges between them.**

For the visualisation step to be mechanical rather than a rewrite, the graph
needs two edge kinds the doctrine currently carries as prose:

- **`handoff`** — producer → artifact → consumer, e.g. `pulse:loop:propose →
  table:loop_proposals → pulse:loop:drive`, `pulse:loop:drive →
  repo:gitlab-mr → pulse:loop:review`. Derivable today for the loop: the
  states from `STATE_GLOSS`, the forge coordinates from `FORGE_KEYS`, the
  artifact names from the tools' own module constants — all literal data.
- **`identity`** — actor → credential → scope. Derivable today:
  `loopauth.IDENTITIES` is a literal dict; `authentik_agent_clients` and
  `nos_identities` are committed YAML; the reviewer/driver token keys are
  module constants. §4's diagram becomes a projection.

The evidence graph (§6, question → reader → artifact) is the least mechanical
— the join lives in the readers' docstrings — and can stay curated the way
`REPO_SURFACES` already is: each node pinned to the code that touches it.

This belongs **in** `anatomy-graph-gen`, not beside it: same address space,
same byte-stable artifact, same gate, same renderer, same apex ruling
(default WITHHELD, so nothing here leaks by default). When those edges become
data, the diagrams above become checkable against the graph — and the doctrine
file shrinks to the prose and the refusals, which is what doctrine is for.
