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

Every `nos-users` member (tier 3) can **create their own DataTables** — in the
browser at `https://__HOST__:8443/` (Tables → *Share scope*), and from the
shell, **as yourself**:

```
nos dtt tables                                          # what you can see, and whose it is
nos dtt create-table "Project X"                        # private, roadmap-shaped (columns, view)
nos dtt --table "Project X" status                      # every verb works on your table
nos dtt --table "Project X" capture --slug px-1 --title "First task" --track platform --task-type design --status next --body "…"
nos dtt --table "Project X" seed                        # from ~/nos-tables/<table-id>/ — its own seed files
NOS_DTT_SEED_DIR=~/projects/x/seed nos dtt --table "Project X" seed   # or a seed repo per project
nos dtt share "Project X" --with user:svp2bj --access read      # or write, or none to revoke
nos dtt visibility "Project X" shared                   # everyone in the tenant may read
```

How the shell knows who you are: an **identity outpost** on a unix socket
identifies the caller by uid (the kernel says who connected), maps your Linux
groups to the tier (`nos-users` → tier 3, `nos-maintainers` → tier 1) and
speaks to KEAP on your behalf. No password prompt, no token in your files, and
the same identity the browser gets through the PAM login — so a table private
to you is private in both places, and a grant you give is visible in both.
Consequence you will notice: `nos dtt status` on the shared roadmap now needs
the tier the roadmap asks for (`tier-managers`); a tier-3 user reads it in
Chat via the `nos_tables` tool or asks a maintainer to open it.

**Agents still see everything.** The agent door (`nos_tables` in Chat, the
estate token) lists *all* tables, private ones included, until KEAP row
`keap-agent-door-honours-sharing` lands. Your own Claude Code / Codex on this
box uses the identity socket and sees only what you see; the shared Chat tool
does not. Do not put anything in a table you would not show to a colleague.

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
