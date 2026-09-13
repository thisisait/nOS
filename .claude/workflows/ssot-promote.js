export const meta = {
  name: 'ssot-promote',
  implements: 'ssot-recite-doctrine',
  description:
    'Promote docs/doctrine/*.md into ssot/doctrine/ one file at a time. Light reformulation. Section numbers stay. Warehouse cleanup of the rest of docs/ is a later wave.',
  isolation: 'worktree',
  writes: 'branch',
  phases: [
    { title: 'Harvest', detail: 'ssot/ is in the citation corpus; stubs alias sections (sequential, already in tree)' },
    { title: 'Promote', detail: 'union: one live doctrine file per agent; stubs only in docs/doctrine; no README' },
    { title: 'Judge', detail: 'parent updates README; heading + cite gates. v1 promote landed except agentkit/organs. docs/ warehouse cites articles; it is not this phase' },
  ],
}

const P = `You are a lazy senior nOS developer.

ISOLATION: git worktree + feat/ssot-promote-<name> off the SHA in this prompt.
Commit there. Do NOT push. Do NOT touch ~/projects/nOS. Do NOT merge.

ONE FILE. You receive NAME.md. You write:
- ssot/doctrine/NAME.md (the article)
- docs/doctrine/NAME.md (stub only)

Do NOT edit: README.md, INDEX.yml, tools/doctrine-cite.py, other doctrine files,
docs/llm/security/*, apex ruling.yml, agentkit.md, organs.md.

STABLE SECTION NUMBERS. A ## 3 that was 3 stays 3. Renaming a number is a
breaking citation change. Light reformulation: shall/must/may; drop session
anecdotes ("an agent said"). Keep the rule. Incidents that justify the rule
may stay as one measured sentence with a path, or move to an already-linked
companion. Do not invent a new companion. Do not settle proposed files.

Stub exactly:

# <original H1 text>

Moved to [\`ssot/doctrine/NAME.md\`](../../ssot/doctrine/NAME.md).

pytest: tests/anatomy/test_ssot_index.py tests/anatomy/test_doctrine_headings_are_unique.py
Conventional Commits, subject ≤ 50 chars.
`

phase('Promote')

// FAN-OUT: union. Each agent writes one pair (ssot/doctrine/X + stub).
// README and the harvester are sequential and owned by the parent.
const promoted = await parallel([
  () => agent(`${P}\nNAME.md = ponytail.md`, { label: 'promote-ponytail', phase: 'Promote' }),
  () => agent(`${P}\nNAME.md = gates.md`, { label: 'promote-gates', phase: 'Promote' }),
  () => agent(`${P}\nNAME.md = four-trees.md`, { label: 'promote-four-trees', phase: 'Promote' }),
  () => agent(`${P}\nNAME.md = identity.md`, { label: 'promote-identity', phase: 'Promote' }),
  () => agent(`${P}\nNAME.md = virtiofs.md`, { label: 'promote-virtiofs', phase: 'Promote' }),
])

phase('Judge')
log(JSON.stringify(promoted))
