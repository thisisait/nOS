---
id: 2026-10-17-release-v0-17-beta
title: "v0.17-beta — Iris gets a body: a terminal, a window, and a wall between clients"
date: 2026-10-17
namespace: nos-core
summary: "814 commits after v0.16-beta. The Thalamus serves Iris at a terminal and in a native window (the pupil, Iris.app); she reads through KEAP as the person who asked and writes only after that person approves the cell diff. The receptor says who is asking, the septum says for which client. Benches stop crediting a guess, the estate counts what is installed, and a blank now leaves a record. Still -beta by the operator's ruling of 2026-10-16."
tags: [release, iris, thalamus, pupil, receptor, septum, bench, blank]
release: v0.17-beta
actors: [pazny, claude]
related: [RELEASE.md, roles/pazny.thalamus, roles/pazny.receptor, files/anatomy/thalamus, files/anatomy/pupil, tools/iris-bench.py, tools/septum-status.py, docs/hidden_fees/61-ceilings-that-do-not-say-they-were-hit.md, docs/hidden_fees/62-measurements-that-pass-loosely.md]
---

`v0.17` was meant to drop `-beta`. On 2026-10-16 the operator ruled that it stays:
the maturity exit criteria (the restore drill, UC13) are not met, and a name
should not claim what the evidence does not.

PENDING: blank 2026-10-17 — the converge result and `nos-smoke --strict`.

## Iris at a terminal

Iris, the end user's caddy, lived in benches. The Thalamus
(`roles/pazny.thalamus`, a Rust relay) gives her a daemon and a `ratatui` shell.
Her tools run as the person through KEAP's human door, and every call lands in
one ledger with one writer. The rule the whole organ is built around: **a write
lands only when the person approves its cell diff** — an edit, an insert with its
line items, a delete, a new table or new columns, one card each. The row is
re-read before the write and the approved fields are read back.

## Iris in a window

The pupil (Tauri, installed as `Iris.app`, built and signed on the host) draws
what the shell draws: tables, records, six chart kinds, timelines, graphs,
sequence diagrams, before/after change markers, forms that submit through the
same approval. Keeping dashboards in KEAP was built and reverted in the same
week; a placed dashboard stays on the Mac.

## Who is asking, and for whom

The receptor maps a host login to a person for KEAP's door; OpenHuman reads the
tables through it. The septum is the wall between clients: tables carry a
`client_scope`, producers stamp `book_owner`, and reads, memory and the approval
card honour it. `tools/septum-status.py` shows orphan and unstamped rows as red.

## A bench that does not credit a guess

Most fixes in the bench were about honesty: a guess is not "cannot see", a
fabrication is not credited, a rate-limited run or an unjudged case is NO-DATA.
What the benches still measure loosely is written down as hidden fee 62; four
runtime limits that answer normally when they are hit are fee 61.

## What is installed is what is counted

Authentik, the hub, Pulse, the scanner, the smoke and the backup list the
installed set instead of hand lists. `profiles/core.yml` is the smallest working
nOS. And a confirmed blank now writes `~/.nos/blank-runs.jsonl`, the record this
release's own gate reads. Its first known gap is already a roadmap row: a
failure after the smoke still records the blank as passed.

## Still open

Iris is off by default until the operator proves her live. The Bonus CI lanes
have had no green run since 2026-10-10. A Pulse job rewrites committed fixtures
in the repo checkout (row `pipeline-exercise-writes-checkout`).
