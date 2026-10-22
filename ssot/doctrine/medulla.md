---
in_force: false
ruled: null
row: medulla
gates:
  - tests/anatomy/test_estate_status_reports_organ_identity.py
  - tests/anatomy/test_estate_status_symbionts_apart.py
  - tests/anatomy/test_medulla_is_one_static_binary.py
  - tests/anatomy/test_medulla_role.py
  - tests/anatomy/test_medulla_unit_runs_as_nos.py
  - tests/anatomy/test_medulla_serves_metrics.py
---
# Medulla — one binary runs the estate under its own identity

> **PROPOSED** (2026-10-21, roadmap row `medulla`). Not in force until the
> operator rules `in_force: true`. Numbered headings are the addresses; citations keep `§N`.

## 1. What it is

The medulla is one static Rust binary (the Cargo workspace rooted at
`files/anatomy/thalamus/`, members `thalamus`, `contract` and `medulla`; the rename
of that directory to `files/anatomy/medulla` is a later row the operator rules on). It is one process with std threads; no
async runtime until one is measured to be needed. It runs the host organs under
its own identity, not the operator's, and its CLI subcommands replace
`wing/bin/*.php`.

## 2. Operator rulings, 2026-10-21

- The organ is named **medulla**.
- The host bridge is a **thread** of the medulla, with a tiny root-side unit for
  the verbs that need root. It is not a second native daemon. This amends
  containerized-core's order, which put the bridge first as its own daemon.
- Linux gets a dedicated **`nos` system user**; the medulla runs as it.

Default kept from the plan: Bone moves last.

## 3. Absorption order

1. thalamus
2. Pulse's scheduler
3. the host bridge (ssot/doctrine/medulla.md §2)
4. Wing's API, one prefix at a time behind the same `:9000` (ssot/doctrine/medulla.md §5)
5. receptor
6. Bone's API, then the loop engine last

## 4. One database

One `wing.db`, one writer per table, one schema file. While a table moves, PHP
or Rust writes it, never both.

## 5. The strangler seam

A move takes a whole `/api/v1/<prefix>`, never one route of it. Each moved
prefix gets its own Caddy `handle`; whatever is not handled still reaches PHP.

## 6. What stays separate

The face, KEAP, pupil and cortex. Cortex stays TypeScript, and Wing's PHP cortex
executor moves to cortex, not to Rust.

## 7. Never

- a big-bang rewrite
- a UI in the medulla
- porting gates (they stay Python)
- the `nos` user in the `docker` group
- promising isolation on macOS before roadmap row nos-user-macos lands

## 8. The measure

`tools/estate-status.py --identity` prints each self-owned host organ's language,
runtime, run-as user and uid, and one summary line
(`host runtimes: php N, python N, node N, rust N · run as operator N, root N, other N`).
Every later medulla row says which of those numbers it moves. Measured start
(2026-10-21): every self-owned host organ runs as the operator, under `$HOME`.
