export const meta = {
  name: 'cortex-s4-readers-writers',
  description: 'S4 — move every corpus reader and writer onto the organ over /agent/v1, and prove none is left behind.',
  whenToUse: 'After S3 decides the index. S4 is the step that ends the parallel period — until it runs, the organ is a second copy rather than the source.',
  phases: [
    { title: 'Inventory', detail: 'every consumer of KEAP corpus, by call not by name' },
    { title: 'Contract', detail: 'does /agent/v1 answer what each consumer asks' },
    { title: 'Move', detail: 'repoint consumer groups, each proven independently' },
    { title: 'Prove', detail: 'nothing reaches KEAP corpus; every read and write is in audit lineage' },
  ],
}

const NOS = '/Users/pazny/projects/nOS'
const KEAP = '/Users/pazny/projects/knowledge-explorer-and-preserver'
const PLAN = NOS + '/docs/archive/cortex-self-core.md'
const SET = NOS + '/docs/archive/cortex-s3-s4-workflow-set.md'
const BRANCH = 'feat/cortex-s4'

const RULES = [
  'HARD CONSTRAINTS',
  '- Work in ' + NOS + ' on ' + BRANCH + '. ' + KEAP + ' is READ-ONLY. Never dev, never master, never tag.',
  '- Do NOT restart the live cortex daemon and do NOT converge. Report what needs a converge; a human runs it.',
  '- NEVER host-sqlite3 a live libSQL store. Use the owning process.',
  '- Per the plan section 3 doctrine line: every consumer goes over /agent/v1. No in-process shortcut,',
  '  not even for a consumer that will end up colocated. A shortcut taken once becomes the contract.',
  '- A consumer is MOVED only when its own test passes against the organ. "Repointed" is not "moved".',
  '- Report every claim with the command that produced it.',
].join('\n')

const INVENTORY = {
  type: 'object', additionalProperties: false,
  required: ['consumers', 'totalCallSites', 'method'],
  properties: {
    method: { type: 'string' },
    totalCallSites: { type: 'number' },
    consumers: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['name', 'kind', 'callSites', 'verbs', 'writes', 'movable'],
        properties: {
          name: { type: 'string' },
          kind: { type: 'string', enum: ['pulse-job', 'agentkit-tool', 'agent', 'keap-ui-route', 'script', 'other'] },
          callSites: { type: 'array', items: { type: 'string' } },
          verbs: { type: 'array', items: { type: 'string' } },
          writes: { type: 'boolean' },
          movable: { type: 'string', enum: ['yes', 'blocked', 'out-of-scope'] },
          blockedBy: { type: 'string' },
        },
      },
    },
  },
}

const GAPS = {
  type: 'object', additionalProperties: false,
  required: ['covered', 'gaps'],
  properties: {
    covered: { type: 'array', items: { type: 'string' } },
    gaps: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['verb', 'neededBy', 'severity', 'proposal'],
        properties: {
          verb: { type: 'string' },
          neededBy: { type: 'array', items: { type: 'string' } },
          severity: { type: 'string', enum: ['blocker', 'workaround-exists', 'cosmetic'] },
          proposal: { type: 'string' },
        },
      },
    },
  },
}

phase('Inventory')
const inventory = await agent(RULES + '\n\n' +
  'Read ' + PLAN + ' section S4 and ' + SET + ' first.\n\n' +
  'Enumerate EVERY consumer of KEAP corpus data across the estate. The plan says "Pulse jobs, Wing\n' +
  'AgentKit and the curator/librarian agents, then the KEAP UI routes (~47, S0-measured)". Treat that\n' +
  'as a hypothesis to verify, not a list to copy — S0 already found the route count had grown from ~33\n' +
  'to ~47 while nobody was counting.\n\n' +
  'Search by CALL, not by name. A consumer is anything that reads or writes taxonomy nodes, knowledge\n' +
  'objects, embeddings, captures or relations. Look for: HTTP to the KEAP container, direct libSQL\n' +
  'opens of its store, in-container node scripts, KEAP CLI invocations from Pulse job commands, and\n' +
  'AgentKit tools (McpKeapTool and anything beside it).\n\n' +
  'For each, record the VERBS it needs — list nodes, get node, search, upsert object, write capture,\n' +
  'write relation, and so on. The verb list is what phase 2 checks; a consumer named without its verbs\n' +
  'is not inventoried.\n\n' +
  'Mark writers explicitly. Readers can be moved and reverted cheaply; a writer moved to an API that\n' +
  'silently drops a field corrupts the corpus, and that is the risk this whole step carries.',
  { label: 'inventory', phase: 'Inventory', schema: INVENTORY, effort: 'high' })

phase('Contract')
const gaps = await agent(RULES + '\n\n' +
  'Inventory:\n' + JSON.stringify(inventory, null, 1) + '\n\n' +
  'Now the gate that decides whether S4 can proceed at all: does the organ /agent/v1 surface answer\n' +
  'every verb in that inventory?\n\n' +
  'Read the organ route definitions and the KEAP /agent/v1 implementation. For each verb: is it\n' +
  'present, present-but-different (shape, paging, auth, error semantics), or absent?\n\n' +
  'Two specific traps this estate has already paid for:\n' +
  '  - PAGING. The capture queue served every row until an offset parameter was added in KEAP v1.36.0.\n' +
  '    Any verb that returns a collection without an offset is a latent version of the same defect;\n' +
  '    name them even when the current corpus is small enough that nobody notices.\n' +
  '  - THE BOOT CACHE. The organ caches its knowledge tree at process start. A consumer that WRITES\n' +
  '    taxonomy and then READS it back in the same run will read stale data. Say which inventoried\n' +
  '    writers do exactly that, because for them "move to /agent/v1" is not sufficient - they need\n' +
  '    either a cache invalidation verb or a documented restart.\n\n' +
  'Classify each gap: blocker (a consumer cannot move), workaround-exists (say what it costs), or\n' +
  'cosmetic. If there are blockers, S4 does not start — say so plainly and propose the smallest\n' +
  'additions to /agent/v1 that unblock it.',
  { label: 'contract', phase: 'Contract', schema: GAPS, effort: 'high' })

phase('Move')
const GROUPS = [
  { key: 'pulse', what: 'Pulse jobs that touch the corpus (keap-consolidate, keap-embed-sync, keap-features-sync, keap-lint, cortex-fs-sync, cortex-corpus-diff)' },
  { key: 'agentkit', what: 'Wing AgentKit tools — McpKeapTool and any sibling that reaches corpus data' },
  { key: 'agents', what: 'the curator and librarian agent definitions and their runner scripts' },
]
const moved = await pipeline(GROUPS,
  (g) => agent(RULES + '\n\n' +
    'Contract findings:\n' + JSON.stringify(gaps, null, 1) + '\n\n' +
    'Move this consumer group onto the organ over /agent/v1:\n  ' + g.what + '\n\n' +
    'Rules for this group:\n' +
    '- If the contract phase marked any verb this group needs as a BLOCKER, do not move it. Report and stop.\n' +
    '- Keep the old path reachable behind a config switch for one release. This is a corpus; a bad move\n' +
    '  must be revertible without a restore.\n' +
    '- Every write must land in Wing audit lineage with actor_action_id set. That is S4 exit criterion 2,\n' +
    '  and it is easier to add now than to retrofit.\n' +
    '- PULSE GROUP SPECIFICALLY: a job whose runtime exceeds the tick interval used to be dispatched twice\n' +
    '  because Wing advances next_fire_at only on finish. The daemon now guards re-entrancy per job\n' +
    '  (2026-07-28), but state your job runtimes anyway — an indexing job that runs for minutes is exactly\n' +
    '  the shape that found the defect.\n\n' +
    'Then TEST the group against the organ and report the command and its output. Repointed is not moved.',
    { label: 'move:' + g.key, phase: 'Move', effort: 'high' }),
  (result, g) => agent(RULES + '\n\n' +
    'A worker reports having moved: ' + g.what + '\n\n' + String(result).slice(0, 4000) + '\n\n' +
    'Verify it adversarially. Assume the claim is optimistic.\n' +
    '1. Does the consumer still reach KEAP corpus by ANY path — a fallback, a default, an env var that\n' +
    '   is unset in this environment but set in production, a second call site the mover missed?\n' +
    '2. Was the test a real assertion, or did it pass because the code path did not execute?\n' +
    '3. For writers: is the write actually in Wing audit lineage? Query it. Do not accept "it should be".\n' +
    'Report CONFIRMED or REFUTED per point, with commands.',
    { label: 'verify:' + g.key, phase: 'Move', effort: 'high' }))

phase('Prove')
const proof = await agent(RULES + '\n\n' +
  'Inventory: ' + JSON.stringify(inventory, null, 1).slice(0, 4000) + '\n' +
  'Gaps: ' + JSON.stringify(gaps, null, 1).slice(0, 3000) + '\n' +
  'Move results: ' + JSON.stringify(moved.filter(Boolean), null, 1).slice(0, 8000) + '\n\n' +
  'Write the S4 outcome to ' + NOS + '/docs/idea/cortex-s4-outcome.md and amend ' + PLAN + ' S4.\n\n' +
  'The plan states two exit criteria. Answer each with evidence, not with a summary:\n' +
  '  1. NO consumer reaches KEAP corpus. Prove it the hard way: a negative search across the estate for\n' +
  '     every call shape the inventory found, plus the KEAP UI routes, which this workflow does NOT move\n' +
  '     and which therefore keep criterion 1 open. State that openly rather than declaring S4 done.\n' +
  '  2. EVERY corpus read and write appears in Wing audit lineage. Query the lineage and give counts.\n\n' +
  'Then the part that matters more than the checklist: state what S4 has NOT closed. Consumers marked\n' +
  'out-of-scope, verbs still absent from /agent/v1, the KEAP UI routes, and anything that only works\n' +
  'because the corpus is currently small. A step that reports itself complete while leaving a reader on\n' +
  'the old path is worse than one that reports itself partial.',
  { label: 'prove', phase: 'Prove', effort: 'high' })

return {
  consumers: inventory.consumers ? inventory.consumers.length : 0,
  blockers: (gaps.gaps || []).filter((g) => g.severity === 'blocker').map((g) => g.verb),
  moved: moved.filter(Boolean).length,
  proof: String(proof).slice(0, 3000),
}
