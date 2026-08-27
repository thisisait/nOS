# The skill library — one shelf, many readers, unequal shares

A **skill** is a procedure written for whoever is holding the tools: "when you
do X in nOS, do it this way". It is the text half of a contract whose other
half is already enforced in code — `nos_app_parser` refuses a manifest that
skips GDPR Article 30 whether or not anybody read a skill about it.

That asymmetry is the point. **A skill never becomes the authority.** It teaches
a reader to arrive at what the gate already demands, so the reader stops
guessing. If a skill and a gate disagree, the gate is right and the skill is a
bug.

## Where the shelf is, and why here

`files/anatomy/skills/<name>/SKILL.md`, beside `plugins/`, `agents/` and
`docs/` — anatomy A1 put agent-facing contracts under `files/anatomy/` and
operator runbooks under `docs/`, and a skill is squarely the first kind.

Before 2026-08-27 there was no shelf. There was **one skill**, living in
`roles/pazny.hermes/templates/skills/nos/SKILL.md.j2`, delivered to exactly one
consumer, owned by the role that happened to write it. It had also drifted: it
told its reader to `cd ~/projects/mac-dev-playbook`, a repository name retired
in the nOS rebrand, in four places. A library of one, addressed to one, and
wrong — which is roughly what you would predict of a document nothing reads back.

## Who gets what

Two kinds of consumer, and they do not get the same shelf.

**`main`** — the harness a human is driving right now: Claude Code, Codex,
Gemini, opencode, the generic `~/.agents/skills`. Main gets **every skill**, and
that is an invariant rather than a list: a new skill is available to the
operator the moment it exists, with nothing to remember to update.

**`agent`** — an autonomous runner: Hermes, OpenClaw, and the AgentKit profiles.
An agent gets **only the skills that name it**. An agent that can do fewer
things wrongly is worth more than one that has read everything, and a
narrow shelf is a narrow blast radius.

Declared in the skill's own frontmatter, because the skill is what knows who
needs it — the same direction as a plugin declaring its wiring rather than a
central table listing every plugin:

```yaml
metadata:
  nos:
    audience: [hermes, openclaw]   # agents that need this one
```

`audience: []` is legitimate and means *operator-only*. It is not "nobody" —
main always gets it — and it is the right answer for anything whose failure mode
is expensive and whose caller should be a person.

## How it reaches a reader

`tasks/skills.yml` symlinks each skill into every consumer directory whose
audience matches. Symlinks, not copies, for the reason Omarchy gives: a copy
becomes a fork the moment upstream changes, and nobody notices which of the six
is stale. The link means every reader is reading this file.

A consumer directory is only linked into **if it exists** or its harness is
enabled. Creating `~/.codex/skills` on a host with no Codex is litter, and
litter that looks like configuration is worse than absence.

## What a skill must carry

- YAML frontmatter with `name`, `description`, and `metadata.nos.audience`.
- **When NOT to use it.** A skill with no refusal clause gets applied to
  everything and stops meaning anything.
- Commands that exist. `prerequisites.commands` is checked by the reader, not
  taken on trust.
- No secret, no token, no password — not even an example-shaped one. Skills are
  world-readable by design and get symlinked into five directories.
- **No moving number.** "47+ containers", "63 plugins", a pending-CVE tally:
  these rot, and a rotted number in a procedure teaches an agent something
  false with full confidence. Name the reader that answers instead
  (`tools/red-status.py`, `tools/rem-status.py`).

## Asking rather than assuming

```bash
tools/skill-status.py          # what is on the shelf, who should hold it, who does
tools/skill-status.py --json
```

It is a reader: it creates no link, repairs nothing, and exits 0 whatever it
finds. A missing link is reported as missing — the repair belongs to a converge.

## The caveat, carried honestly from upstream

Omarchy ships its own skill with a warning worth repeating because it is true
here too: **treat these as experimental — different models will use them to
different effect.** A skill is a prompt, not a program; the gates are what
actually hold.
