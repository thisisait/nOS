# 61 — Ceilings that do not say they were hit

**Found** 2026-10-17 (release-prep v0.17-beta, harvesting the `ponytail:` comments
added since v0.16-beta); **open** (carried on purpose, each with its upgrade path).

## The fee

Four limits shipped in v0.17-beta answer normally when they are reached. Nothing
fails, and the answer looks complete:

- `files/anatomy/face/src/lib/server/upstream.ts` `keapTableRows`: 40 pages x 500
  rows. A table past 20,000 rows comes back cut, with no marker.
- `files/anatomy/thalamus/thalamus/src/serve.rs` group_by: past 60 groups each
  operation folds its own "other", so that row's count is approximate.
- `serve.rs` reader timeout: the kill goes to the process group. A reader that
  calls `setsid()` escapes it, and in the moment between a late exit and the kill
  the group id could be reused.
- `files/anatomy/thalamus/contract/src/renderers.rs` delta: a JSON null old value
  reads as absent, so "was empty" cannot be said.

## When the bill comes due

The first private table over 20,000 rows (an importer sweep, a ledger); the first
group_by over a field with more than 60 values (a party name, an invoice number);
the first reader that daemonizes itself.

## How it was found

Not by a failure. Each was written down as a `ponytail:` comment when it was built,
and the release harvest (`git log -p v0.16-beta..dev -S'ponytail:'`) collected them.

## What closes it

The upgrade paths in the comments: a truncation marker (or a `truncated: true` the
caller must render) on the page cap; one shared "other" bucket on group_by; a
pidfd-style wait for the reader; a three-state old value in the delta. Each is
small and needs its own gate. Until then the cap has to show when it is hit,
not hide it.
