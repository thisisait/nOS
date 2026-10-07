# KEAP holistic coherence review — Fable pass (2026-07-14)

Whole-map read of `knowledge/canonical/` (107 domain files, 1577 nodes). Verdict:
the corpus is **already high quality** — even the shortest descriptions (120+ chars)
are dense and boundary-carving, and the "The study of …" openers I initially
flagged as templatey turned out to be substantial, legitimate field definitions
(300–400+ chars), not stubs. The Czech is broadly clean: the automated Slovak-letter
hits were all proper nouns (Kähler), and the "colloquial" hits were correct standard
Czech. So this was a **surgical** pass, not a rewrite: 6 files touched, 9 edits.

## What I changed, by theme

### 1. Factual cross-reference errors (3 edits — highest value)
`01-natural-sciences/01.01.json` briefs linked prose to the **wrong sibling seed
node**. The lint gate cannot catch this (it deliberately can't see seed ids), so it
was invisible to the pipeline:

- `01.01` and `01.01.01`: prose *"revises/corrects the classical picture of space and
  time at high speed and strong gravity"* linked to `[[01.01.05]]` — but `01.01.05`
  is **Nuclear Physics**. Relativity is `01.01.04`. Fixed both → `[[01.01.04]]`.
- `01.01.02`: prose *"whose Standard Model is built on quantum field theory"* linked
  to `[[01.01.07]]` — but `01.01.07` is **Astrophysics**. Particle Physics is
  `01.01.06`. Fixed → `[[01.01.06]]`.

Verified against `src/game/data/taxonomy.ts`: 01.01.04 = Relativity, 01.01.06 =
Particle Physics are real seed ids, and `knowledge/lint.mjs` does not validate
crossref existence, so these render correctly.

### 2. Missing Czech on high-visibility container/root nodes (6 edits)
328 nodes lack `cs`, but 322 are deep L4 leaves in the big physics/math/bio files —
mass-translating those is high-risk and out of scope for a curated pass (see
PROPOSED). I translated the **6 nodes at L2/L3** that were missing `cs`, because
these are the prominent index/root nodes a reader hits first:

- `01.01.11` Quantum Gravity & Unification, `01.01.11.06` Emergent & Entropic Gravity,
  `01.01.11.17` Swampland Program (conjecture proper-names kept in English, as the
  `en` does and as is standard in Czech physics writing).
- `01.02.11` Chemical Disciplines, `01.03.11` Biological Disciplines,
  `02.01.04` Mathematical Disciplines (MSC2020).

All are full mirrors, no Cyrillic, within length bounds.

### 3. Truncated Czech mirrors completed (3 edits)
Three `seed-override` nodes had correct-but-incomplete `cs` that dropped clauses
present in `en` (cs/en length ratio ≈ 0.48):

- `04.01.04` Clinical Psychology — cs had dropped *"evidence-based … through
  behavioral, cognitive, and therapeutic interventions"*. Restored as a full mirror.
- `04.01.05` Neuropsychology — cs had dropped *"especially following neurological
  injury or disease"*. Restored.
- `07.02` Mechanics (trade) — cs had dropped *"rebuilding … power-transmission
  assemblies … and performance"*. Completed (kept the existing "Mechanika" opening
  to stay parallel with the `en` "Mechanics"; did not reinterpret the physics-vs-trade
  ambiguity, which is present in the `en` too).

## Integrity checks run
- All 107 files parse; 0 Cyrillic; 0 `en` length violations (20–2000); trailing
  newlines intact on all touched files; 1-space indent preserved.
- Broken-brief-ref sweep: the only remaining "broken" refs are pointers to seed nodes
  invisible to a canonical-only scan (expected; lint tolerates these by design).
- No dangling/duplicate relations found anywhere in the tree.

## PROPOSED (not applied) — for a human / follow-up task

1. **Deep Czech backfill (322 L4 nodes lack `cs`).** Concentrated in `01.01` (144),
   `01.03` (65), `01.02` (63), `02.01` (56) — the four deeply-grown domains. These are
   technical leaf descriptions; translating them well needs a dedicated, verified
   Czech pass (ideally the same author who wrote the existing mirrors), not a
   coherence-review side-effect. High-value but a task of its own.

2. **Structural sparsity of L0 domains 03–12.** Domains 3 (Applied Sciences), 4
   (Social), 5 (Humanities), 6 (Arts), 7 (Trades), 8 (Survival), 9 (Reference), 10
   (Cultural), 11 (Digital), 12 (Post-disaster) are almost entirely **static seed
   spine** — most L1 files carry 1–51 nodes with 0 relations, versus 01.01's 321
   nodes / 742 relations. Domains 09/10/11/12 are effectively single-node stubs. This
   is the real structural gap in the map: the "preservation/rebuilding" half of the
   taxonomy (the KEAP mission's namesake) is barely grown. Growing them needs new
   `ext` subtrees (a separate epic — explicitly out of scope here), not description
   edits.

3. **No `relations` outside the four deep files.** Every domain except 01.01/01.02/
   01.03/02.01/02.02 has `relations: []`. Even where seed nodes clearly interrelate
   (e.g. 04.04 micro/macroeconomics siblings, 01.04 geoscience subfields, 07.02
   engine↔transmission↔brakes which the `brief` prose already cross-links via `[[id]]`),
   no typed relations exist. A targeted pass to lift the `[[id]]` links already written
   into briefs into first-class `relations` entries would materially improve graph
   navigability with low risk — recommend it as the natural next coherence task.
