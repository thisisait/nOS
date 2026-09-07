---
name: nos-datatables
description: Work with the nOS DataTables (the roadmap and the current-state claim board in KEAP) as an agent — read the board, file a row, claim and release work, never write a verdict. Covers the `nos dtt` CLI, the `nos_tables` MCP tool and the token tiers.
metadata:
  nos:
    audience: [hermes, openclaw]
    platforms: [macos, linux]
    requires: [nos, python3]
---

# nOS DataTables — the working surface

nOS tracks its work in two KEAP DataTables, not in prose files:

| Table | What a row is | Who writes |
|---|---|---|
| `roadmap` | the durable PLAN: releases, epics, tasks, fees, observations, self-nesting via `parent` | a human or an agent files it; a maintainer moves its **claim** (`status`); a **probe** writes its **verdict** (`verified`) |
| `current-state` | the live CLAIM BOARD: units of work that need doing, expressed as `nos-work://` address components; an agent claims one, works, releases | agents, through `nos dtt claim/release/progress` or `nos_tables claim-row/release-row` |

Two columns on `roadmap` are separate **on purpose** and you must never conflate
them: `status` is what someone claims (`next`, `doing`, `review`, `shipped`, …);
`verified` is what an independent probe observed (`confirmed`, `contradicted`,
`unverifiable`). An agent may move a claim. **An agent never writes a verdict.**
The estate's most expensive recurring defect is a success marker written by the
code that attempted the work.

## Two doors, one contract

1. **The CLI** — `nos dtt <verb>` runs the tools from the runtime checkout over
   your clone of the private seed repo (`NOS_SEED_DIR`, default `~/nos-seed`):

   ```
   nos dtt status                                   # the roadmap board
   nos dtt board                                    # current-state: assignments, claims, who is capable
   nos dtt capture --slug <kebab> --title "<one line>" --track <platform|security|agents|cortex|face|release|filesystem> \
       --task-type <investigate|design|code-fix|seed-edit|review|doc|security-remediation|converge> \
       --status <next|queued> [--parent <slug>] --body "<the prose>"
   nos dtt seed [--dry-run] [--sync]                # file the seed repo's new rows into the live table
   nos dtt update --slug <slug> --status doing|review|shipped [--owner <who>]   # move a CLAIM
   nos dtt claim <slug> · nos dtt progress <slug> working|blocked|review|done · nos dtt release <slug>
   ```

   `capture` writes ONE file `<slug>.md` into the seed repo; commit and push it
   there (never into nOS), then `seed`. The file owns `title/parent/track/refs/body`;
   the table owns `status`, dates and `verified*`. Do not hand-edit a row's
   table-owned half in the file — `--sync` reconciles only the git-owned half.

2. **MCP** — the `nos_tables` tool (server `tools/mcp-tables-server.py`; in
   Claude Code it is registered as `nos-tables`). One tool, verb-shaped input:

   | verb | plane | use it for |
   |---|---|---|
   | `list-tables` | read | what tables exist |
   | `read-rows` `{table}` | read | the whole board of a table |
   | `get-row` `{table, id}` | read | one row by id (roadmap: id == slug) |
   | `search-rows` `{table, query}` | read | find a row by text (confident-match floor) |
   | `upsert-row` `{table, row}` | write | file or update a row (`slug` is the key) |
   | `patch-field` `{table, id, field, value}` | write | move ONE field, e.g. `status` |
   | `claim-row` / `release-row` `{table, id}` | write | take / hand back a current-state assignment (a lease, not ownership) |

   Write verbs need the RW token; read verbs the RO token. If a write answers
   401/403, you hold the reader tier — say so, do not retry with another token.

## Tokens follow the tier you were given

`KEAP_API_URL`, `KEAP_AGENT_TOKEN_RO` (readers) and additionally
`KEAP_AGENT_TOKEN_RW` (maintainers) arrive in your environment. Never print
them, never paste them into a row body, never look for them in files you were
not pointed at.

## Etiquette on the claim board

- Claim before you work; release when you stop, even on failure — a stale
  lease blocks the next agent until it expires.
- Match yourself honestly: the board says who is *capable* of an assignment
  (`task_type` × where × scope). If the match says you are not, file a note
  instead of claiming.
- One row, one change, one reason. A row body that another agent can build
  from: the measurement, the gap, the structural approach, the gate that will
  pin it.
- Prefer `patch-field` on `status` over `upsert-row` for a state change; upsert
  replaces the git-owned half and is for filing.

## When NOT to use

- Not for prose planning documents — the operator directive is that new work
  is DEFINED in dtt; if you are about to write `docs/plans/*.md`, file a row.
- Not for the estate's other KEAP tables (face layouts, business fixtures,
  caddy sessions): they have their own owners and seeders.
- Not for a verdict, a probe or a gate result — those come from
  `roadmap-verify.py` and `state/roadmap-probes.yml`, never from an agent.
- Not when you hold no token: without `KEAP_AGENT_TOKEN_RO` in the
  environment you are outside the estate; ask, do not go looking.

## Never

- Never set `verified`, `verified_by`, `verified_at`, `evidence` — those are a
  probe's (`roadmap-verify.py`, `state/roadmap-probes.yml`).
- Never delete a row. Rows are history; a wrong row is moved to `dropped`.
- Never write to a table you were not told about; `list-tables` shows more than
  you are meant to touch (face layouts, business fixtures, and — until KEAP
  row `keap-agent-door-honours-sharing` lands — users' PRIVATE tables, which
  the agent bearer can see but was never granted). Treat a table you were not
  named as someone else's, whatever the door returns.
