# 62 — Measurements that pass loosely

**Found** 2026-10-17 (release-prep v0.17-beta, `ponytail:` harvest since v0.16-beta);
**open** (carried; the benches still report honestly at today's case set).

## The fee

The benches and the CI split added this release measure a little less than they
appear to:

- `tools/local-model-bench.py` `intent_ok`: expected params are matched anywhere in
  the chain, not on the opcode's own stage. Two stages sharing a param name in one
  task would pass a wrong plan.
- `tools/iris-bench.py`: the ledger is not sliced per turn, so a multi-turn case
  without a plan goes unjudged (it reports NO-DATA, not a pass, since `18f78a4f`);
  `rowRef` resolves one level only.
- `tests/_shard.py`: the four pytest shards are balanced by test count, not duration.
- `.github/workflows/ci.yml`: the Bonus per-stack and all-on jobs copy the setup
  of `integration-linux`. A fix to one copy does not reach the others.

## When the bill comes due

A bench task where two stages share a param name; a slow test file landing in one
shard; the next toolchain change to `integration-linux` that the Bonus copies miss,
so a Bonus lane fails (or passes) for a reason the blocking lane no longer has.

## How it was found

Written down as `ponytail:` comments when built; collected by the release harvest.

## What closes it

Parse the chain (the cortex AST) instead of a regex in `intent_ok`; slice the ledger
per turn; weigh shards by recorded durations once CI keeps a junit artifact; a
composite action for the converge-job setup, used by all three jobs.
