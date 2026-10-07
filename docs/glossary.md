<!-- GENERATED — do not edit. Source: state/genome/lexicon.yml (via tools/genome-codegen.py). Gate: tests/anatomy/test_lexicon_holds.py -->
# Glossary

Each word in nOS means one thing. The body levels run smallest to largest:
genome → cell → tissue → organ → organ system → organism → habitat.

## Levels

- **genome** (genome) — The declared facts every part of nOS inherits, kept in state/genome/. Not: law, definition.
  Counter-example: a cell's system.md (its definition, not something every part inherits).
- **gene** (genome) — One declared kind of entity in the genome. Not: plugin.
  Counter-example: one DataTable row (data a gene shapes, not a gene).
- **cell** (cell) — One model in one specialization; in code it is called an agent. Not: sense, stem cell, AWS/Slack cell (an isolated full-stack replica).
  Counter-example: an immune indicator (a sense).
- **stem cell** (cell) — A model that has not yet differentiated into one specialization. Not: cell.
  Counter-example: jeff, a broad assistant that still has one charter (a cell).
- **definition** (cell) — One cell's own prompt and tool allow-list, versioned and hashed. Not: genome, law.
  Counter-example: the model pin in agent.yml (which model runs the cell, not its prompt or allow-list).
- **tissue** (tissue) — The transplantable pack of one specialization's cells with their skills, tables and services. Not: plugin, organ. Mechanism: bounded context (domain-driven design).
  Counter-example: a plugin (wiring, not a specialization).
- **organ** (organ) — One service or host daemon with one job; one row in state/manifest.yml. Not: organ system, cell, digest.
  Counter-example: a Pulse job (a reflex of the Pulse organ).
- **organ system** (organ system) — A public group of organs serving one function; the apex page shows thirteen. Its source is the apex ruling's `organ_systems:` key. Not: organ, organism.
  Counter-example: a compose stack such as iiab (a deployment group, not a public function).
- **organism** (organism) — One nOS install on one machine, all its organ systems together. Not: habitat, anatomy.
  Counter-example: the anatomy graph (a drawing of the organism, not the organism).
- **habitat** (habitat) — The machine and what lives beside the organism: its software by origin (self / symbiont / habitat). Software of origin habitat belongs to the machine's owner, and nOS never installs or touches it. Ruled 2026-10-06: the git forges nOS hosts itself are not habitat (they are organ jobs); the LLM backends nOS's cells call are habitat, third-party processors beside it. Not: organism, symbiont.
  Counter-example: the Gitea or GitLab nOS hosts (organ jobs, not habitat).

## Across levels

- **self** — Software nOS calls, pins and updates itself, vendor formulae included; a self organ is one of nOS's own parts. Provisional — a deeper sense (versions as a lineage, old ones die, new ones are born) is being designed, roadmap row self-definition. Not: declared, symbiont.
  Counter-example: OpenHuman, declared and installed by nOS but neither pinned nor updated by it (its vendor updates it: a symbiont).
- **symbiont** — Declared foreign software that lives beside nOS and is updated by its own vendor. Not: self, habitat.
  Counter-example: a personal Homebrew package (habitat: the machine owner's, never installed by nOS).
- **declared** — On the list nOS generates from its declarations; the immune system tolerates it, and anything undeclared is a signal. Not: self.
  Counter-example: a launchd job the operator loaded by hand (undeclared until a declaration explains it, however harmless).
- **sense** — A reader or judge that only reads; an immune indicator is a sense with an indicator contract. Not: cell, limb.
  Counter-example: tools/genome-codegen.py (it writes the glossary; only its --check reads).
- **limb** — A tool that acts. Not: sense, side. Mechanism: port / adapter (hexagonal architecture).
  Counter-example: an agent tool grant whose every scope is .read (a sense).
- **memory** — What nOS has learned, kept in KEAP; RAM stays plain English. Not: cortex, verdicts, stores.
  Counter-example: Wing's audit ledger (a record of what happened, not what nOS learned).
- **verdicts** — The log of what each sense reported and what the operator judged. Not: memory.
  Counter-example: KEAP (memory: what nOS learned, not what a sense reported).
- **law** — The rules in force, kept in ssot/doctrine/ and kept apart from the genome. Not: genome, definition.
  Counter-example: the genome's entity schema (declared facts, not rules in force).
- **reflex** — An automatic, scheduled response of an organ; Pulse runs each one on its clock. Not: Pulse, heartbeat, organ. Mechanism: a scheduled job (cron); where it restarts what failed, a supervisor (Erlang/OTP).
  Counter-example: a launchd daemon (an organ, not a scheduled response).
- **heartbeat** — A periodic signal that proves something is still alive. Not: Pulse. Mechanism: a liveness signal; monitor / link (Erlang/OTP).
  Counter-example: a health check (asked from outside; a heartbeat is sent from inside on a clock).
- **nervous system** — The path events take to the operator, from events to the Wing inbox to ntfy or mail. Not: converge.
  Counter-example: a converge (one playbook run, not the path events take).
- **twin** — The second Mac. Not: mirror-parity.
  Counter-example: a coexistence track (a second copy of one service on the same Mac).
- **plugin** — A plugin.yml declaring how one service is wired to the others (SSO, dashboards, jobs). Not: tissue, gene.
  Counter-example: an apps/<name>.yml manifest app (it deploys a service; a plugin only wires one).
- **anatomy** — The structure of one organism drawn as a graph. Not: body plan.
  Counter-example: state/body-plan.json (the anatomy projected onto levels, not the graph).
- **body plan** — The anatomy projected onto the levels above; each graph kind's level is read from state/genome/lexicon.yml. Not: anatomy.
  Counter-example: state/anatomy-graph.json (the anatomy itself; the body plan is its projection).
- **appendage** — An organ attached through one declared joint (a cross-repo contract: spec, fixture, symmetric gates), with its own code and licence, which no core organ depends on or imports; the organism survives its loss. A property of an organ, not a level. Not: tissue, symbiont, organ system, twin, limb, KEAP.
  Counter-example: KEAP: has a cross-repo contract and the core depends on it.

## Plumbing (hidden from the body plan)

- **internal** — Real plumbing that is not a body part; the body plan hides it by default. Not: organ, sense.
  Counter-example: the Authentik service (an organ); only an SSO client object inside it is internal.

## Procedures

- **digest** — The intake process that turns outside data into DataTable rows; mail digest and hash digest are allowed compounds. Not: organ.
  Counter-example: a sha256 digest (a hash, an allowed compound, not the intake).
- **converge** — One playbook run that moves the source into the running system. Not: nervous system. Mechanism: a reconcile loop (a Kubernetes operator) — declared against observed; it does not heal.
  Counter-example: a hand `docker compose up` (it moves one container, not the declared source).
- **imprint** — The one page a newborn model reads first. Not: cell.
  Counter-example: CLAUDE.md (the brief for an assistant working in the repo, not a newborn's first page).
- **apgar** — The score of a newborn model on the questions its imprint should answer. Not: cell.
  Counter-example: a pytest gate (it scores the repo, not a newborn model's answers).

## Proper names (one job each)

- **Bone** — The host API bridge between the runs and the records.
- **Wing** — The host dashboard and audit ledger.
- **Pulse** — The scheduler that runs every scheduled job. Not: heartbeat.
- **Cortex** — The reasoning machinery (the cortex daemon, cortex-lang and Wing's executor); it is not KEAP. Not: memory, KEAP.
  Transitional debt (roadmap row `cortex-corpus-ruling`): The store inside Cortex is transitional: the Cortex corpus (a replica of memory held for the onto1 digest) with its libsql store, fs-sync, embeddings and ANN index. KEAP is memory; the store leaves Cortex after v0.17, and no new store code lands here.
- **Face** — The web desktop.
- **Ears** — The speech organ, which hears and speaks.
- **Apex** — The public page that shows the organ systems to strangers.
- **KEAP** — The knowledge store where nOS keeps its memory. Not: Cortex.
- **AgentKit** — The audit-first runtime inside Wing that runs the cells (agents). Not: cell, tissue, Wing.
  Counter-example: a cell such as jeff (AgentKit runs it; the cell is the model in its specialization).

## Left alone, or retired

- **iiab** — An old compose stack name, still used by about two dozen services.
- `files/anatomy/` — The source tree of nOS's own parts; the directory name stays.
- `tests/anatomy/` — The offline gates; the directory name stays.
- `bone_* / WING_* / eu.thisisait.nos.*` — Config, environment and launchd label prefixes; they stay as spelled.
- `nos.host.*` — KEAP anchors for host-native organs; they stay.
- **pulse (graph kind)** — The anatomy graph's kind name for a reflex (one scheduled job), not the Pulse organ; the kind name stays.
- `heartbeat_* / mail_digest_*` — Config keys for the fleet heartbeat and the daily mail digest; they stay.
- **brain** — Not used. KEAP is memory, the host parts are organs, the Wing API token is a flat token.
- **spine** — Not a body-plan word; KEAP's ontology spine is upstream's word, and "The Spine" stays an apex title.
- **organelle** — Not used. A genome entity kind is a gene; a plugin is a plugin.

## Retired senses (old use → what to say now)

- DNA of the inner organism (prompts, skills, CLAUDE.md, allow-lists) → law for the shared parts; definition for one cell's prompt and allow-list
- an immune indicator called a cell → sense (an indicator is a sense with an indicator contract)
- the `dna` field of the indicator contract → definition
- praxis pack / backoffice pack → tissue
- plugins as connective tissue, tendons or vessels → plugin wiring
- a public apex group called an organ → organ system
- organ meaning host-native (runs under launchd or systemd) → the stack axis: stack is null
- a model called an organ → cell
- organ meaning nOS's own parts as opposed to vendor software → self organ
- host, as the third owner class of software → habitat
- self meaning the immune system's tolerated set → declared
- limb as the apex page's left/right/core column key → side
- The Memory, the apex group of databases → The Stores
- memory meaning the immune system's verdict log → verdicts
- Pulse called the heartbeat → Pulse, which is the scheduler
- the playbook called the nervous system → converge
- twin for two lists that must stay equal (twin-parity) → mirror-parity
- a second kind-to-level map beside the lexicon → the graph_kind names in state/genome/lexicon.yml
- the digest organ, the stomach → digest
- bones-and-wings for the host organs together → the host organs
- Cortex remembers (holds memory) as well as reasons → Cortex reasons; KEAP is memory
- cortex-query, recall from KEAP → keap-recall
- KEAP called the cortex (a cortex store, cortex objects) → KEAP, where nOS keeps its memory
- brain for KEAP, the four host parts or the Wing API token → memory / organs / flat token
- a reader called the spinal cord → sense
- organelle for a genome entity kind → gene
- organelle for a plugin → plugin
- organelle for a digest importer (hydrator) → digest importer
