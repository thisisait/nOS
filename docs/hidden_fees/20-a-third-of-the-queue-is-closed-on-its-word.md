# 20 — A third of the queue is closed on its word

**Found 2026-08-22, while trying to fix a different problem that turned out not
to exist.**

`docs/llm/security/remediation-queue.json` holds 212 findings. 155 are closed.
**50 of those 155 carry no evidence of any kind** — no `resolved_by`, no
`resolution`, no `resolved_detail`, no `blocked_reason`, no `decision`. Just a
status and, usually, a date.

48 are `resolved`. Among them:

```
REM-001   CRITICAL  resolved   portainer   closed 2026-05-31
REM-015   CRITICAL  resolved   traefik     closed undated
REM-043   CRITICAL  resolved   n8n         closed 2026-06-06
REM-051   CRITICAL  resolved   n8n         closed undated
REM-052   CRITICAL  resolved   n8n         closed undated
```

## The fee is not the missing prose. It is that nobody has to believe it.

`tools/rem-status.py` reports `145 resolved`. `docs/doctrine/loops.md` and the
weakness reader treat a resolved row as work that no longer exists. Every
downstream count — the severity floor, the drift watcher, the loop's own entry
half — subtracts these rows from the estate's exposure story, and for a third of
them there is nothing to check against.

CLAUDE.md already records the cost in the other direction: twelve pending rows
were found to be **already live at their fix version**, and REM-178 found a
recorded fix *below* what the estate runs. The queue has a measured history of
being wrong about state in both directions. A closure with no evidence is that
same class, pre-armed.

## What it cost, once, legibly

REM-144 (traefik dashboard, CRITICAL) is the worked example, and its own
`resolved_detail` narrates it:

> LIVE-VERIFIED 2026-08-04 (the record carried a bare status+date until then,
> with no resolved_by and no evidence — which is how a reader on 2026-08-04 …)

A CRITICAL sat marked resolved for five days with nothing behind it, and a reader
had to re-derive the whole question from the running estate to find out whether
it was true. It was. That is luck, not process.

## The correction this replaces

The roadmap row `sec-queue-authorship` says the nightly scan **overwrites** what
a human wrote, and cites REM-144 as the incident. That premise is false, and it
was worth an hour to find out rather than an afternoon to build against.

Replaying all 75 commits that have ever touched the queue and diffing
`resolved_by` / `resolved_detail` / `resolution` for every row across every
consecutive pair: **zero dispositions have ever been lost.** The scanner's prompt
(`files/vuln-scan/scan-runner.sh:120-135`) is advisory — *"Append findings to
existing files… Read existing findings first to avoid duplicates"* — and it is
prose an LLM reads at 02:00, not a schema constraint. That remains a real
structural weakness. It has simply never fired, and building the companion-file
split it implies would have taught every reader to join two files in order to
protect against something that has not happened.

The thing that HAS happened, fifty times, is closure without evidence.

## Fixed

- `tools/rem-status.py` now counts unproven closures in its default output and
  names them under `--unproven`.
- `tests/anatomy/test_a_closed_finding_carries_its_evidence.py` ratchets the
  count at 50. It cannot go up.

**A ratchet, not a target, and deliberately.** Fifty rows cannot be repaired by
inventing evidence — the runs that closed them are months gone, and a gate
demanding retroactive proof would be satisfied by fiction, which is worse than
the silence it replaces. The estate chose this shape once before for the same
reason (`sec-p4`, "ratchets not targets"). A second gate refuses ratchet slack:
if the count drops and the ceiling does not, the gate says so, because a ceiling
far above the real number quietly re-licenses the gap it closed.

## What is still owed

- **The scanner's write path is still prose.** Nothing structurally stops the
  02:00 run from dropping a disposition; it just never has. If it ever does, the
  companion-file split is the answer and this file is the record of why it was
  not built pre-emptively.
- **`status` has two authors and no arbiter.** The scanner writes it and so does
  the operator. That ambiguity is what makes "who closed this" unanswerable for
  the fifty, and it is not fixed here.
- **The fifty are not triaged.** They are named, counted and pinned. Deciding
  which deserve a re-verification pass — the CRITICALs first — is operator work,
  and `tools/discovery-scan.py` already answers the version half of it for any
  row whose component is running.
