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

## Your coding agent and the tables (MCP)

Claude Code, Codex and Cursor speak MCP. `nos-user-setup` registers a stdio
server called `nos-tables` in Claude Code (`claude mcp list`); for another
client point it at `/srv/nos-dgx/bin/nos-tables-mcp`. It exposes one tool,
`nos_tables`, with the verbs `list-tables`, `read-rows`, `get-row`,
`search-rows`, `upsert-row`, `patch-field`, `claim-row`, `release-row` — the
write verbs work only with the RW token, i.e. for maintainers.
