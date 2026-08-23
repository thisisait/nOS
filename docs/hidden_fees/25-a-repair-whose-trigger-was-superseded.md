# 25 — A repair whose only trigger was superseded by a reader

**Found 2026-08-23, chasing a red that had been standing for four days.**

```
agent session surveyor ae3b3024 still 'running' after 110.3 h
  — trigger=operator, model=anthropic-claude-sonnet-4-5; no run can close it now
```

The reaper for exactly this existed and was correct. It was written on
2026-06-10, right after **five orphaned `running` rows were hand-cleaned in a
single day**:

```php
public function terminateStale(int $capMinutes): int   // AgentSessionRepository
```

It had one caller — `AgentsPresenter::renderDefault()`, Wing's `/agents` page —
with its reasoning written down, and the reasoning is the interesting part
because it reads perfectly well:

> Lazy stale-session reaper — every catalog view sweeps orphaned `running` rows
> past the cap, so dead runs self-clean without a dedicated cron
> (**the page where orphans annoy is the page that clears them**).

## The fee

That last clause was true, and then the estate improved and it quietly stopped
being true.

`tools/red-status.py` shipped **2026-08-18** — the "what is red right now"
reader CLAUDE.md now tells every session to start with. Orphaned sessions are
one of the things it reports. And it is a **reader**: it may not write, on
purpose, because half this estate's expensive defects were a marker written by
the code that attempted the work, and `test_the_red_reader_only_reads.py` pins
that it stays that way.

So the annoyance moved to a surface that **must not act**, and the repair stayed
on a surface **nobody had opened in four days**. Detection got better; repair
got quieter; the net was worse. Nothing broke, nothing changed, no commit did
it — a sentence about human attention stopped being accurate.

## What it cost, and the detail that makes it sting

110 hours of a red that the estate could have cleared itself, in a reader an
operator is instructed to run first — which is precisely where a stale red is
most expensive, because it teaches you to skim.

And: **a later surveyor run started beside the orphan, finished, and went idle
without touching it.** The reaper had a live opportunity on 2026-08-21 and no
one had thought to give it that trigger, because in June the page WAS the
trigger and there was nothing else.

## What closes it

`terminateStale()` is now also called at session **open**, on both runtimes —
`startSession()` (the PHP runner) and the `agent_run_start` branch of
`syncFromAgentEvent()` (the claude-CLI bridge).

**A successor closes what its predecessor could not.** That is the right
authorship and it is the same rule the estate applies everywhere else, read from
the other end: the row that says "this run died" is written by something
demonstrably alive, never by the run itself.

Both runtimes, and not for symmetry — **the 110-hour orphan arrived on the
claude-CLI path**, so reaping only in the PHP runner would have left exactly the
observed case uncovered.

The cap moved from `AgentsPresenter` to the repository, because a policy defined
by one of several callers drifts. The lazy page-view call stays: it is a free
extra chance, and it is the only path that *tells* the operator a reap happened.

Gate: `tests/anatomy/test_a_dead_session_is_closed_by_a_successor.py` — both
paths reap, and reap **before** they insert, so a session can never become a
candidate for its own reaper. Proven in the failing direction.

## The general shape, which is why this is a fee and not a bug

**A repair triggered by a human looking at something is coupled to the reason a
human looks.** Improve the observation surface and you can silently remove the
trigger, without touching the repair, without a failing test, and without
anything in the diff to notice.

Worth checking wherever else "the page that shows it is the page that fixes it"
was the design. That reasoning is fine as an *extra* trigger and unsafe as the
only one.

## What is still owed

- **The existing orphan is still open.** The fix ships in Wing's source; it
  reaches the daemon on the next converge, and the row closes on the first agent
  run after that. Until then `red-status` is right to keep saying so.
- **`stop_reason` is `interrupted` for both an operator kill and a reap** —
  they differ only by `error_json.by`. Pre-existing, and it means the timeline
  cannot cheaply tell "someone stopped this" from "nobody was there".
- **No audit of other lazy repairs.** This one was found by chasing its symptom,
  which is exactly how the fees corpus says these get found, and is not a method.
