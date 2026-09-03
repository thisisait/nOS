# 59 — A ceremony billed for the weather

**Found** 2026-09-03; **open** (the burn is named; the export edge and the
attribution question are roadmap rows).

The librarian's 05:36 ceremony ended `outcome_needs_revision` three nights
running (sessions 958/960/969, ~110k tokens each) with byte-identical gate
feedback: `cortex-corpus-diff: agrees is false`. The ceremony's own work was
done — session 969's lint queues were empty — and its revision iteration
re-did that work in full, then failed on the same clause again. The gate set
`live` judges the ESTATE, correctly; nothing distinguishes "your work failed
the gate" from "the gate was already failing before you started", so a
pre-existing condition bills every ceremony that shares the gate set, every
night, until an actor none of them can reach repairs it.

Why the clause fails, measured 2026-09-03 from `~/.nos/cortex-corpus-diff.json`
and the pulse run tails:

- **The KEAP→repo export edge does not exist.** The librarian promotes
  objects into KEAP's DB (345 knowledge_objects); `cortex-fs-sync` syncs the
  organ FROM the vendored repo corpus (337 files, "scanned 337 · upserted 0").
  Every promotion night widens a divergence only a repo commit + converge can
  close — the loop writes to one side of a two-sided invariant it is judged
  by. (2026-09-03: 8 objects `onlyKeap`, excused per-row as
  `organ-corpus-lacks-source`; the clause failed on the row below.)
- **KEAP's embed queue lost a row.** `keap-embed-sync` (04:48) reported
  "corpus current (upserted 0)" while KEAP held 345 object sources and 344
  vectors — one source with no vector that is NOT in the pending queue, so
  the sync sees nothing to do and the diff's `keap-embed-behind` count check
  (exact, always available) fails the clause. A self-inconsistency inside one
  store, upstream (nos-keap), invisible to its own repair job.

The fee's shape, stated generally: **an outcome loop that cannot attribute a
gate failure to its own session's work re-buys the failure nightly.** The
deliverable half of this was already solved (GateOracle's `deliverableExists`
— "the gates judge the tree; the work you owe is an artifact"); the converse
half — the gate judging weather the ceremony cannot touch — has no reader
yet. The honest repair is not to soften the gate: the estate IS divergent and
the gate says so. It is (1) the export edge, so promotion stops creating the
divergence; (2) the upstream embed-queue fix; and only then (3) whether a
baseline gate run before iteration 0 is worth one gate execution to stop the
re-work iteration — measured against what it saves, ~40k tokens per affected
ceremony night.

Roadmap rows: `cortex-keap-export-edge`, `keap-embed-queue-lost-row`,
`agentkit-baseline-gate-attribution`.
