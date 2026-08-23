# 22 — A probe that could never pass

**Found 2026-08-23, while asking the roadmap what to do next.**

`sec-rem` is the roadmap's only row for the open HIGH findings, and the roadmap
is what dictates the order of work here. Its probe:

```
test "$(python3 tools/rem-status.py | grep -c 'HIGH ')" -eq 0
```

`rem-status.py` renders for a person. Six of its lines match `HIGH ` today:

```
 3:  pending by severity: 2 HIGH · 26 MEDIUM · 19 LOW
 4:  6 CRITICAL/HIGH are BLOCKED, not fixed — no upstream remedy exists:
10:    REM-126   HIGH      ollama         mitigated
13:  REM-214   HIGH     openwebui      …
14:  REM-217   HIGH     mariadb        …
16:  +45 pending below HIGH — `--all` lists them.
```

Two are the open findings the row is about. Line 10 is a `vendor-blocked` row
with a recorded disposition — not open work. Lines 3, 4 and 16 are headings, and
they survive every state of the queue.

**So the count could not reach 0 with every HIGH closed.** The row has read
`contradicted` since the day it was filed and would have gone on reading
`contradicted` after the work was done. A verdict that cannot move is not a
verdict.

## The shape, which this estate has paid for before

CLAUDE.md already records one: the `master` ruleset requires signed commits,
every commit is unsigned, and the admin bypass logs `Found 188 violations` on
every release. *"A gate that only ever reports its own defeat."* Same object
here, one layer in — and worse, because `verified` exists specifically so it can
disagree with `status`. A column pinned to one value is a second copy of nothing.

The catalogue had already been caught twice in the other direction:
`test_a_probe_cannot_match_its_own_description.py` closed *a probe that reads
the PLAN and reports it as the work* (five rows, including `sec-p1` matching the
seeder that authored its own row) and *a probe that cannot fail*. This is the
mirror image, and nothing was watching for it.

## The reader had the answer the whole time

`rem-status.py --json` carries `pending_by_severity`, which excludes
`vendor-blocked` by construction and goes to `{}` on a clean queue:

```
test "$(tools/rem-status.py --json | python3 -c "…
  s['pending_by_severity']; print(s.get('CRITICAL',0)+s.get('HIGH',0))")" -eq 0
```

Exits 1 today with the two real HIGHs, and 0 when they close. Falsifiable in
both directions, which the old one was not in either.

## The second defect in the same row

The title was **`Open HIGHs — REM-152 n8n 17-GHSA wave`**. REM-152 closed. The
row was still correct — HIGHs are still open — but its title named an instance
rather than the condition, so it read as stale work while tracking live work.

Retitled to `Open HIGHs — no HIGH stays pending without a disposition`. The
distinction is worth keeping: **a row is a condition; a finding is an instance.**
When the instance closes, a row named after it lies.

Its body is worse and is not fixed here — `Cycle-21, 15 pending, 0 CRITICAL`,
now cycle 37 with 47 pending. `roadmap-update.py` has no `--body` flag by design
(the body is the evidence at filing time, not a live field), so the honest read
is that a body carrying a **tally** was the wrong thing to write, not that the
tool is missing a writer. Same rule CLAUDE.md applies to its own backlog line:
*this line no longer carries the numbers.*

## Gated

`tests/anatomy/test_a_probe_asks_the_machine_half.py` — if a probe decides by
COUNTING a repo reader's output, that reader must have been asked in its machine
mode, when it has one. Conditional on purpose: where no `--json` exists there is
no better option, and a gate demanding one would be asking for a tool rather
than for a correct probe.

Proven both ways: green on the fixed catalogue, and it names `sec-rem` when the
old probe is put back.

**And it caught itself first.** The first cut split the command with `shlex` and
passed the very probe it was written for — because `shlex` reads all of
`"$(python3 tools/rem-status.py | grep -c 'HIGH ')"` as **one token**, so
`tools/rem-status.py` never appeared as a token at all. A detector that cannot
see inside a command substitution cannot see the shape that hides there. It now
reads the raw string.

## What is still owed

- **Nothing checks that a probe is DECISIVE.** `test -f README.md` is scoped
  correctly, cannot match the plan, is not trivially true, is not a prose count
  — and proves nothing about any row. Three gates now fence the catalogue and
  none of them can read intent.
- **46 open roadmap rows carry a number in title or body.** Most are legitimate
  — a body is filing evidence, and the measurement that motivated a row is worth
  keeping. The failure is only when a number is read as current state. No gate
  can tell those apart, and one that tried would delete the useful case.
