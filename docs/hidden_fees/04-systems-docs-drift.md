# 04 — `docs/systems/` covers a third of the estate and targets dead paths

## The fee

`docs/systems/<svc>/{README,SKILLS,AGENTS}.md` is the substrate for the planned
vector skill router — SKILLS.md already carries named actions with **Trigger:**
phrases, which is close to an ideal routing corpus.

Two gaps, neither of which costs anything today:

- **Coverage.** 22 systems have docs; the live self-model describes ~60. The
  router will answer confidently for a third of the estate and be silent for the
  rest — and silence is indistinguishable from "no such capability".
- **Accuracy.** The docs target `https://auth.dev.local` and `~/stacks/<svc>/…`
  — a domain scheme and a path layout that predate `nos_data_root`. They describe
  a machine that no longer exists.

The second is the expensive one. A router that returns nothing is annoying; a
router that returns a confident, wrong endpoint sends an agent to act on stale
information.

## When the bill comes due

The moment the skill cards are embedded. Before that these are just stale docs
nobody reads; after it, they are authoritative answers to agent queries.

And embedding is close to irreversible in practice: once the corpus is in the
vector layer, wrong-but-confident entries outrank correct-but-thin ones — the
contract's own rule, agreed with the KEAP side:

> **In a recall target, confident wrongness outranks honest thinness.**

## How it was found

While scoping the self-model rework. The KEAP side offered its host-side
`describe` path to draft the ~60 node descriptions from these READMEs — and
withdrew the offer once the coverage and staleness numbers were on the table,
because drafting from a stale source produces confidently stale descriptions.

That withdrawal is the clearest statement of this fee: the docs are *worse* than
absent for anything that generates from them.

## What closes it

**Reconcile before embedding — the order is the whole point.**

1. Repoint the 22 existing systems at real domains and `nos_data_root` paths.
2. Then, and only then, generate/describe the remaining ~38.
3. The endpoint probe (nOS CI, output into the skills dataTable, never into card
   bodies — a probe result is volatile state and would re-embed the corpus on
   every cycle) turns accuracy from a one-time cleanup into a standing check.

Explicitly agreed **not** to be solved by running `describe` over the current
sources, and never over the 38 systems whose only input is a one-line manifest
subtitle.
