---
in_force: true
ruled: 2026-10-04
row: immune-system
gates: []
last_reviewed: 2026-10-06
review_every_days: 31
---
# The immune system — indicators as senses

> Words per `state/genome/lexicon.yml`.
> nOS is an organism; its models, defined by their prompts and permissions, are
> its cells. Detection is a population of senses that run on a clock, report to
> the nervous system, age and die. Threat side: [session-threat-model.md](session-threat-model.md).

## 1. The anatomy it maps onto

| Body | nOS today |
|---|---|
| scheduler | Pulse: runs each patrol and crawler step as a reflex on its clock |
| nervous system | Bone events → Wing inbox → ntfy/mail; `tools/red-status.py` is the first reader |
| senses | the indicators of §3, each filling the indicator contract (§2) |
| declared | `state/manifest.yml`, the anatomy-graph daemons, the Pulse trees, the converge's image record |
| skin | the edge (Traefik + forward_auth), Santa exec telemetry, the pre-push border |
| law and definitions | law: the shared parts every model inherits (skills, CLAUDE.md, `ssot/doctrine/`); definition: one cell's prompt and tool allow-list |

The declared set is **generated** from declarations, never hand-listed. Anything
running that no declaration explains is undeclared (`undeclared-status`, `workload-digest-status`).

Software on the machine classed `symbiont` or `habitat` in `software_owner` is
**tolerated**: declared, not of the organism, living beside it. A sense
neither attacks it nor counts it as nOS's own.

## 2. The indicator contract

Every indicator — deterministic probe or model — declares the same fields.
A detector that cannot fill one in is not an indicator yet.

| Field | Meaning |
|---|---|
| `kind` | sentinel · patrol · crawler · checkpoint · regulator · apoptosis · verdicts (§3) |
| `antigen` | what it recognises, stated as a deterministic predicate first; a model may refine, never be the only judge |
| `receptor` | what it reads; read-only, always |
| `effector` | what it may do: `report` by default; anything stronger (quarantine, stop, refuse) is an operator-approved escalation named in its contract |
| `signal` | where it reports and at which severity (the A9 routing: wing-inbox / ntfy / mail) |
| `heartbeat` | how often the nervous system must hear from it; silence past it is itself a red |
| `lifespan` | for crawlers: a TTL or step budget, after which it is retired |
| `tolerance` | how it avoids attacking what is declared: the generated allow-list it consults |
| `verdicts` | where each verdict is recorded for calibration (JSONL, no content, no secrets) |
| `definition` | for an indicator run by a model: its prompt and allow-list file, hashed in every record |

## 3. Indicator kinds

- **Sentinel** — fixed place, always on, read by red-status: undeclared-status,
  workload-digest-status, santa-status, identity-status.
- **Patrol** — Pulse sweeps on a schedule: discovery contradiction-scan,
  gitleaks nightly, npm IOC scan, tofu drift plan, security drift watch.
- **Checkpoint** — at a border, on crossing: `tools/prepush-score.py` before
  every push; CodeRabbit + the checklist at the dev→master PR.
- **Crawler** — stateful: holds a cursor, Pulse nudges it one step further each
  tick (a slice of git history, KEAP records, logs, agent transcripts), and it
  **dies** when its lifespan is spent. Built for the slow, wide search no
  sweep can afford in one run: instructions planted in data, dormant triggers.
- **Apoptosis** — retires crawlers past their lifespan and any indicator whose
  definition no longer matches its recorded hash. An indicator no one can kill
  is a tumour.
- **Regulator** — measures each indicator's false-alarm rate from the verdicts
  and demotes a noisy one to advisory. It never silences: a gate that cries wolf
  is disarmed by its own users (the prefix gate that flapped 3/5, 2026-08-31),
  so autoimmunity is a failure of the system, not of the operator's patience.
- **Verdicts** — the log of what fired, what the operator judged, and which
  weights and thresholds that teaches. The audit chain keeps it tamper-evident.

## 4. Rules

1. **Absence is a signal.** Every indicator has a heartbeat; a killed or
   stalled one turns red by its silence. This is the one defence that survives
   an attacker who can rewrite an indicator (§6).
2. **Deterministic antigen first, model second.** A model's score is shown
   beside the evidence, never instead of it; a model scoring 0 against strong
   evidence is no score (prepush-score, 2026-10-04).
3. **Report is the default effector.** Escalation to stop/refuse/quarantine is
   operator consent, declared per indicator, dry-run first.
4. **Definitions and law are versioned.** A model's prompt and permissions are
   committed, hashed in every record, and reviewed like code; a change to a
   definition or to the law is the strongest pre-push signal.
5. **Indicators die.** Crawlers carry a lifespan; apoptosis enforces it.
6. **Readers only read.** An indicator never writes the state it judges.

## 5. Today's population

| Indicator | Kind | Heartbeat | Lifespan | Regulated |
|---|---|---|---|---|
| undeclared-status, workload-digest-status, santa-status | sentinel | red-status run | — | no |
| discovery, gitleaks, npm-ioc, tofu-drift, security-drift | patrol | Pulse schedule | — | no |
| prepush-score, CodeRabbit + checklist | checkpoint | per push / PR | — | no |
| audit-chain-verify | verdicts integrity | nightly | — | — |
| crawler | — | **none exists** | — | — |
| apoptosis, regulator | — | **none exists** | — | — |

The gaps are the roadmap children of `immune-system`: an indicator registry
with the contract as schema, heartbeats for every indicator, the first crawler,
apoptosis, and the regulator.

## 6. Ceilings

Every indicator runs as the operator's user today, so a compromised session can
rewrite or stop any of them — the heartbeat (§4.1) turns that into a signal
but not a defence. The hard boundary is moving indicators out of the session's
reach: the separate-user child of `operator-session-threat-model`, and the
containerized core (roadmap epic `containerized-core`), where an indicator can
run in a container the session cannot write into.

## 7. Review

Monthly, with the session threat model: walk §5, add new indicators, record what
the regulator demoted, move `last_reviewed`. `tools/red-status.py` names this
file when the date runs out.
