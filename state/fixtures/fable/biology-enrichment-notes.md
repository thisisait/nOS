# Biology domain (01.03) enrichment — review note

Scope: `knowledge/canonical/01-natural-sciences/01.03.json`, the `01.03.11` "Biological
Disciplines" catch-all cluster only (17 pillars + their L4 children). 154 nodes total.
Named seed branches `01.03.01`–`.10` left untouched per instruction.

Gates run locally after edits (all green):
- `node knowledge/lint.mjs` → **clean, 1577 nodes / 107 files**
- JSON valid, 154 nodes preserved, 1-space indent, trailing newline
- No Cyrillic in any `en`/`cs`; all `en` within 20–2000; all `cs` ≤ 2000
- `git diff` touches **only** `cs` and `brief` — zero changes to `id`, `parentId`,
  `level`, `kind`, `zone`, `ordinal`, `name`, `en`; no nodes added/removed
- All `[[id]]` refs in new briefs resolve to real ids

## Applied (in `01.03.json`)

### 1. Czech mirrors completed — 64 nodes
Every L4 node that had a dense `en` but no `cs` now carries a full, faithful Czech
mirror in the same register as the 61 existing L4 `cs` fields (mirror of `en`, not the
`brief`). Distribution by pillar:

- Molecular Biology `.01` — 7 (`.01`–`.07`)
- Cell Biology `.02` — 7 (`.01`–`.07`)
- Genetics `.03` — 7 (`.01`–`.07`)
- Genomics & Bioinformatics `.04` — 4 (`.01`–`.04`; `.05`–`.08` already had cs)
- Developmental Biology `.05` — 4 (`.04`–`.07`; `.01`–`.03` already had cs)
- Evolutionary Biology `.06` — 8 (`.01`–`.08`)
- Ecology `.07` — 1 (`.01`; `.02`–`.07` already had cs)
- Neuroscience `.09` — 6 (`.01`–`.06`; `.07` already had cs)
- Systems & Synthetic Biology `.13` — 4 (`.04`–`.07`; `.01`–`.03` already had cs)
- Biophysics `.14` — 8 (`.01`–`.08`)
- Botany `.15` — 1 (`.01`; `.02`–`.07` already had cs)
- Zoology `.16` — 7 (`.01`–`.07`)

Terminology grounded in standard Czech biological usage: *buněčná biologie, genetika,
imunologie, mikrobiologie, dědivost* (heritability), *nezávislá kombinovatelnost*
(independent assortment), *vzrušivost* (excitability), *gliové buňky, ribopřepínače*
(riboswitches), *replizom, kanálopatie, homininů, mendelovská dědičnost*. Loanwords with
no settled Czech equivalent kept verbatim (*biofoundry, FRET, AFM, SNARE, CRISPR, evo-devo,
de novo*). Each `cs` re-read after finalising; no calques, no Slovak forms, zero Cyrillic.

### 2. Pillar briefs added — 17 nodes
Each of the 17 `01.03.11.NN` pillars (which had `en` + `cs` but no `brief`) now carries a
two-paragraph node-article. First paragraph defines the discipline; second carves its
boundaries against sibling pillars and, where the boundary matters, against neighbouring
domains ([[01.02]] Chemistry, [[01.01]] Physics). Cross-refs point at the **live sibling
pillars** (`01.03.11.01`–`.17`) rather than the empty named seed branches, to reinforce the
real content graph and avoid legitimising the duplication (see proposal below). All ids
verified real.

### 3. Description (`en`) sharpening — 0 changes (deliberate)
Every existing `en` (pillars and L4 children) is already dense, encyclopedic, and
boundary-carving — none restate the node name, none are templatey, none are thin. Per the
"leave good descriptions alone / judgment over volume" directive, I made **no** `en` edits.
The three slightly list-formier pillar intros (Microbiology & Virology `.11`, Systems &
Synthetic `.13`, Botany `.15`) are still complete and accurate; rewriting them would have
been churn, not improvement, and would have forced parallel `cs` rewrites for no content gain.

---

## PROPOSED (not applied)

### A. Named-vs-catch-all reconciliation — RECOMMENDATION: keep the catch-all, retire/redirect the named seed branches
The static seed spine defines named L2 branches `01.03.01`–`.10` (Molecular Biology,
Cell Biology, Genetics, Genomics, Developmental, Evolutionary, Ecology, Microbiology,
Physiology, Neurobiology) as `seed-override` nodes that each carry a good domain brief but
**no child content**. All the actual depth lives under the single `01.03.11` "Biological
Disciplines" catch-all (17 pillars, ~142 nodes). This is a structural redundancy: the seed
briefs describe the same subfields the `01.03.11` pillars actually populate.

My recommendation is the reverse of moving content *into* the named branches:

1. **Do not author parallel trees under `01.03.01`–`.10`.** That would double the graph and
   split every subfield's content across two ids (the exact duplication the task warns against).
2. **Promote `01.03.11`'s pillars to be the canonical discipline layer.** They are richer
   (17 vs 10 branches — they add Immunology, Structural Biology, Systems & Synthetic Biology,
   Biophysics, Botany, Zoology, Astrobiology as first-class disciplines the seed's 10 lack),
   fully described, and now fully bilingual + briefed.
3. **Reconcile the seed spine, not the delta.** The clean fix is upstream in
   `src/game/data/taxonomy.ts`: either (a) collapse the 10 named seed branches so `01.03.11`'s
   children reparent up one level and `01.03.11` itself dissolves, or (b) keep the 10 named
   branches as the L2 layer and **move** the 17 pillars under them (merging the 7 extra
   disciplines in), then delete the `01.03.11` wrapper. Option (b) yields the more conventional
   taxonomy (disciplines directly under Biology) but is a larger seed edit and reshuffles ~142
   ids. Option (a) is mechanically smaller but leaves the "Biological Disciplines" wrapper as a
   slightly awkward extra level.
   - Net: **(b) is the better end-state, (a) the cheaper interim.** Either way the named seed
     branches and the catch-all must not both carry content — pick one home. Until that seed-level
     decision is made, the catch-all is the correct place for content and the named branches should
     stay empty (as they are).
4. This is a **seed-spine (`taxonomy.ts`) + id-migration** change, out of scope for a
   canonical-delta content pass. Flagging for a dedicated structural epic; no delta edits made.

### B. Genuinely-missing biology subfields worth a future additive pass
The 17 pillars are strong but a few established subfields have no clear home. Candidates for
new L4 children (or, post-reconciliation, new pillars), in rough priority:

- **Mycology** — fungi are a whole kingdom with no dedicated node. Currently only implicit
  (antifungals under Microbiology `.11.06`). Deserves at least an L4 block, arguably a pillar.
  Highest-value gap.
- **Marine / Aquatic Biology** — cross-cutting (ecology + physiology + zoology) but a
  recognised discipline with no anchor; could sit under Ecology `.07` or as a pillar.
- **Parasitology** — split today across Microbiology (pathogens) and Immunology (host); a
  dedicated block would consolidate helminth/protozoan biology that fits neither cleanly.
- **Paleobiology** — partially covered by Evolutionary `.06.05` (Macroevolution & Paleobiology);
  fine as-is unless a deeper fossil/taphonomy tree is wanted.
- **Conservation Biology** — currently two overlapping L4s (`.07.06` restoration ecology,
  `.16.07` wildlife biology); adequate, but a unified pillar could reduce the split.
- **Biochemistry / Metabolism** — sits on the biology↔chemistry boundary; metabolic pieces are
  scattered (Physiology `.08.07`, Metabolic Engineering `.13.03`, Cell Biology). If Chemistry
  ([[01.02]]) does not own core metabolism, a Biology-side biochemistry block is worth considering.
- **Systematics / Taxonomy as a standalone** — currently embedded per-kingdom (Zoology `.16.03`,
  Botany `.15.04`, Evolutionary `.06.02`); acceptable, low priority.
- **Chronobiology, Toxicology, Biogeography** — smaller, defensible as L4 additions under
  Physiology / Ecology respectively; low priority.

All of the above are **additive** (new nodes) and therefore out of scope for this
description-level pass. Recommend Mycology first if a future additive pass is greenlit.
