# Chemistry (01.02) enrichment — Fable pass

Target: `knowledge/canonical/01-natural-sciences/01.02.json` (145 nodes; the live
content sits under pillar cluster `01.02.11` "Chemical Disciplines", 15 L3 pillars
+ their L4 children). Edits touched only `cs` / `brief`; no `en` was altered.

## What changed (counts)

- **Czech (`cs`) completed: 62** L4 nodes. Every previously-`cs`-less dense-`en`
  node now carries a full Czech mirror in established chemical terminology
  (organická/anorganická/fyzikální chemie, koordinační sloučeniny, reakční
  kinetika, spektroskopie, termodynamika, aktinoidy, retrosyntéza, glykobiologie,
  radiolýza, kosmochemie, …). Post-edit `missing cs = 0` across the whole file.
  Diacritics/orthography checked; no Cyrillic (lint `CYR` gate clean); no Slovak
  forms; loanword-vs-Czech balance kept (e.g. `křížové kaplinky (cross-coupling)`,
  `spřažená (hyphenated)` glossed once, then Czech).
- **Briefs added: 15** — one node-article on every `01.02.11.xx` L3 pillar
  (`.01`–`.15`), which previously had none. Each is 2 paragraphs, boundary-carving,
  and cross-references sibling pillars plus `[[01.01]]` Physics / `[[01.03]]`
  Biology where the disciplinary edge actually runs.
- **`en` descriptions sharpened: 0.** Every existing `en` was already dense and
  boundary-carving (a consistent "definition / scope / maturity-frontier" shape).
  None met the "genuinely weak / circular / templatey" bar, so per the surgical
  brief I left them untouched — judgment over volume.

## `[[id]]` integrity

All brief cross-refs were validated programmatically against the ids actually
present in the file (plus the two cross-domain L1 targets, which exist as sibling
files `01.01.json` / `01.03.json`). Only real ids used:
- sibling pillars `01.02.11.01`…`01.02.11.15`
- cross-domain `01.01` (Physics), `01.03` (Biology)

No guessed sibling numbers. (Guard script asserted every `[[…]]` resolves before
write; `node lint.mjs` then passed: "✓ knowledge lint clean — 1577 nodes".)

## Catch-all reconciliation verdict (proposal — NOT applied)

The seed spine carries **named-but-empty L2 branches `01.02.01`–`01.02.10`** whose
topics are already, and more deeply, covered by the `01.02.11` pillar cluster. I
left them empty as instructed (authoring there would duplicate the graph). The
overlap map, for a future structural decision:

| Empty L2 seed | Covered by pillar |
|---|---|
| `01.02.01` General/foundational chemistry | *(no pillar — see gap below)* |
| `01.02.02` Organic | `01.02.11.01` |
| `01.02.03` Inorganic | `01.02.11.02` |
| `01.02.04` Physical | `01.02.11.03` |
| `01.02.05` Analytical | `01.02.11.04` |
| `01.02.06` Biochemistry | `01.02.11.05` |
| `01.02.07` Environmental | `01.02.11.12` |
| `01.02.08` Medicinal | `01.02.11.13` |
| `01.02.09` Materials | `01.02.11.07` |
| `01.02.10` Computational | `01.02.11.06` |

`01.02.11` additionally covers six disciplines with **no** named L2 twin: Polymer
(`.08`), Electrochemistry (`.09`), Photochemistry & Radiation (`.10`), Nuclear &
Radiochemistry (`.11`), Supramolecular & Nano (`.14`), Astro/Cosmochemistry (`.15`).

**Verdict:** `01.02.11` is the authoritative disciplinary map; `01.02.01`–`.10`
are redundant seed stubs. Recommended future reconciliation (structural, needs a
node/id migration — flagged, not done here): pick ONE of
1. **Collapse** — retire the `01.02.01`–`.10` names into `01.02.11` as the single
   home (simplest; the L2 seeds already read as a duplicate index), or
2. **Re-parent** — promote the `01.02.11.xx` pillars up to become the `01.02.0x`
   L2 branches and dissolve the `01.02.11` intermediate, so the tree matches the
   flatter seed intent. Either way the *content* stays where it is now.

## Genuinely-missing chemistry subfields (future additive pass)

Coverage of the 15 pillars is broad and current. Real gaps worth an additive
(node-adding) pass later:
- **General / foundational chemistry** — atomic structure, periodic law,
  stoichiometry, states of matter, acid–base & redox fundamentals. Lives only in
  the empty seed `01.02.01`; the pillar cluster jumps straight to specialist
  disciplines with no "entry layer" L3. Best candidate for a new pillar.
- **Geochemistry / mineral & cosmochemistry-adjacent Earth chemistry** — only
  partially present (aquatic/soil under `.12`, meteorites under `.15`); no
  dedicated geo/mineral-chemistry pillar.
- **Industrial / process chemistry & the chem-eng interface** — catalysis is well
  covered, but scale-up, unit operations, and process chemistry are absent.
- **Food & agricultural chemistry** — absent.
- **Forensic chemistry** — absent (only implicit in analytical MS `.04.02`).
- **Crystallography as a discipline** — currently dispersed across structure-
  elucidation and solid-state L4s rather than named.

## How the edit was made (reproducibility)

Data authored in `/tmp/chem-data.json` (`{cs:{…}, brief:{…}}`), applied by a guard
script that (a) rebuilt each touched ext node in canonical key order
(`…en, cs, brief`), (b) asserted no `id/level/parentId/name/zone/ordinal/kind/en`
or `relations` drift, (c) asserted every brief `[[id]]` resolves and no `cs`
Cyrillic / >2000, then wrote with `json.dumps(indent=1, ensure_ascii=False)+"\n"`
(1-space indent, trailing newline — byte-format matches the untouched file).
Diff: 92 insertions / 15 deletions; the 15 deletions are pillar `cs` lines that
merely gained a trailing comma now that `brief` follows them.
