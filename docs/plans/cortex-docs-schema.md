# Cortex docs schema — node kinds and the ingestion contract

Status: **design, decided.** Written 2026-07-26 on `feat/cortex-docs-knowledge`.
This is the Design phase of `cortex-s1-docs-as-knowledge`; Build renders it.
Read `docs/plans/cortex-self-core.md` §1–§3 and `docs/hidden_fees/04` first —
this plan assumes the boundary rule (nOS holds the runtime) and the recall rule
(*confident wrongness outranks honest thinness*) as settled.

The self-model producer `files/anatomy/scripts/keap_selfmodel_gen.py --schema
slug` already emits the estate as taxonomy nodes (`nos.<stack>.<system>`) plus
fs-sync cards, and already reads `docs/systems/<svc>/SKILLS.md` into `type:
skill` cards. This document does not invent a corpus. It says how the rest of
the estate's prose — READMEs, gotchas, devlogs, a day's work — becomes nodes on
that same tree, so a stranger can point their own docs at it and get a navigable
universe instead of a pile of markdown.

The measure of success is not "the docs are ingested." It is: **a stranger reads
one of our doc files and can tell, without a spec, which kind each block is and
where it will land.**

---

## 1. The kinds — four, by what the reader DOES

A kind is not a topic or a folder. It is the **action the reader takes with the
node**. That is the only axis recall can serve, and it is the only axis a
stranger can apply to their own text without training.

| kind | the reader… | the discriminating test | one example from this repo |
| --- | --- | --- | --- |
| **skill** | **invokes** it | *Can an agent execute this by reading the card alone?* Names a call — endpoint, command, UI action — and carries a **Trigger** (recall phrases). | `create-repo` in `docs/systems/gitea/SKILLS.md` |
| **hint** | **watches for, then acts** | *Is it true only UNDER a condition?* Leads with a situation (`When…` / `If…`) and a do-or-avoid. Unconditional ⇒ it is a note. | "Run removals from a terminal OUTSIDE the IDE" (CLAUDE.md gotchas) |
| **note** | **understands** | *Is it a standing claim, true or false about the estate?* Context-free prose that describes or explains. The default. | a system's `en` description; most of a README |
| **snippet** | **copies** | *Is it correct only byte-for-byte?* A verbatim artefact with a format/language and no trigger — reformatting it breaks it. | a compose fragment, an env line, a one-liner |

Four is right, and the justification is the partition, not the count: every
useful block does exactly one of **invoke / watch-then-act / understand / copy**.
Collapse any pair and you lose a query class recall must answer —
*"how do I X"* (skill), *"what do I do when Y"* (hint), *"what is Z / why"*
(note), *"give me the exact text for W"* (snippet). A fifth kind would have to
name a fifth verb; there isn't one.

**The two fragile boundaries, stated so they are not misused within a week:**

- **hint vs note** — both are prose. The wall is the **condition**. A hint that
  states no situation is a mis-filed note; a note that hides an `If…` is a
  mis-filed hint. This is the boundary the operator's goal depends on: the
  *conditional relations* of a process are exactly its hints (§6).
- **skill vs snippet** — both can contain a command. The wall is **trigger +
  semantics vs verbatim bytes**. A skill answers a question and is invoked; a
  snippet is inert payload a skill or note refers to. A snippet with a Trigger
  is a skill wearing a code block; a skill without one is a snippet that will
  never be found.

A kind whose boundary you cannot state in one sentence will be misused. Each of
the four fits in the "discriminating test" column above; that column is the
contract, not decoration.

---

## 2. How a kind is declared — reuse three signals already in the docs

**Decision: frontmatter `type:` at file level; three already-universal signals
at block level; no manifest, no new heading dialect.** A stranger annotates
nothing to start and adds one line to sharpen.

Every signal below is already true of the corpus. We add **one** convention, and
it is a mirror image of one that already exists.

**File level.** A leading frontmatter block — flat scalars, `---`-fenced, the
first bytes of the file — sets the file's kind:

```
---
type: skill        # skill | hint | note | snippet
title: create-repo
---
```

This is the *exact* block the generator already writes for skill cards
(`render_skill_card`); KEAP's fs-sync already parses it and treats a single
non-key line as body. **A file with no `type:` is a `note`** — the safe,
unconditional default, so plain markdown ingests untouched and you annotate only
when you mean something sharper than "understand this."

**Block level** — for the "day's work" file that is many kinds at once, the kind
of a section under a heading is read from a signal that is *already present in
well-written markdown*:

| signal (already in the docs) | kind of that section |
| --- | --- |
| a fenced code block ` ```lang ` | **snippet** (the language IS the format tag) |
| a `**Trigger:**` bold-lead line | **skill** |
| a `**When …:**` / `**If …:**` bold-lead line | **hint** |
| anything else under a heading | **note** |

Three of those four we already emit or already have (fenced code is universal;
`**Trigger:**` is the SKILLS.md convention the recall gate is built from). The
**one** addition is `**When:**`/`**If:**` as the hint marker — deliberately the
same shape as `**Trigger:**`, so anyone who has seen a skill card can write a
hint without being told the rule.

Rejected: **heading-name conventions** (`## Skill: …`) drift the moment someone
renames a heading, and collide with prose; **a separate manifest** is a second
file to keep in sync and the first thing that goes stale (it is fee 04 in a new
costume). The declaration must live in the file it describes.

---

## 3. Anchoring — one tree, the estate's; no parallel doc subtree

**Decision: a doc node hangs off the node it is ABOUT. There is no `nos.docs.*`
mirror.** The estate self-model already puts everything under `nos`
(`nos.<stack>.<system>`); docs enrich those nodes, they do not shadow them.

- A doc about a **service** anchors at that service: `[[nos.<stack>.<system>]]` —
  the wikilink cards already use. Its skills/hints/snippets become child nodes
  or relations of that service node.
- A doc about a **process** that spans services (release flow, blank reset)
  anchors at the **narrowest node that contains every service it touches** — the
  owning stack (`nos.<stack>.<process-slug>`) or `nos.<process-slug>` when it is
  estate-wide. Its steps are hint/skill nodes anchored to the services they act
  on, tied to the process node by relations (§6).

A parallel doc tree is refused for a measured reason: the nine near-identical
`_stack.md` documents that became nine near-identical vectors and won unrelated
physics queries (`hidden_fees/04`, and the generator's own header). A
`nos.docs.gitea` node sitting beside `nos.devops.gitea` is that failure by
construction — two homes for one subject, and recall cannot choose. **A doc is
not a place; it is content that lands on a place that already exists.** When no
such place exists (a genuinely new process), you add the process node to the
estate tree at its owning scope — you do not add a doc tree.

This is the choice §6 rests on: because process nodes live *in* the estate tree,
the explorer can select one and its relation edges point at real service nodes.

---

## 4. Provenance — repo · path · commit · blob, in a sidecar, never the body

**Decision: every doc node carries `{repo, path, commit, blob_sha,
generated_at}` in a structured metadata channel, NOT in the embedded markdown
body.** This is what turns the accuracy gap (fee 04) from permanent into
fixable, and it obeys the fee-04 rule that volatile state must never re-embed the
corpus.

- **`repo` + `path`** — stable; change only when a file moves. They make a wrong
  card **traceable to the exact file** a human or agent can open and fix. Today
  the fs-sync id is `fs:<uid>:sha1(relPath)[:16]` — the path is *hashed*, so a
  wrong card points nowhere. Provenance carries the plaintext path back.
- **`commit` + `blob_sha`** — change on every edit. A standing check compares a
  node's stored `commit`/`blob_sha` against the repo's current blob for that
  `path`; a mismatch is **staleness, detected** — the accuracy half of fee 04
  becomes a query, not a hope. Because these churn, they **must** live outside
  the body: put a commit hash in a card and every commit re-embeds the corpus
  (the exact mistake fee 04 forbids for the endpoint probe).
- **`generated_at`** — the ingest timestamp; the time axis §6 animates over.

Provenance is emitted alongside the node into the doc-provenance metadata
(node-keyed, e.g. a `doc_provenance` DataTable / `taxonomy_metadata` row —
Build picks the table), never interleaved with the card the vector index reads.
The card body stays what a query should match; provenance stays what an operator
should trust. Separating them is not neatness — it is the thing that keeps the
corpus from re-embedding on every commit.

---

## 5. Ids — one slug gate, enforced in code, and fee 03 is now closed

**Decision: every id segment a doc mints goes through the one function the
self-model producer already uses — `slug_or_die` — and nothing implements the
charset a second time.** A doc node id is `nos.<…>.<doc-slug>` where `<doc-slug>
= slug_or_die(basename-or-title)`. A doc titled *"7-zip howto"* dies loudly at
generate time, exactly as a service named `2fauth` does — no silent drop into a
nonexistent anchor.

`hidden_fees/03` said the KEAP charset rule (`^[a-z][a-z0-9-]*$`, first char a
LETTER) was **enforced but unpinned**: `slug_or_die` rejects a leading digit,
but no test proved it fires, so the estate was "clean only because nobody named
a service after a number recently." A guard nothing exercises is a guard one
refactor from silent.

**Closed in code, this stage** (not in prose):

- `tests/anatomy/test_selfmodel_slug_charset.py` — runs **every** manifest
  service id and stack (62 + 9, the whole estate) through `slug_or_die` and
  asserts a valid slug; asserts the negative (`2fauth`, `3d-printer` →
  `SystemExit`); asserts the diacritic fold (`Pázny → pazny`) and that the
  produced pattern is `SLUG_RE`. Fee 03's "what closes it" was *"a gate in the
  producer that runs every emitted slug through the KEAP charset and fails on a
  mismatch"* — this is that gate, now pinned.
- `docs/hidden_fees/03` and the README index: **latent → closed 2026-07-26**.

Build inherits the invariant for free: because doc ids route through the same
`slug_or_die`, the gate that pins the self-model also pins docs — there is no
second charset to drift (`hidden_fees/11`). Do not re-derive the rule; call the
function.

---

## 6. What the explorer gets — and which choices are load-bearing

Not built here: the temporal animation, and relation-*type* semantics KEAP does
not yet parse (`render_system_card` notes it drops relation-type prose as body
noise). But the operator's goal — **zoom into one process, see its conditional
relations, on real data, animated over time** — is either allowed or foreclosed
by the four decisions above. These are the load-bearing ones:

- **hint is a distinct, conditional kind (§1).** A process's branches ARE its
  hints (`When the volume is unmounted → …`; `If GitLab cold-inits → wait`). Fold
  hint into note and a process has no conditional edges to draw. This is the
  single choice the animation most depends on.
- **processes anchor in the estate tree, not a doc silo (§3).** The explorer
  selects a real `nos.<stack>.<process>` node; its edges point at the service
  nodes it touches. A parallel `nos.docs.*` would leave the process floating,
  unselectable in the context that gives it meaning.
- **relations go in canonical `relations:[]`, not card bodies (§3/§4).** The
  canonical domain files already carry a `relations` array (empty today).
  Hints emit as typed relations there — `when` / `requires` / `precedes` /
  `blocks` — between the process node and its services. Bodies can't hold a
  relation type; the array can. This is the hook the "conditional relations"
  view reads.
- **provenance is a time-stamped sidecar (§4).** "Animated over time" needs a
  time axis (`generated_at`, `commit` history) that must not re-embed the corpus
  each frame. Volatile-state-out-of-body is what lets the explorer move without
  churning vectors.
- **one id gate (§5).** A silently dropped node is a hole in the animation. The
  gate makes every node addressable and present.

What is deliberately left open, not decided here: relation-type parsing in KEAP,
and the temporal store. The shapes above do not commit to how those are built —
they only guarantee the data will be there in a form they can read.

---

## The worked example — a day's work, so a stranger can copy it

The point of the whole exercise is a file a newcomer imitates. A devlog entry —
one day, many kinds — ingests like this with **one** frontmatter line and the
markdown they would write anyway:

```
---
type: note                 # the file's default; sections below sharpen it
---

[[nos.devops.release-flow]]        # anchors the day's work at the process it advanced

Cut v0.6-beta. The dev→master PR gate needs an admin bypass because a
sole operator can't self-approve.        # ← note (standing claim)

**When** the PR is green but GitHub refuses the merge:      # ← hint (conditional)
use `gh pr merge --rebase --admin`, then re-sync dev to master.

```bash
gh pr merge --rebase --admin            # ← snippet (verbatim, language-tagged)
git checkout dev && git merge --ff-only master && git push
```

**Trigger:** "cut a release", "promote dev to master"      # ← skill (invocable, has recall phrases)
```

Ingested, that one file becomes: a **note** and a **hint** and a **snippet** and
a **skill**, all anchored on `nos.devops.release-flow`, each traceable back to
this file at this commit, each addressable by a slug the gate guarantees. No
manifest, no doc tree, no new syntax the author had to learn — and a process
node the explorer can later zoom into and watch fill in over the days it was
worked. That is the universe; this is the file that seeds it.
