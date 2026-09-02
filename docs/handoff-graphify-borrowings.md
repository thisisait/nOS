# Handoff — Graphify borrowings (items 3–5 + the embeddings decision)

Give the agent everything below the line. It is written to be pasted whole.

Roadmap row: `cortex-graph-borrowings` (track cortex, status next).
Ask it with `tools/roadmap-status.py --track cortex`.

---

You are working in the **nOS** repo. Read `CLAUDE.md` first — it overrides your
defaults. Run `/ponytail full` and stay in it: the ladder is a reflex, and the
best code here is the code you talk the operator out of writing.

## Standing constraints, not preferences

- **Partial tagged converges are yours; sudo and full `nos` runs are the operator's.**
- **`config.yml` needs consent every time.** It is gitignored and it is theirs.
- **Removals are the operator's act.** You may stop; you may not delete.
- **Never `git add -A`.** Other sessions share this working tree. Stage paths.
- **`files/anatomy/apex/ruling.yml` may gain rows. You may NOT re-sign it.**
  Adding a WITHHELD row is fine and needs no signature (the published set is
  unchanged); `tools/awaiting-operator.py` will report the amendment, which is
  correct and is the operator's to clear.
- **Readers are read-only. The seeder is the writer.** `tools/roadmap-seed.py`
  writes the roadmap table. Note: it does NOT parse arguments — `--help` seeds.
- Comments: **~4 lines**. Keep the measurement, the defect, the gate. Cut the essay.
  Long accounts go in `docs/hidden_fees/` or a devlog.

## The house rules you will be judged against

1. **Absence is never success. A skip is not a pass.** A check that cannot run
   reports UNKNOWN, never green.
2. **A success marker is written by a READER, not by the code that attempted the
   work.**
3. **A detector reads the ARTIFACT, not the prose.** Parse the AST, render the
   template, run the SQL, ask `--json`. A gate that greps a comment passes on the
   comment. This has recurred four times in one day; you will not be the fifth.
4. **Retro-verify every gate against its own broken state, each break
   independently.** A gate never seen red is not a gate. Restore afterwards and
   show it green.
5. **A field with one value is decoration.** Before shipping any enum, count its
   members on real data.

## What already shipped (do not redo it)

Read these first; they are the pattern to match.

- `tools/anatomy-graph-gen.py` — compiles `state/anatomy-graph.json` (256 nodes,
  286 edges). Now stamps `evidence` on every edge and **refuses** one carrying
  neither `derived:` nor `measured:`.
- `tools/graph-report.py` — reader. God nodes, isolated nodes, evidence split,
  and evidence **rot** (resolves `file:line` citations out of an edge's `via`
  and asks git whether that file moved since).
- Gates: `tests/anatomy/test_every_edge_says_how_it_is_known.py`,
  `tests/anatomy/test_the_graph_report_only_reads.py`.

Run `python3 tools/graph-report.py` before you start. Its output is your context.

## Your task

The roadmap row carries the full brief. Three items, and **each needs a decision
recorded before any code**:

**3 — a code graph (the only genuinely absent thing).** The estate has an
infrastructure graph and a concept graph and nothing that answers *what calls
`nos_prune_plan`* or *what breaks if I change this filter*. Graphify
(Apache-2.0, tree-sitter, 37 grammars, deterministic, no LLM) does exactly this.
Decide first, in writing: where the code graph lives (a fourth artifact, or edges
in the existing one), who regenerates it and on what trigger, and whether a
Python extractor may enter an Ansible estate as a role or only as a dev tool.
Do not vendor before those three are answered.

**4 — Leiden communities as a cross-check.** The estate DECLARES `stack`,
`organ`, `layer`. Communities computed from the 286 existing edges will disagree
somewhere, and **the disagreement is the deliverable** — not the clustering.
Costs a `networkx` dependency, which is not installed; that is a decision, not a
detail. Precedent for the shape: the layer survey in `plat-defaults-derive`
falsified a rule that had looked obviously right.

**5 — a `.gitattributes` merge driver for `state/*.json`.** Small. Parallel
agents regenerate these and today that is a conflict.

## The part that is not a build ticket

The embeddings question is why this row exists. **Argue it; do not assume it.**

The case against embeddings as a store, which is the estate's own case and not
Graphify's: a cosine top-k **always answers** — k results, ranked, with no notion
of nothing-here, which is absence rendered as a result. A graph traversal that
finds no path returns *no path*, a real negative. Three more asymmetries:
provenance (every edge now says how it is known; a neighbour hit has a float),
rot (a `measured` edge rots *detectably*; a vector rots invisibly — no date to
compare), and threshold.

The case for: a graph cannot traverse to a node you cannot name, and prose is how
humans and agents arrive.

**Establish the state of play before proposing anything.** `cortex-resolve.ts` is
BM25/FTS and already does ambiguity detection — and already refuses RRF scoring
because "adjacent ranks differ by ~0.00026 and the value is bounded to ~0.016
regardless of match quality — a threshold built on it fires on every query or on
none". That is a sharper position than Graphify states. `cortex-ann.ts` is a
separate vector path (`vector_top_k` over a libSQL index). **The estate runs
both.** So the honest question is not whether to have embeddings — it is which
questions reach the ANN path, and whether that path can say *nothing*.

Answer that with a measurement, not an opinion.

This reaches KEAP's `keap-embed-sync` and Qdrant, so **the doctrine is the
operator's call**. Bring them the evidence and a recommendation; do not ship a
retrieval change on your own authority.

## Definition of done

- Each of 3/4/5 has a decision written down, or a stated reason it was deferred.
- Anything you build has a gate, retro-verified against its own break.
- `python3 -m pytest tests/anatomy -q` is no worse than you found it. One
  pre-existing failure is expected: `test_hub_url_audit.py::test_no_hard_404_in_hub_systems`
  (six Authentik applications absent because the main checkout's tofu desired
  state was rendered under a profile and declares 14 services). Not yours.
- Report what you did NOT do, and why. Scaling the work down is the operator's
  call, not yours.
