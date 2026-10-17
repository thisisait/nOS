---
id: 2026-10-17-release-v0-17-beta
title: "v0.17-beta — Iris gets a body: a terminal, a window, and a wall between clients"
date: 2026-10-17
namespace: nos-core
summary: "867 commits after v0.16-beta. The Thalamus serves Iris at a terminal and in a native window (the pupil, Iris.app); she reads through KEAP as the person who asked and writes only after that person approves the cell diff. The receptor says who is asking, the septum says for which client. Benches stop crediting a guess, the estate counts what is installed, a blank now leaves a record, and a review found Ollama had been hiding every component kind from Iris. Still -beta by the operator's ruling of 2026-10-16."
tags: [release, iris, thalamus, pupil, receptor, septum, bench, blank]
release: v0.17-beta
actors: [pazny, claude]
related: [RELEASE.md, roles/pazny.thalamus, roles/pazny.receptor, files/anatomy/thalamus, files/anatomy/pupil, tools/iris-bench.py, tools/septum-status.py, docs/hidden_fees/61-ceilings-that-do-not-say-they-were-hit.md, docs/hidden_fees/62-measurements-that-pass-loosely.md]
---

`v0.17` was meant to drop `-beta`. On 2026-10-16 the operator ruled that it stays:
the maturity exit criteria (the restore drill, UC13) are not met, and a name
should not claim what the evidence does not.

The blank ran on the operator host on 2026-10-17, 12:34–13:03 UTC, at
`v0.16-beta-862-g17b5b64f`: `nos --remove=data --confirm`, then the converge.
PLAY RECAP ok=1443 changed=352 failed=0, the smoke inside it 32/32, and the
blank record closed `failed: false`. `tools/nos-smoke.py --strict` afterwards:
32/32 OK. The strict run is not in the record yet (`smoke_strict: null`), so
`tools/estate-status.py` still says the release gate is unmet — the reader is
right about what it can see.

Second host (an M1 Max Mac, macOS 27.0.1) converged the pre-release (`30e96791`): PLAY RECAP ok=748 changed=46 failed=0, `tools/nos-smoke.py --strict` 8/8 OK.

## Iris at a terminal

Iris, the end user's caddy, lived in benches. The Thalamus
(`roles/pazny.thalamus`, a Rust relay) gives her a daemon and a `ratatui` shell.
Her tools run as the person through KEAP's human door, and every call lands in
one ledger with one writer. The rule the whole organ is built around: **a write
lands only when the person approves its cell diff** — an edit, an insert with its
line items, a delete, a new table or new columns, one card each. The row is
re-read before the write and the approved fields are read back.

Late on the 17th Iris got two cloud rows, `anthropic-api` and `minimax-api`,
both non-EU. That needed a gate change, accepted by the operator and committed
on its own (`647fe3a3`): gate 8 now follows `gdpr_posture`, so a non-EU row
binds only at posture `none`. Wing's PHP resolver was not changed and still
refuses — a known gap.

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

## What Ollama never showed her

PR #57 reviewed the reasoning core seam by seam: what the model is sent, what
the organ accepts, what the mapper reads. The biggest finding was outside nOS.
Ollama keeps only a handful of JSON-schema keywords in a tool definition and
drops `oneOf`, `const` and `additionalProperties`. `show.component` was a
`oneOf`, so Iris received `component: {}` — she was asked to draw charts without
ever being told a chart exists. The card tools have flat schemas, which is why
writes passed and renders did not. The fix keeps the `oneOf` and adds a kind
enum and the shapes in the description (`85e2576f`), and a gate now checks
every tool property against Ollama's keep-list.

The rest of the review closed one-sided contracts: `show` accepts what its
schema admits, a plan param the mapper would drop is refused, the repair round
hears which stage and key failed, every plan row says which primer and grammar
it was asked under and whether a fallback was the model's fault or the
estate's. The same day the live `hermes3:8b` runs found the plan schema open
enough to put the table in params; it is closed now.

The numbers before any of this (nos-assay, synthetic data, a second host: M1 Max, 32 GB):
`qwen3.5:9b` plain tool calling 68/126 at smoke, 143/284 at standard, with KPI
0/19, choice 0/19 and chart 6/21; `hermes3:8b` 28/126; the first live cortex
plan run 1/14. Those are the baseline. Nothing after #57 has been measured, so
nothing is claimed.

## What is installed is what is counted

Authentik, the hub, Pulse, the scanner, the smoke and the backup list the
installed set instead of hand lists. `profiles/core.yml` is the smallest working
nOS. And a confirmed blank now writes `~/.nos/blank-runs.jsonl`, the record this
release's own gate reads. Its first gap — a failure after the smoke still
recorded the blank as passed — was closed the same week: a callback closes the
record with the play outcome (`1bcb16ce`). The blank also showed the live
password prefix as a prompt default; the prompt no longer shows it
(`fc4c3525`).

## Still open

Iris is off by default until the operator proves her live. The Bonus CI lanes
have had no green run since 2026-10-10. A Pulse job rewrites committed fixtures
in the repo checkout (row `pipeline-exercise-writes-checkout`).
