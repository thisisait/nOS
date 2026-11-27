# 65 — The medulla answers the edges in its own words

**Found** 2026-11-15 (release-prep v0.19-beta, harvesting the `ponytail:` comments added
since v0.18-beta); **open** (carried on purpose, each with its upgrade path).

## The fee

v0.19 moves thirteen Wing read sets onto the medulla behind `medulla_read_routes`. The
parity gates (`tests/anatomy/test_medulla_serves_*.py`) prove the medulla answers the
requests they replay the way PHP does. Four edges no caller sends today were left different
on purpose, and two observers drop or repeat a record at their edge. Each answers normally:

- **A negative offset or limit is a JSON 500, not PHP's HTML 500.** Same status, another
  body: `medulla/src/security_reads.rs:44`, `remediation_reads.rs:46`, `scan_reads.rs:41`.
- **An array-shaped filter is ignored, where Nette builds a SQL `IN`**: `?type[]=`
  (`events_reads.rs:42`), `?stack[]=` (`hub_reads.rs:46`), `?severity[]=`
  (`notification_reads.rs:39`); `?limit[]=` reads as absent where PHP reads 1
  (`pulse_reads.rs:188`).
- **Security finding members leave key-sorted, PHP's in `created_at` order**, and an
  all-digit id would be an int key in PHP (`security_reads.rs:70`). Ids are UUIDs and the
  one reader counts them, so no answer differs today.
- **A thalamus poller that stops leaves its last count unsaid** (`thalamus/src/serve.rs:1131`):
  the count is written by the next repeat after the quiet window.
- **The immune crawler re-walks git history after a rewrite** (`tools/immune-crawl.py:141`):
  a cursor git no longer knows restarts at the root, so verdicts may repeat.
- **Skill-tree labels are placed by an O(kept × candidates) overlap scan**
  (`face/src/lib/tables/skilltree/labels.ts:250`); fine at today's few hundred labels.

## When the bill comes due

A new caller (a face view, an agent) that sends an array filter or relies on PHP's order
or error page, now that the medulla answers it; a poller whose last burst matters to an
incident; a history rewrite of the repo the crawler watches; a board that keeps thousands
of labels.

## How it was found

Each was named by its builder as a `ponytail:` comment at the site (11-12 … 11-15), and
harvested here by the release-prep sweep. Nothing failed.

## What closes it

Per edge: a parity case in the read set's gate for the array filter and the negative
offset (the gate then says which answer is right); `ORDER BY created_at` on the security
members; a timer thread for the poller count; a crawler cursor kept by commit date, not
sha; a spatial grid for the labels. None is scheduled; the parity cases are the cheapest
and move first if a caller appears.
