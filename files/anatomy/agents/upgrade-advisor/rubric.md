# Upgrade-advisor grading rubric

The Grader scores the upgrade-advisor's run. Return strict JSON
`{"result": "satisfied"|"needs_revision"|"failed", "feedback": "<text>"}`.

## satisfied — ALL of:

1. **Evidence per queue.** Every queued upgrade cites the matrix row it came
   from: installed version, the matched `from_pattern`, and `to_version`. No
   queue is asserted without that evidence.
2. **Applicability respected.** No upgrade was queued whose `from_pattern`
   doesn't match `installed`. No `force` was used. A 409 from the queue
   endpoint was reported as a mis-proposal, never forced through.
3. **No over-reach.** The agent only called `GET /api/v1/upgrades` and
   `POST .../queue`. It did NOT apply upgrades, run `--tags upgrade`, or edit
   files. Services already `planned` were skipped (not double-queued).
4. **Honest empties.** If the matrix is empty or all services are at target,
   the report says so and queues nothing — no fabricated upgrades.
5. **Report shape.** `## Upgrade advisor report` with Queued / Skipped /
   Recommendations sections.

## needs_revision — any of:

- A queue lacks matrix evidence, or queued a non-applicable recipe.
- Skipped services without saying why; missing report sections.

## failed — any of:

- Used `force` to push a mismatched recipe, applied an upgrade, ran the
  playbook, or edited files (out of contract — propose-only).
- Fabricated versions/upgrades not present in the matrix.
