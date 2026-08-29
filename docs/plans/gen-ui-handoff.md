# Handoff to the generative-UI session — 2026-08-29

Written by the agentic-planes-build session. Two things happened while you were
running: I swept some of your work into my commits, and then I rebased the
branch you had already branched from. Both are mine. This says where everything
is and what the cheapest way forward looks like.

## 1. The sweep — resolved, nothing for you to do

On 2026-08-28 I committed with `git add -A` while we shared the working tree,
and three of my commits carried your files. That is separated: your work stands
in three commits of its own on `feat/planes-build`, with your name on the subject.

| commit | subject |
|---|---|
| `9d19fbd3` | feat(face): tables view + contracts, from the gen-ui session |
| `5e02800e` | feat(face): DataTable view block travels to the BFF, from the gen-ui session |
| `c8d8807a` | feat(keap): roadmap highlights, from the gen-ui session |

The split changed no bytes — `git diff` between the branch before and after was
empty, which was the only check that mattered.

## 2. The rebase — this one needs a decision from you

`feat/face-lens` branched off `feat/planes-build`, and I then rewrote that
branch's history under you. The merge-base is now `63036e6d`, and your branch
carries **13 commits, of which 8 are old copies of mine** under SHAs that exist
nowhere else. Your five:

```
f7f216d9 docs(doctrine): generative UI — fill the contract, never extend it
f641b00f feat(contracts): a reader that compares the two view contracts
c1308a49 chore(keap): pin v1.41.0 — the view block's transport
79527abb feat(roadmap): an applier for the definition's view block
2802f1e0 feat(roadmap): declare the view block the face renders
```

Cheapest way to land them — replay only yours onto the current branch:

```bash
git tag pre-rebase-face-lens feat/face-lens      # so the before-state is nameable
git rebase --onto feat/planes-build 63036e6d feat/face-lens
```

Expect conflicts where we both edited: `state/keap-tables/roadmap.table.yml`,
`tools/roadmap-seed.py`, possibly `files/anatomy/face/src/lib/tables/view.ts` —
because the three commits in §1 already carry an earlier snapshot of your work.
Where a hunk looks like your own change arriving twice, it is; take the later one.

Verify it the way I verified mine: diff the result against the tag and satisfy
yourself that nothing moved except what you meant to move.

## 3. What has already been converged — do not repeat it

You left five steps. Two are done, and one of those is done WRONG for your
purposes:

| step | state |
|---|---|
| `ansible-playbook main.yml --tags keap` | ran 2026-08-29, `failed=0` — but **without your v1.41.0 pin**, see below |
| `tools/view-contract-drift.py` | not on `feat/planes-build`; it exists only on your branch |
| `tools/roadmap-apply-view.py` (dry run) | same |
| `tools/roadmap-apply-view.py --confirm` | **the operator's act.** It writes a live store outside the playbook and nothing re-derives it |
| `ansible-playbook main.yml --tags face` | ran 2026-08-29, `failed=0`, smoke 47/47 |

Both converges ran against `feat/planes-build`, which does not contain your five
commits. So KEAP was rebuilt, but not at `v1.41.0` (`c1308a49`) — if that pin is
what carries the view block's transport, **the converge you actually wanted has
not happened**. Land your branch first, then re-run `--tags keap`, then the drift
reader. I can run tagged converges now (granted 2026-08-29); `sudo` and a full
`nos` still stop at the operator.

## 4. The estate moved under you — four things that may bite

- **Agent memory is gone, permanently.** Q8 was answered "no agent memory, EVER;
  KEAP is the estate's memory." `Dreamer`, `MemoryStore`, `bin/dream-agent.php`
  and the `agent_memory_stores` table are deleted, with a gate that fails if they
  return — including one that reads the live `wing.db`, because removing a CREATE
  does nothing to a database that already ran it.
- **`mcp-wing` split into read and write planes**, and `api_tokens` gained a
  `scopes` column. A bearer POST now needs `wing.write` — unless the route sits
  in its presenter's `publicActions`, like `/api/v1/events`, which is HMAC-gated
  and takes no bearer at all. Note the trap: `wing.write` in `agent.yml` means
  *may load the write tool*; in `api_tokens` it means *may POST to a scoped
  route*. Two axes, one spelling — a gate of mine got that wrong first.
- **`satisfied` is no longer a model's opinion.** Two DB triggers refuse to write
  it without a `gate_run_id`.
- **`state/anatomy-graph.json` is regenerated** (236 nodes, 266 edges) and the
  face layout pin re-frozen. If you touch the graph, run
  `tools/anatomy-graph-gen.py` and re-freeze the pin, or the pytest lane reds.

## 5. Two conventions that would have saved us both a day

- **Stage by path.** `git add -A` in a shared tree is a broom, not a staging
  command. Everything in §1 came from it.
- **Take a worktree.** `git worktree add` costs one command and makes §1 and §2
  impossible. Either of us should have done it at the start; I noticed second.

## 6. Your own finding, so it survives into whatever you write next

`c8d8807a` carries it: the roadmap highlight authored as `status eq shipped AND
verified eq contradicted` matched **zero** of 122 live rows — all 11 shipped rows
are `confirmed`, and every one of the 27 contradictions sits on a row someone had
already moved back to queued, next, active or parked. A declaration checked only
against the schema would have shipped an empty strip that looks exactly like a
table with nothing wrong in it.

## Delete this file once your branch has landed.
