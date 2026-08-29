# 32 — The dashboard counted finishing as succeeding

**Found 2026-08-29, while building a second dashboard beside it.**

`22-ai-agents.json` has carried a stat panel called **Success rate** since it
shipped. Its query:

```sql
SELECT ROUND(100.0 * SUM(CASE WHEN status = 'idle' THEN 1 ELSE 0 END) / COUNT(*), 1)
  AS success_rate FROM agent_sessions
```

`status = 'idle'` is AgentKit's word for *the process is no longer running*. It
is set when a session ends, and it is set the same way whether the agent
produced its deliverable, produced nothing, or hit a ceiling mid-sentence. The
column that records whether anything was achieved is `outcome_result`, written
by the oracle — `satisfied`, `needs_revision`, or NULL when no verdict was ever
reached.

Measured against the live ledger, 55 sessions:

| the question | the figure |
| --- | --- |
| `status = 'idle'` — the panel's | **72.7 %** |
| `outcome_result = 'satisfied'`, ended runs only | **20.0 %** |

Eighteen sessions ended with no outcome at all. Every one of them was being
counted as a success, on the surface an operator glances at to decide whether
the agents are working.

## Why nothing caught it

Because there was nothing wrong with it. The SQL is valid, the column exists,
the panel renders, the number is plausible and it moves when the estate moves. A
gate that executes every dashboard query — which now exists,
`test_a_dashboard_panel_asks_a_question_that_runs.py` — passes this panel
happily, and says so in its own docstring. **No gate reads questions.**

That is the fee's actual shape, and it is not really about Grafana. The estate
has spent months closing "absence read as success" in code, where a reader can
be pointed at an artifact. A dashboard panel is a claim in *natural language*
("Success rate") bound to a claim in SQL, and nothing compares the two. The
binding is a human's memory of what they meant, six weeks ago.

## The neighbouring finding

The same gate, on its first run, reported `40-e2e-journeys.json`: on disk since
2026-05-07, documented in `docs/e2e-tester-identity.md` as *"surfaces in Grafana
dashboard 40-e2e-journeys"*, and never added to `plugin.yml`'s `files:` list —
so the loader has never copied it to a host. Four months of a dashboard that
exists in review and not in the estate. Both are now listed and both are gated.

## What was done, 2026-08-29

The panel asks the honest question and says so in its own description; its title
is now *"Runs an oracle called satisfied"*, which cannot be read as a
process-completion metric. The new `25-loop.json` renders the loop's own tables
and carries the same distinction as a column named `ended_with_no_verdict`,
because the number that mattered here deserves to be visible rather than
inferred from a rate.

**Not closed:** nothing checks that a panel's title matches its query, and this
entry does not pretend to know how it could. What is cheap and was done instead:
every panel whose title makes a claim now carries a `description` stating what
the SQL actually counts, so the reader who doubts a number has the answer in the
tooltip rather than in the JSON.
