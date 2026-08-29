# 35 — An authorised discontinuity per converge

**Found 2026-08-29, by giving Pulse a dashboard and reading down it.**

`27-pulse.json` shipped with a failure-rate table. `wing:audit-chain-verify` was
on it — 4 failures in 31 runs. Following those four to their stored output:

```
{"ok":false,"checked":337462,"unsigned":37,
 "first_break":{"id":337500,"why":"segment start prev_hash neither genesis nor recorded anchor"}}
```

That break is already documented and was handled correctly: a bare
`php bin/run-agent.php` inherited no chain env, appended 37 unsigned rows, and
the operator acknowledged the window through the reviewed path. Fine.

What was not fine was two rows down in the same investigation:

| | |
| --- | --- |
| segment anchors in `audit_chain_meta` | **99** |
| age of the newest | **three hours** |
| period they accumulated over | **five weeks** |

## The fee

A segment anchor is the verifier's permission to resume the chain at a
`prev_hash` it cannot derive — the boundary of a window where the chain was off
and rows landed unsigned. `bin/backfill-event-chain.php` records one, and its
own docstring states the contract: *"MUST run after each flag OFF->ON toggle"*.

`roles/pazny.wing/tasks/post.yml` runs it on **every converge** where
`wing_audit_chain_enabled` is true. The `when:` expresses *the chain is on*, not
*the chain was just turned on* — and those are not the same condition. The only
guard against repeat work compared the recorded anchor against the current
chain tail, which has moved every time, so every call minted a fresh anchor.

Ninety-nine authorised discontinuities, of which two or three were earned.

**What it costs, stated exactly and no wider.** An anchor is only reachable
after an unsigned row resets the segment, so this is not a free deletion of
history — an attacker still has to leave a `row_hash IS NULL` at the boundary.
What it does is convert *the chain broke here* into *the chain was allowed to
break here* at ninety-nine points instead of three, and the nightly verify
reports `ok:true` across all of them. The chain's entire value is that a
discontinuity is remarkable. Ninety-nine of them are not remarkable.

It is also the same shape as this estate's older lesson, one level up: a check
that compares an artefact against itself is blind to a uniformly wrong input.
Here the check had been handed a growing list of exceptions by the machinery it
was checking.

## What was done, 2026-08-29

The default path writes nothing when the chain tail is signed. An anchor is
minted only when the last row of `events` is unsigned — which is exactly the
OFF→ON boundary the tool exists for — or when the ledger is empty. The
operator's `--acknowledge-gap-before` path, which already refuses anything but a
clean window, is untouched.

Gate: `tests/anatomy/test_an_anchor_is_earned_by_a_gap.py`, running the real
script against throwaway databases. Retro-verified against the unconditional
mint, against anchoring the wrong row, and against a refusal that exits zero.

## Not closed

**The 99 existing anchors stay.** Each one opens a segment that is already
signed under it; deleting one would break verification of real history. The fix
is to stop minting, and the count will now be a fact worth reading rather than a
counter of converges.

**Nothing reviews an anchor.** There is no surface listing them with the window
each one authorises, so an anchor that should not exist still has no reader.
Worth building the day the count changes for a reason nobody remembers — which,
at one per five weeks instead of one per converge, is now a question an operator
can actually be asked.
