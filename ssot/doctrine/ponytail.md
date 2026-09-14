# ponytail — the ladder this repo builds on

## 1. The ladder

The badge is not decoration. Code SHALL answer `ponytail` before it is written.
It is a ladder: stop at the first rung that holds.

1. Does this need to exist at all?
2. Is it already in this codebase?
3. Does the stdlib do it?
4. Does the platform do it natively?
5. Does an installed dependency solve it?
6. Can it be one line?
7. Only then: the minimum code that works.

**The ladder shortens the solution, never the reading.** A small diff in the
wrong place is not lazy; it is a second bug. The flow MUST be traced first;
then climb.

## 2. Why this repo, specifically

The estate's worst defects are over-building or under-reading. Each was found
by reading, not by adding:

- `tests/anatomy/test_a_hook_knows_which_stack_it_is_for.py` inferred a plugin's
  kind instead of reading the `type` field two files over (rung 2).
- `traefik_auth_modes` re-derived three services' edge gates from a default
  while the plugin manifest already named them (rung 2).
- A probe reconstructed `<prefix>_pw_backup_encryption` to compare digests;
  asking whether the live key contains the prefix needed no concatenation and
  was strictly broader (rung 6).

## 3. The `ponytail:` marker

A deliberate simplification with a known ceiling SHALL carry a comment naming
the ceiling and the upgrade path:

```python
# ponytail: global lock, per-account locks if throughput matters
```

`/ponytail-debt` greps them into a ledger, so a deferral cannot quietly become
permanent. A marker with no named trigger is the one that rots — the ledger
tags those `no-trigger`.

The marker is for a corner genuinely cut. Code that is simply small MUST NOT
carry one, and a repo full of markers is a repo apologising for itself.

## 4. Deliberately not here

No count of markers, and no "N% lazier" figure. The unbuilt version was never
written, so there is no baseline to subtract from — and a number carried in a
document is this estate's most reliably wrong artifact. Ask `/ponytail-debt`,
which counts at the moment you ask.
