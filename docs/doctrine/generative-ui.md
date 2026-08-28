# Generative UI

**The decision:** a model may FILL a declarative render contract. It may never
extend one, and it may never add a capability.

Everything a "generative UI" needs already existed as `TableView` — the block a
DataTable uses to say how it wants to be rendered. So there is no generative-UI
framework in this estate and there must not be one: there is a contract, and two
kinds of author for it (a person, a model), passing through the same door.

## The contract

`TableView` — declared twice, deliberately, at a repo boundary:

| Where | What it does |
|---|---|
| `files/anatomy/face/src/lib/contracts/index.ts` | the TypeScript the face renders from |
| `<keap>/shared/contracts/table.ts` (`viewMetaSchema`) | the zod KEAP validates with, at author time |

It names **column keys, comparison ops and labels** — never a chip, a tab, a
pixel or a component. That is the whole reason it survives a second renderer: a
native client reads the identical JSON from `GET /agent/v1/tables/:slug` and
decides for itself whether a facet is a `<select>` or an `NSPopUpButton`.

Predicates reuse KEAP's `filterOpSchema`. A second spelling of "status equals
shipped" would be two answers to one question.

Two copies with nothing comparing them is this estate's most-repeated defect, so
`tools/view-contract-drift.py` compares them. It is a **reader, not a gate** —
CI has no KEAP checkout, and inventing one would be a third copy to keep in step
(`cortex-drift.py` settled this).

## The trust boundary

`narrowView()` in `$lib/tables/view.ts`, called at exactly one seam
(`routes/bff/tables/+server.ts`). An authored block and a model's proposal go
through the same check — a second, gentler entrance would make the first one
advice.

- **May be influenced:** which existing column a facet or predicate names, which
  of the seven ops, a scalar value, a label, which action id, the order.
- **May never be produced:** a column not in `table.columns`, an op outside the
  enum, an action outside the catalog, a URL, a command, markup, a style.
- **Refuse, do not repair.** One bad predicate voids its whole highlight: a
  partially-applied AND selects different rows and labels them with the author's
  confident words. What was dropped is REPORTED (`viewDropped`), never swallowed.

## The action catalog is code

`offer.action` selects from `VIEW_ACTIONS` in `$lib/tables/view.ts`. This is the
genome's rule (`state/genome/entity.schema.json`) pointed at the face: *a
capability must not be addable by data, so opcodes and handlers stay code, per
runtime*. Data says WHICH of the things a renderer already does is worth doing;
it can never teach it a new one.

Fail-closed ordering, also the genome's: **the handler ships first, the id joins
the list second.** A member with no arm is a declaration that validates and does
nothing. KEAP deliberately does NOT validate `action` — the catalog belongs to
whichever runtime renders, and a store pinning it would declare a capability for
a client it cannot see.

## Deterministic first; the model is the fallback

**If the answer is already in the columns, there is no model call.** The roadmap
declares `status` (a claim) beside `verified` (an observation); "a probe
disagrees" is a predicate, not an inference. A model asked to re-derive four
lines of YAML on every open is slower, non-deterministic, and no more correct.

The generative path (`buildViewProposalPrompt`) is **design-time**: propose a
block for a table nobody has authored one for, narrow it, and the operator
pastes the survivor into the `.table.yml`, where it is reviewable and diffable.
There is no runtime route and no cache — add them when a table proves it needs
one, not before.

**A declaration must reach the estate.** A `view:` in git with no applier is
git-green and estate-absent — the shape that cost this feature three silent
holes in one afternoon (the agent create mapping, the reconcile path, and a GET
that omitted what PATCH accepted). Appliers: the playbook seeder for `face-*`
tables, `tools/roadmap-apply-view.py` for the roadmap. Gate:
`test_view_block_travels_and_is_narrowed.py` proves an applier EXISTS; only a
reader proves it RAN.

## For a loop that learns to offer better

Not built. The seams above are deliberately sufficient for one, and the two
rules it will need are stated here because they are easy to get wrong by
guessing:

1. **A loop may not grade its own offers.** "The offer was useful" written by
   the thing that made the offer is a success marker written by the code that
   attempted the work — the defect the roadmap's own `status`/`verified` split
   exists to end. The usefulness signal must come from a separate observation
   (was it clicked, was the row then opened), and **it does not exist yet**. Do
   not synthesise one.
2. **A loop proposes; it does not apply.** Applying is a converge or an operator
   running a tool with `--confirm`, and both are dry-run by default. A proposal
   that writes itself has skipped the only step where a person could disagree.
