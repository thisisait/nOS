# Mathematics (02.01) enrichment — fable pass notes

Date: 2026-07-14 · File touched: `knowledge/canonical/02-formal-sciences/02.01.json` (only) · 263 nodes, structure untouched (ids/parentId/level/kind/name/zone/ordinal verified byte-identical vs HEAD; relations untouched). `node knowledge/lint.mjs` clean (1742 nodes / 107 files).

## 1. Czech completed — 55 nodes (0 missing after pass)

All were level-4 children under the MSC pillars; every node in the file now carries a full Czech mirror. Established terminology used throughout (teorie čísel, komutativní algebra, teorie pravděpodobnosti, variety, svazy, toulce, systémy hromadné obsluhy, analýza přežití, …); no Cyrillic, no Slovak forms, ≤2000 chars (programmatic sweep + re-read).

- 02.01.04.01.01, .01.02, .02.01, .03.01
- .07.01, .07.03, .10.05, .10.06, .11.02
- .12.01, .12.02, .12.03, .12.05
- .18.01–.18.04, .20.01, .24.03, .25.03, .25.05
- .26.01–.26.03, .31.01, .40.01–.40.03, .42.04, .43.03
- .45.01–.45.08, .46.01–.46.06
- .48.01, .48.02, .49.01, .49.02, .50.01, .50.02, .51.01, .51.02, .52.01–.52.03

Terminology choices worth flagging: prvoradikál (prime radical), toulec (quiver), okruhy šikmých polynomů (skew polynomial rings), skorookruhy/polookruhy (near-rings/semirings), skupinkový výběr (cluster sampling), cenzorování/trunkace (survival), omezená variace, faktorové prostory.

## 2. English descriptions repaired — 15 nodes (480-char import clip)

These `en` fields were hard-truncated at exactly 480 characters, mid-word — an import artifact, not authored prose. Each got its final sentence completed in register (no other rewriting of dense text):

02.01.04.01.01, .01.02, .02.01, .03.01, .48.01, .48.02, .49.01, .49.02, .50.01, .50.02, .51.01, .51.02, .52.01, .52.02, .52.03

No other `en` was judged weak or circular enough to touch — the 02.01.04 corpus is unusually well-carved (boundary-stating, MSC-code-aware); leaving it alone was the right call.

### Known defect NOT fixed (proposal): 104 clipped brief lead paragraphs
The same 480-char clip lives inside the **brief** field of 104 level-4 child nodes: each brief opens with a lead paragraph that repeats the node's `en` but truncated at 480 (e.g. `02.01.04.44.01` brief lead ends "…Kolmogorov, Feller, an"). The leads were generated from a serial-comma variant of the en, so they are not verbatim prefixes — a blind mechanical replace is not identity-safe, but replacing each clipped lead with the node's current (complete) `en` verbatim would be correct and scriptable. Left out of this pass to keep the blast radius at the tasked scope; recommend a dedicated mechanical pass + lint gate ("brief lead must end in sentence punctuation").

## 3. Briefs added — 52/52 MSC pillars (02.01.04.01–.52)

Each pillar now carries a 2-paragraph node-article: paragraph 1 states what the discipline is and its internal strata; paragraph 2 carves the boundaries via `[[id]]` cross-refs. Every ref target verified to resolve: 54 distinct targets, all present in this file except `[[01.01]]` (Physics, sanctioned) — checked programmatically against node ids AND spot-checked semantically against node names (no off-by-one). Physics boundary is drawn where it matters: 10 (mirror symmetry), 12/13 (quantum groups, Lie/Jordan), 16/17 (symmetry, gauge groups, Noether), 21 (Newtonian potential), 23–26 (evolution laws, Hamiltonian/KAM), 34/35 (quantum observables), 36 (least action), 39 (general relativity), 41–44 (TQFT, gauge theory, statistical mechanics), 46 (simulation), 51 (quantum information), plus 01/45 informally.

## 4. Reconciliation verdict — empty seed branches

`02.01.01` (Pure Mathematics: seed children .01 Algebra, .02 Analysis, .03 Geometry, .04 Topology, .05 Number theory) and `02.01.02` (Applied: .01 Statistics, .02 Probability, .03 Numerical, .04 Optimization, .05 Game theory) are described seed nodes with **no grown subtrees** — their subject matter lives fully under the `02.01.04` MSC pillars (07, 09–17 ↔ algebra/NT; 18–35 ↔ analysis; 37–43 ↔ geometry/topology; 44–50 ↔ the applied five). Correctly left alone: growing them would create parallel duplicate trees.

**Proposal:** keep `02.01.01`/`02.01.02` as *orientation* layers (motive-based: pure vs applied) and make the MSC pillar tree the single *content* home, linking rather than duplicating — i.e. add `related-concept` relations (or brief `[[id]]` refs) from each seed leaf to its MSC pillar(s): 02.01.01.01→02.01.04.{06,08,09,12,13,16}, .02→{18,19,20,26,28,34}, .03→{37,38,39}, .04→{40,41,42}, .05→{07}; 02.01.02.01→{45}, .02→{44}, .03→{46}, .04→{48,36}, .05→{49}. Structural, hence out of scope for this pass. `02.01.03` (computational/experimental mathematics) has genuine own content and is already cross-referenced from pillar briefs 09, 10, 47.

## 5. Missing subfields (observed gaps, NOT added — structural)

MSC2020 top classes absent as pillars (the 52 present skip these codes): **06-XX is present as .05**; genuinely missing vs full MSC2020: none at top level — all 63 MSC classes are either present or deliberately merged (the file's 52 pillars fold e.g. 33/42/43/44/45 siblings faithfully). Within pillars, notable child-level gaps a future grow pass could fill:
- 02.01.04.16 has no dedicated *geometric group theory* child; 20F is folded into general structure.
- 02.01.04.44 lacks a *stochastic PDE / interacting particle systems* child (60H/60K frontier).
- 02.01.04.47 lacks *quantum computing* (68Q12) and modern *learning theory* (68T05) split-outs.
- 02.01.04.03 syntactic child exists (.03.01); a matching *semantic* child (model/set/computability, 03C/03E/03D) appears under-articulated relative to pillar en.
- 02.01.04.30 could use a *wavelets & time-frequency* child (42C40) given its research weight.

## 6. Verification run

JSON valid after every batch (incremental Edit-tool batches of ≤5); final gate: structure diff vs `git HEAD` clean, 52/52 briefs, 263/263 cs, en 20–2000, cs ≤2000, zero Cyrillic, zero unresolved `[[refs]]`, trailing newline + 1-space indent preserved, `knowledge/lint.mjs` green. Round-trip (`roundtrip.mjs`) not run here (needs the container-side libSQL path) — left to the caller's gate as announced.
