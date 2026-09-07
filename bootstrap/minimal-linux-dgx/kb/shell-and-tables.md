---
title: The shell, the tables, the skills
section: start
order: 3
summary: nos dtt, the roadmap seed repo, tokens by group, and the MCP door for your coding agent.
---

## The `nos` CLI

`nos` is on the PATH for everyone. Only its `dtt` verbs matter on this box
(there is no Ansible estate here):

```
nos dtt status                 # the roadmap board: what is doing, next, shipped
nos dtt board                  # the current-state claim board
nos dtt capture --slug my-idea --title "One line" --track platform \
    --task-type design --status next --body "why, what, the gate"
```

`capture` writes one markdown file into your clone of the **seed repo**
(`~/nos-seed`); commit and push it, then `nos dtt seed` files it into the live
table. The file owns title / parent / track / refs / body; the table owns
status and dates (moved by `nos dtt update`). Pushing needs `nos-maintainers`.

## Tokens follow your group

Every login shell sources `/etc/profile.d/nos.sh`, which exports what your
group may read:

| Group | Variables | Meaning |
|---|---|---|
| `nos-users` | `KEAP_API_URL`, `KEAP_AGENT_TOKEN_RO`, `NOS_ROADMAP_TABLE_ID` | read the tables |
| `nos-maintainers` | + `KEAP_AGENT_TOKEN_RW`, `KEAP_PROXY_SHARED_SECRET` | write, seed, run the stack |

A quick read from any shell:

```
curl -s -H "Authorization: Bearer $KEAP_AGENT_TOKEN_RO" \
  $KEAP_API_URL/agent/v1/tables/roadmap/rows | python3 -m json.tool | head
```

## Skills on your shelf

`nos-user-setup` symlinks `/srv/nos/files/anatomy/skills/*` into every AI
harness directory that exists in your home (Claude Code, Codex, Gemini, pi,
OpenCode, Hermes, OpenClaw). Check what landed with

```
python3 /srv/nos/tools/skill-status.py
```

## Your own tables (per user, per project)

Yes, you can — in the browser today. KEAP lets every `nos-users` member
(tier 3) **create their own DataTables** at `https://__HOST__:8443/` (the
Tables page): a table you create is yours, its **Share scope** is *Private
(only you + admins)* by default, and you can open it to *Everyone* in the
tenant. Under the hood KEAP also holds explicit per-person grants
(`sharedWith: [{principal: "user:<login>", access: "read" | "write"}]`),
measured on this box: a private table is invisible to another user (404), a
`read` grant makes it visible and read-only, a `write` grant lets them add rows.

Two honest limits, both roadmap rows:

- **The shell does not know who you are yet.** `nos dtt` talks to KEAP as the
  estate admin and only about the shared `roadmap`, so your own table is a
  browser thing for now. The planned fix (`dtt-per-user-tables`) is an identity
  socket: the shell login becomes the KEAP login, `nos dtt --table <yours>`,
  `nos dtt share --with user:<login>`.
- **Agents see everything.** The agent door (`nos_tables` in chat, MCP in your
  coding agent) authenticates with an estate token and lists *all* tables,
  private ones included (`keap-agent-door-honours-sharing`, a KEAP change).
  Until that lands, do not put anything in a table you would not show to a
  colleague with the same chat.

## The skill that teaches an agent the tables

`nos-datatables` (in the library your shelf links) is the procedure: the two
tables, the two doors, the token tiers, the claim-board etiquette, and the one
hard rule — an agent moves claims, **never** writes a verdict. Your Claude
Code / Codex / Hermes reads it before touching a row.

## Your coding agent and the tables (MCP)

Claude Code, Codex and Cursor speak MCP. `nos-user-setup` registers a stdio
server called `nos-tables` in Claude Code (`claude mcp list`); for another
client point it at `/srv/nos-dgx/bin/nos-tables-mcp`. It exposes one tool,
`nos_tables`, with the verbs `list-tables`, `read-rows`, `get-row`,
`search-rows`, `upsert-row`, `patch-field`, `claim-row`, `release-row` — the
write verbs work only with the RW token, i.e. for maintainers.
