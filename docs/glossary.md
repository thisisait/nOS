<!-- GENERATED — do not edit. Source: state/genome/lexicon.yml (via tools/genome-codegen.py). Gate: tests/anatomy/test_lexicon_holds.py -->
# Glossary

Each word in nOS means one thing. The body levels run smallest to largest:
genome → cell → tissue → organ → organ system → organism → habitat.

## Levels

- **genome** (genome) — The declared facts every part of nOS inherits, kept in state/genome/. Not: law, definition.
- **gene** (genome) — One declared kind of entity in the genome (the word replacing organelle, step 4). Not: plugin.
- **cell** (cell) — One model in one specialization; in code it is called an agent. Not: sense, stem cell.
- **stem cell** (cell) — A model that has not yet differentiated into one specialization. Not: cell.
- **definition** (cell) — One cell's own prompt and tool allow-list, versioned and hashed. Not: genome, law.
- **tissue** (tissue) — The transplantable pack of one specialization's cells with their skills, tables and services. Not: plugin, organ.
- **organ** (organ) — One service or host daemon with one job; one row in state/manifest.yml. Not: organ system, cell, digest.
- **organ system** (organ system) — A public group of organs serving one function; the apex page shows thirteen. Its source is the apex ruling's `organs:` key, whose rename is pending (step 5). Not: organ, organism.
- **organism** (organism) — One nOS install on one machine, all its organ systems together. Not: habitat, anatomy.
- **habitat** (habitat) — The machine and what lives beside the organism: its software by origin (self / symbiont / habitat). Software of origin habitat belongs to the machine's owner, and nOS never installs or touches it. Ruled 2026-10-06: the git forges nOS hosts itself are not habitat (they are organ jobs). Not: organism, symbiont.

## Across levels

- **self** — Software nOS wrote, pins and updates itself; a self organ is one of nOS's own parts. Not: declared, symbiont.
- **symbiont** — Declared foreign software that lives beside nOS and is updated by its own vendor. Not: self, habitat.
- **declared** — On the list nOS generates from its declarations; the immune system tolerates it, and anything undeclared is a signal. Not: self.
- **sense** — A reader or judge that only reads; an immune indicator is a sense with an indicator contract. Not: cell, limb.
- **limb** — A tool that acts. Not: sense, side.
- **memory** — What nOS has learned, kept in KEAP; RAM stays plain English. Not: cortex, verdicts, stores.
- **verdicts** — The log of what each sense reported and what the operator judged. Not: memory.
- **law** — The rules in force, kept in ssot/doctrine/ and kept apart from the genome. Not: genome, definition.
- **reflex** — An automatic, scheduled response of an organ; Pulse runs each one on its clock. Not: Pulse, heartbeat, organ.
- **heartbeat** — A periodic signal that proves something is still alive. Not: Pulse.
- **nervous system** — The path events take to the operator, from events to the Wing inbox to ntfy or mail. Not: converge.
- **twin** — The second Mac. Not: mirror-parity.
- **plugin** — A plugin.yml declaring how one service is wired to the others (SSO, dashboards, jobs). Not: tissue, gene.
- **anatomy** — The structure of one organism drawn as a graph. Not: body plan.
- **body plan** — The anatomy projected onto the levels above; each graph kind's level is read from state/genome/lexicon.yml. Not: anatomy.

## Plumbing (hidden from the body plan)

- **internal** — Real plumbing that is not a body part; the body plan hides it by default. Not: organ, sense.

## Procedures

- **digest** — The intake process that turns outside data into DataTable rows; mail digest and hash digest are allowed compounds. Not: organ.
- **converge** — One playbook run that moves the source into the running system. Not: nervous system.
- **imprint** — The one page a newborn model reads first. Not: cell.
- **apgar** — The score of a newborn model on the questions its imprint should answer. Not: cell.

## Proper names (one job each)

- **Bone** — The host API bridge between the runs and the records.
- **Wing** — The host dashboard and audit ledger.
- **Pulse** — The scheduler that runs every scheduled job. Not: heartbeat.
- **Cortex** — The reasoning machinery (the cortex daemon, cortex-lang and Wing's executor); it is not KEAP. Not: memory, KEAP.
- **Face** — The web desktop.
- **Ears** — The speech organ, which hears and speaks.
- **Apex** — The public page that shows the organ systems to strangers.
- **KEAP** — The knowledge store where nOS keeps its memory. Not: Cortex.

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
- limb as the apex page's left/right/core column key → side (step 5)
- The Memory, the apex group of databases → The Stores (step 5)
- memory meaning the immune system's verdict log → verdicts
- Pulse called the heartbeat → Pulse, which is the scheduler
- the playbook called the nervous system → converge
- twin for two lists that must stay equal (twin-parity) → mirror-parity
- a second kind-to-level map beside the lexicon → the graph_kind names in state/genome/lexicon.yml
- the digest organ, the stomach → digest
- cortex-query, recall from KEAP → keap-recall (step 3)
- brain for KEAP, the four host parts or the Wing API token → memory / organs / flat token
- a reader called the spinal cord → sense
- organelle for a genome entity kind → gene (step 4)
- organelle for a plugin → plugin
