export const meta = {
  name: 'voice-build',
  description: 'Build contract-search, exec tool and collab v1 from the four drafts; record what is skipped',
  phases: [
    { title: 'Build' },
    { title: 'Wire' },
    { title: 'Record' },
    { title: 'Judge' },
  ],
}

// Every agent gets this. The persona is not decoration: it is what keeps the
// diff small enough to review at the end.
const P = `You are a lazy senior developer. Lazy means efficient, not careless.
THE LADDER, stop at the first rung that holds: does it need to exist at all /
already in this codebase / stdlib / native platform / installed dependency /
one line / minimum code that works. No unrequested abstractions, no scaffolding
for later, deletion over addition, fewest files. Mark a deliberate corner with a
\`ponytail:\` comment naming the ceiling. Non-trivial logic leaves ONE runnable
check behind — the smallest thing that fails if the logic breaks. Output code,
not essays.

REPO: /Users/pazny/projects/nOS-voice, branch feat/voice-ingress. Do NOT commit,
do NOT push, do NOT touch /Users/pazny/projects/nOS.

THIS ESTATE'S RULES, which outrank your taste:
- A capability may never be added by DATA. Handlers and opcodes are code.
- No enumeration oracle: an error may not list what would have worked. KEAP's
  unknown_operand is already namespace-constant (261/261 identical) — preserve
  it, do not rebuild it.
- Absence is never success. A success marker is written by a READER, never by
  the code that attempted the work.
- A detector reads the artifact, not the prose describing it.
- A gate you can satisfy by editing the gate is not a gate.
- The repo is not the running system.

MEASURED, do not re-derive: qwen3:14b invented GET /api/v1/security/findings/
open/count and 404'd; the answer exists as GET /api/v1/remediation, described,
in files/anatomy/skills/contracts/wing.openapi.yml (98 paths, 117 operations,
117 with summaries). The genome is a schema with ZERO entity instances — not an
index. tax: and rel: are the only cortex namespaces marked resolved.

The four drafts are in docs/drafts/. Read the one that is yours before you write.

IF A DEPENDENCY BLOCKS YOU: do not invent a workaround and do not stall. Say so
in your return value, in one line, starting with BLOCKED:. Another agent records
it. Ship everything that is not blocked.`

const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['done', 'files', 'check', 'blocked'],
  properties: {
    done: { type: 'string', description: 'what now exists, one paragraph' },
    files: { type: 'array', items: { type: 'string' } },
    check: { type: 'string', description: 'the runnable check and how it is run' },
    blocked: {
      type: 'array',
      items: { type: 'string' },
      description: 'dependencies that stopped work, one line each, empty if none',
    },
  },
}

phase('Build')

// Lane A is sequential: both tools edit state/schema/agent.schema.yaml and the
// DI wiring, so running them in parallel would just be a merge conflict with
// extra steps.
const lane = async () => {
  const search = await agent(`${P}

TASK 1/2 — contract-search. Build the read-only tool that stops an agent
inventing endpoints. Draft: docs/drafts/contract-search.md (follow it unless it
is wrong, and say so if it is).

It is ALSO bucket 1 of the entity resolver (docs/drafts/entity-resolver.md) —
build ONE component used twice, not two that drift.

Sibling to copy the shape from: files/anatomy/wing/app/AgentKit/Tools/
McpWingReadTool.php. Register it where the others are registered; add the id to
the enum in state/schema/agent.schema.yaml; give it to the jeff agents.

It may return only static strings from the committed contract files. It may
never execute a request, read wing.db, or return row data. That is the line.`,
    { label: 'contract-search', phase: 'Build', schema: SCHEMA })

  const exec = await agent(`${P}

TASK 2/2 — the exec tool. Draft: docs/drafts/exec-tool.md.

One tool, one argument: a cortex-lang sentence. It adds NO capability — that is
the test. Path: validate (cortex /agent/v1/validate) -> CortexBindingGate ->
the mutating() check in the dispatch loop (it is a THIRD separate check, not
inside the gate — the draft has the detail).

Two refusals, structural: an error may not enumerate (preserve what KEAP
already does), and confirm:true is checked, never trusted — it may narrow a
permission, never widen one.

contract-search has just landed; do not undo its edits to
state/schema/agent.schema.yaml, extend them.`,
    { label: 'exec-tool', phase: 'Build', schema: SCHEMA })

  return [search, exec]
}

// SEQUENTIAL, not a fan-out — corrected 2026-09-01 after
// test_workflow_declares_fanout_semantics refused this file. The two lanes do
// have disjoint output (AgentKit PHP + the schema enum vs the face + one table
// definition), which is what §1 asks of a union — but both are BUILD steps, and
// the gate's rule for those is categorical for a measured reason: a build step
// wants the previous one's real contract, so a fan-out there parallelises the
// guessing. The gate was right and the workflow was wrong; the workflow moved.
const tools = await lane()
const collab = await agent(`${P}

TASK — collab v1, the conversation surface. Draft: docs/drafts/collab.md.

Smallest useful thing per the draft: author the caddy-sessions view block as
style chat, mount it through the existing TablesApp / bff/tables path, and add
the one VIEW_ACTIONS entry the handoff to Wing /inbox needs — handler first,
id second, per the rule written in view.ts itself.

No new render style. No markup from data. The chain column is text, so a nested
view is a client-side JSON.parse, not a schema change.

KEAP's tableViewStyleSchema does not accept 'chat' and lives in another repo:
if that blocks authoring the view block, say BLOCKED: and ship the face half.

The face vitest lane is 330 tests; keep it green (npx vitest run in
files/anatomy/face).`,
  { label: 'collab', phase: 'Build', schema: SCHEMA })

phase('Wire')

const built = [...(tools || []), collab].filter(Boolean)
const fileList = built.flatMap((b) => b.files || []).join(', ')

const wired = await agent(`${P}

TASK — make the tree green and honest after three parallel edits.

Files touched: ${fileList}

Do, in order, and report what you changed:
1. python3 -m pytest tests/anatomy -q --ignore=tests/anatomy/test_the_control_centre_shows_state.py
   (that one fails in a sandboxed shell for tmux reasons, not a regression)
2. cd files/anatomy/face && npx vitest run
3. ansible-lint on any role touched; ansible-playbook main.yml --syntax-check
4. If the anatomy graph changed: python3 tools/anatomy-graph-gen.py, then
   re-freeze the face layout pin by the ritual in
   tests/anatomy/test_face_layout_pin_binds_the_graph.py, then check whether
   the apex ruling gained UNRULED nodes. If it did, add them as withheld with
   a one-line reason and LEAVE THE SIGNATURE STALE — signing is the operator's
   act, and awaiting-operator.py reports the amendment.
5. If tools/ gained a file: add it to tools/README.md (a gate reads that).

Fix what is yours to fix. Anything that needs a decision, return as BLOCKED:.`,
  { phase: 'Wire', schema: SCHEMA })

phase('Record')

const skipped = [...built, wired].flatMap((b) => (b && b.blocked) || [])

const recorded = await agent(`${P}

TASK — record what was skipped, so it is a decision and not a silence.

Blocked items from the build:
${skipped.length ? skipped.map((s) => `- ${s}`).join('\n') : '- (none reported)'}

For each, choose ONE and do it:
- A HIDDEN FEE (docs/hidden_fees/) when a cost was already being paid without
  anyone deciding to pay it. Follow the shape of the existing files: what it
  cost, how it was measured, what is still open.
- A ROADMAP ROW when it is future work: edit tools/roadmap-seed.py, run
  python3 tools/roadmap-seed.py --dry-run first, then without --dry-run.
  Bodies in that file carry the measurement, not the intention.

Do not invent items. If the list is empty, say so and write nothing — an empty
ledger is an answer.`,
  { phase: 'Record', schema: SCHEMA })

phase('Judge')

// union — two lenses over the same diff asking different questions: refute
// hunts defects, trim hunts size. Finding sets are added, never chosen between.
const verdicts = await parallel([
  () => agent(`${P}

TASK — adversarial review of the working tree diff (git diff dev; plus
untracked files). Try to REFUTE that this was built correctly.

Hunt specifically for: a capability added by data; an error path that
enumerates; a success marker written by the code that attempted the work; a
gate that its own change could satisfy; a check that cannot fail for the reason
it exists; and prose that claims something the artifact does not do.

Return findings most severe first, each CONFIRMED (you ran something) or
PLAUSIBLE (you reasoned). If nothing survives, say so plainly.`,
    { label: 'refute', phase: 'Judge' }),

  () => agent(`${P}

TASK — review the same diff for SIZE. You are the laziest reader in the estate.

What in this diff should not exist? Name every abstraction with one
implementation, every option nobody asked for, every file that could be a
function, every test that tests the framework rather than the logic. Quote the
line count you would delete.

Then answer one question honestly: is contract-search and the resolver's first
bucket ONE component here, or did they get built twice?`,
    { label: 'trim', phase: 'Judge' }),
])

return {
  built: built.map((b) => b && b.done),
  files: built.flatMap((b) => (b && b.files) || []),
  checks: built.map((b) => b && b.check),
  wired: wired && wired.done,
  recorded: recorded && recorded.done,
  blocked: skipped,
  judge: verdicts.filter(Boolean),
}
