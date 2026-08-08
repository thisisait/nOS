# nOS roadmap

**The roadmap is a table, not a document. Ask it:**

```bash
tools/roadmap-status.py              # the tally, and everything in motion
tools/roadmap-status.py --all        # every row, nested under its parent
tools/roadmap-status.py --track face # one track
tools/roadmap-status.py --schema     # what the git definition declares vs what the table has
```

It reads the live `nOS Roadmap` DataTable in KEAP. If KEAP is down it exits 2 and
says so — an unreachable roadmap must not render as an empty one.

| surface | holds | where |
|---|---|---|
| `nOS Roadmap` DataTable | dates, statuses, nesting, citations | KEAP · written by `tools/roadmap-seed.py` · defined by `state/keap-tables/roadmap.table.yml` |
| [`docs/idea/`](idea/00-index.md) | why, what is true, what is open | git, ceiling of twenty |
| [`docs/hidden_fees/`](hidden_fees/) | costs paid without a decision | git |
| `docs/archive/` | what happened, and what never did | git |

## Why this file is four screens instead of six hundred lines

It was six hundred and thirty-eight, and by 2026-08-07 it was **two releases
behind its own mermaid chart** — "Now: v0.9-beta staging", written while
v0.10-beta was tagged. That was diagnosed on 2026-08-02 in
[`docs/idea/10-roadmap-surface.md`](idea/10-roadmap-surface.md) and nothing
happened for five days, because a document that has to be rewritten by hand to
stay true will not stay true.

The measurement that settled it: of the workstreams the estate was actually
running that week — SERE, the genome and its organelles, hydrators, cortex-lang,
the Planner, the relations graph, the hidden-fee ledger — this file mentioned
**none**. Not one, in 638 lines that opened by calling themselves "the single
forward-planning surface". Meanwhile the table carried a row for each.

The old text is preserved verbatim at
[`docs/archive/roadmap-2026q3.md`](archive/roadmap-2026q3.md). It is history now,
and it is worth reading as history: the "Shipped this session" sections are a
good record of May–July 2026.

## What v1.0 means

This is the one thing the prose roadmap held that lives nowhere else, so it stays
here. A row in the table can point at a criterion; no row can *be* the
definition of done.

**v1.0 is the general self-hosted platform reaching production-trust for a
single-operator home lab.** It is NOT gov-readiness (ISDS / NIA / eIDAS /
retention enforcement stay a profile-gated post-1.0 track) and NOT full Linux
parity (OpenClaw, Hermes and fleet provisioning are post-1.0).

1. **Security floor** — zero CRITICAL/HIGH pending on a fresh full scan
   (`tools/rem-status.py`). Vendor-blocked FreePBX is a documented accept-risk
   with `install_freepbx: false` by default.
2. **Reproducible blank** — `nos --remove=data --confirm` installs the known-good
   profile end-to-end `failed=0`, every container healthy, on a genuinely clean
   host. This is the core nOS invariant and must be re-proven at the RC.
3. **Epic acceptance exercised on real workloads** — a same-org upgrade applied
   live; a real migration authored *and* applied; one coexistence cutover
   completed end to end (PG 16→17). These prove the frameworks, not their tests.
4. **CI green including the gating Integration wet-test** on both lanes. The
   Linux lane must actually prove the playbook — see
   [`docs/hidden_fees/08`](hidden_fees/), where it passed an empty stack as
   `0/0 ready`.
5. **Healthcheck coverage** — STRICT `wait-stacks-healthy` gates *every* service,
   with no booted-but-broken container passing as `running=ready`, and no check
   that cannot execute counted as a check.
6. **One work surface, and it is asked rather than copied.** The table is
   reachable, its git definition is applied to it, and no document restates a
   number the estate can answer.
7. **Feature freeze** on the beta service surface during stabilization.

Criterion 6 is not met today, and the gap is precise:
`state/keap-tables/roadmap.table.yml` declares 23 columns, the live table has 9,
and **nothing applies the definition** — the playbook seeds only the three
`face-*` tables. The `verified` column, whose entire purpose is to let a row say
*someone claims this shipped and a probe disagrees*, exists in git and not in the
database. `tools/roadmap-status.py --schema` prints the diff;
`tests/anatomy/test_the_roadmap_declares_the_table_it_fills.py` keeps the two git
artifacts from drifting further apart while that is true.
