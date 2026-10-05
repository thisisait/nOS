---
last_reviewed: 2026-10-04
review_every_days: 31
---
# The immune system — indicators as cells

> Doctrine, 2026-10-04 (roadmap epic `immune-system`). Operator's framing: nOS is
> an organism; the models running inside it, defined by their prompts,
> descriptions and permissions, are the organs of a first organism living
> within it. Detection is not a list of scripts but a population of cells that
> circulate, report to the nervous system, age and die.
> Threat side: [session-threat-model.md](session-threat-model.md).

## 1. The anatomy it maps onto

| Body | nOS today |
|---|---|
| bloodstream | Pulse: the scheduler that carries a cell to where it works |
| nervous system | Bone events → Wing inbox → ntfy/mail; `tools/red-status.py` is the spinal cord |
| self | declared state: `state/manifest.yml`, the anatomy-graph daemons, the Pulse trees, the converge's image record |
| skin | the edge (Traefik + forward_auth), Santa exec telemetry, the pre-push border |
| DNA of the inner organism | agent prompts, skills, CLAUDE.md, tool allow-lists: what a model is and may do |

Self is **generated** from declarations, never hand-listed. Anything running
that no declaration explains is non-self (`undeclared-status`, `digest-status`).

## 2. The cell contract

Every indicator — deterministic probe or model — declares the same fields.
A detector that cannot fill one in is not a cell yet.

| Field | Meaning |
|---|---|
| `kind` | sentinel · patrol · crawler · checkpoint · regulator · apoptosis · memory (§3) |
| `antigen` | what it recognises, stated as a deterministic predicate first; a model may refine, never be the only judge |
| `receptor` | what it reads; read-only, always |
| `effector` | what it may do: `report` by default; anything stronger (quarantine, stop, refuse) is an operator-approved escalation named in the cell |
| `signal` | where it reports and at which severity (the A9 routing: wing-inbox / ntfy / mail) |
| `heartbeat` | how often the nervous system must hear from it; silence past it is itself a red |
| `lifespan` | for crawlers: a TTL or step budget, after which it is retired |
| `tolerance` | how it avoids attacking self: the generated allow-list it consults |
| `memory` | where each verdict is recorded for calibration (JSONL, no content, no secrets) |
| `dna` | for model cells: the prompt/definition file, hashed in every record |

## 3. Cell kinds

- **Sentinel** — fixed place, always on, read by red-status: undeclared-status,
  digest-status, santa-status, identity-status.
- **Patrol** — Pulse sweeps on a schedule: discovery contradiction-scan,
  gitleaks nightly, npm IOC scan, tofu drift plan, security drift watch.
- **Checkpoint** — at a border, on crossing: `tools/prepush-score.py` before
  every push; CodeRabbit + the checklist at the dev→master PR.
- **Crawler** — stateful: holds a cursor, Pulse nudges it one step further each
  tick (a slice of git history, KEAP records, logs, agent transcripts), and it
  **dies** when its lifespan is spent. Built for the slow, wide search no
  sweep can afford in one run: instructions planted in data, dormant triggers.
- **Apoptosis** — retires crawlers past their lifespan and any cell whose DNA
  no longer matches its recorded hash. A cell no one can kill is a tumour.
- **Regulator** — measures each cell's false-alarm rate from memory and
  demotes a noisy cell to advisory. It never silences: a gate that cries wolf
  is disarmed by its own users (the prefix gate that flapped 3/5, 2026-08-31),
  so autoimmunity is a failure of the system, not of the operator's patience.
- **Memory** — the verdict log: what fired, what the operator judged, which
  weights and thresholds that teaches. The audit chain keeps it tamper-evident.

## 4. Rules

1. **Absence is a signal.** Every cell has a heartbeat; a killed or stalled
   cell turns red by its silence. This is the one defence that survives an
   attacker who can rewrite a cell (§6).
2. **Deterministic antigen first, model second.** A model's score is shown
   beside the evidence, never instead of it; a model scoring 0 against strong
   evidence is no score (prepush-score, 2026-10-04).
3. **Report is the default effector.** Escalation to stop/refuse/quarantine is
   operator consent, declared per cell, dry-run first.
4. **DNA is versioned.** A model cell's prompt and permissions are committed,
   hashed in every record, and reviewed like code; a change to DNA is the
   strongest pre-push signal.
5. **Cells die.** Crawlers carry a lifespan; apoptosis enforces it.
6. **Readers only read.** A cell never writes the state it judges.

## 5. Today's population

| Cell | Kind | Heartbeat | Lifespan | Regulated |
|---|---|---|---|---|
| undeclared-status, digest-status, santa-status | sentinel | red-status run | — | no |
| discovery, gitleaks, npm-ioc, tofu-drift, security-drift | patrol | Pulse schedule | — | no |
| prepush-score, CodeRabbit + checklist | checkpoint | per push / PR | — | no |
| audit-chain-verify | memory integrity | nightly | — | — |
| crawler | — | **none exists** | — | — |
| apoptosis, regulator | — | **none exists** | — | — |

The gaps are the roadmap children of `immune-system`: a cell registry with the
contract as schema, heartbeats for every cell, the first crawler, apoptosis,
and the regulator.

## 6. Ceilings

Every cell runs as the operator's user today, so a compromised session can
rewrite or stop any of them — the heartbeat (§4.1) turns that into a signal
but not a defence. The hard boundary is moving cells out of the session's
reach: the separate-user child of `operator-session-threat-model`, and the
containerized core (roadmap epic `containerized-core`), where a cell can run
in a container the session cannot write into.

## 7. Review

Monthly, with the session threat model: walk §5, add new cells, record what the
regulator demoted, move `last_reviewed`. `tools/red-status.py` names this file
when the date runs out.
