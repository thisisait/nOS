export const meta = {
  name: 'ssot-promote',
  implements: 'ssot-recite-doctrine',
  description:
    'RECORD. v1 promote landed 2026-09 (19 articles in ssot/doctrine/). Do not re-run. Remaining warehouse originals: agentkit.md, organs.md (INDEX proposed). Citation policy: ssot/doctrine/ssot.md §5.',
  isolation: 'worktree',
  writes: 'branch',
  phases: [
    { title: 'Harvest', detail: 'already in tree: corpus + stub alias + nos-sot: resolver' },
    { title: 'Promote', detail: 'RECORD — do not fan out again' },
    { title: 'Judge', detail: 'cite + heading + ssot-index gates. INDEX proposed names what is not law yet' },
  ],
}

// Historical prompt kept so a later promote of INDEX proposed files copies
// the same contract. ssot.md §5: mint ## N only when the source had none
// and no inbound §N. A ## 3 that was 3 stays 3.
const P = `You are a lazy senior nOS developer.

ISOLATION: git worktree + feat/ssot-promote-<name> off the SHA in this prompt.
Commit there. Do NOT push. Do NOT touch ~/projects/nOS. Do NOT merge.

ONE FILE. You receive NAME.md. You write:
- ssot/doctrine/NAME.md (the article)
- docs/doctrine/NAME.md (stub only)

Do NOT edit: README.md, INDEX.yml, tools/doctrine-cite.py, other doctrine files,
docs/llm/security/*, apex ruling.yml, other INDEX proposed files.

STABLE SECTION NUMBERS. A ## 3 that was 3 stays 3. Renaming a number is a
breaking citation change. If the source had no numbered headings and no
inbound §N, you MAY mint ## N (ssot.md §5). Do not invent a number that
collides with an existing inbound cite. Number every article unless it has
zero sub-rules. Light reformulation: shall/must/may; drop session anecdotes.
Keep the rule. Incidents that justify the rule may stay as one measured
sentence with a path, or move to an already-linked companion. Do not invent
a new companion. Do not settle proposed files.

Stub exactly:

# <original H1 text>

Moved to [\`ssot/doctrine/NAME.md\`](../../ssot/doctrine/NAME.md).

pytest: tests/anatomy/test_ssot_index.py tests/anatomy/test_doctrine_headings_are_unique.py
Conventional Commits, subject ≤ 50 chars.
`

phase('Promote')
// RECORD. v1 already wrote the 19 articles. Re-running the five-file fan-out
// would reproduce a fraction of the tree. INDEX proposed files wait on the
// operator. `P` above is the contract for that later one-file promote.
log('v1 promote is a record: ssot/doctrine/*.md (19). INDEX proposed: agentkit, organs.')

phase('Judge')
log('gates: test_ssot_index.py test_doctrine_headings_are_unique.py test_doctrine_citations_resolve.py')
