# ponytail — the ladder this repo builds on

The badge is not decoration. `ponytail` is the rule we answer to before writing
code, and it is a ladder: stop at the first rung that holds.

1. Does this need to exist at all?
2. Is it already in this codebase?
3. Does the stdlib do it?
4. Does the platform do it natively?
5. Does an installed dependency solve it?
6. Can it be one line?
7. Only then: the minimum code that works.

**The ladder shortens the solution, never the reading.** A small diff in the
wrong place is not lazy, it is a second bug. Trace the flow first, then climb.

## Why this repo, specifically

The estate's own worst defects are all over-building or under-reading:

- A gate that measured its own heuristic instead of the tree
  (`test_a_hook_knows_which_stack_it_is_for.py` — the first draft inferred a
  plugin's kind rather than reading the `type` field two files over: rung 2).
- Three services whose edge gate was already written down in their plugin
  manifest, re-derived from a default because the renderer read a different
  file (`traefik_auth_modes`: rung 2 again).
- A probe that reconstructed `<prefix>_pw_backup_encryption` to compare digests
  when asking whether the live key *contains* the prefix needed no
  concatenation and was strictly broader (rung 6, and it also stopped tripping
  a security gate).

Every one of those was found by reading, not by adding.

## The `ponytail:` marker

A deliberate simplification with a **known ceiling** carries its own comment
naming the ceiling and the upgrade path:

```python
# ponytail: global lock, per-account locks if throughput matters
```

`/ponytail-debt` greps them into a ledger, so a deferral cannot quietly become
permanent. A marker with no named trigger is the one that rots — the ledger
tags those `no-trigger`.

The marker is for a corner genuinely cut. Code that is simply small does not
need one, and a repo full of markers is a repo apologising for itself.

## Deliberately not here

No count of markers, and no "N% lazier" figure. The unbuilt version was never
written, so there is no baseline to subtract from — and a number carried in a
document is this estate's most reliably wrong artifact. Ask `/ponytail-debt`,
which counts at the moment you ask.
