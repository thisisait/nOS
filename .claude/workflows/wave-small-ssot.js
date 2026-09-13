export const meta = {
  name: 'wave-small-ssot',
  // TRIAGE GATE. Discovery cannot promote itself; this line IN GIT authorises.
  implements: 'wave-small-ssot',
  description:
    'Union of disjoint small findings (review 2026-09-12 + active-work follow-ups), then a proposed SSOT/constitution citation scheme. Does not blank, does not HKDF v2, does not build Wing/face browsers.',
  whenToUse:
    'After nos recap failed=0 on 2026-09-13. Scheme is still v1 (122 keys). chmod 600 on tfstate + ansible.log already done on disk; this wave pins that in git.',
  isolation: 'worktree',
  writes: 'branch',
  phases: [
    { title: 'Patch', detail: 'union of disjoint code-fix lanes; every output is kept' },
    { title: 'Design', detail: 'proposed docs/doctrine/ssot.md — citation IDs, genome map, KEAP blast-radius graph; browsers are named not built' },
    { title: 'Judge', detail: 'parent reviews artefacts (not author accounts), FF to local dev, no push unless asked' },
  ],
}

const REPO = (typeof args !== 'undefined' && args && args.repo) || '.'

const P = `You are a lazy senior developer. Lazy means efficient, not careless.
THE LADDER, stop at the first rung that holds: does it need to exist at all /
already in this codebase / stdlib / native platform / installed dependency /
one line / minimum code that works. No unrequested abstractions.

THIS ESTATE:
- Isolation: git worktree + feat/<slug> off the SHA you were given. One slug.
- Commit on that branch. Do NOT push. Do NOT touch ~/projects/nOS. Do NOT merge.
- Do NOT edit docs/llm/security/*, files/anatomy/apex/ruling.yml, or untracked 3dd20d44.
- Status is active, never doing. One agent = one slug.
- Retro-red: the new gate must fail on the pre-fix tree (or a mutation of the fixed artefact). A gate you can satisfy by editing the gate is not one.
- Success is written by a READER, not by you claiming done.
- English in code and comments. Conventional Commits, subject ≤ 50 chars, body bullets ≤ 6.
- If blocked, return BLOCKED: one line. Do not invent a workaround that widens blast radius.

HARD REFUSALS for this wave:
- No confirmed blank, no HKDF v2, no credentials.yml rotation.
- No iLEAPP / new digest importers / accounting US-GAAP rewrite.
- No LangChain, no new orchestrator.
- No silent settle of docs/doctrine/agentkit.md §6 or organs.md §3 (operator).
- No Linux smoke-floor (hidden_fees/08 remainder) — later wave.
- Do not cite "§N" without the file path. That citation hole is why Design exists.
`

const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['done', 'files', 'check', 'blocked', 'sha'],
  properties: {
    done: { type: 'string' },
    files: { type: 'array', items: { type: 'string' } },
    check: { type: 'string' },
    blocked: { type: 'array', items: { type: 'string' } },
    sha: { type: 'string' },
  },
}

phase('Patch')

// FAN-OUT: union. Each lane owns a disjoint output set (different files);
// every result is kept; nothing is selected between. Grounded once in P.
const built = await parallel([
  () =>
    agent(
      `${P}

SLUG: fetch-checksums
TASK: every executable ansible.builtin.get_url (FrankenPHP Linux binary, backrest tarball, linux.docker script/binary at minimum) MUST carry checksum / checksum_algorithm. Extend tests/anatomy/test_pinned_artifacts_fetch_the_pin.py so a fetch without checksum is RED. Look up the hashes from the pinned upstream release; do not invent them. Content fetches (kiwix ZIM, maps) are out of scope unless they are already in that pin gate.`,
      { label: 'fetch-checksums', phase: 'Patch', schema: SCHEMA },
    ),
  () =>
    agent(
      `${P}

SLUG: freescout-off-argv
TASK: Freescout admin password must not appear on docker exec / php artisan argv. Both roles/pazny.freescout/tasks/post.yml AND files/anatomy/plugins/freescout-base/hooks/post_compose.yml. Pass via stdin or an env file; no_log: true on those tasks. Gate must fail if the password jinja still sits in a command: string.`,
      { label: 'freescout-off-argv', phase: 'Patch', schema: SCHEMA },
    ),
  () =>
    agent(
      `${P}

SLUG: converge-modes
TASK: three mode pins, one commit:
1) After OpenTofu apply, terraform/authentik/terraform.tfstate* must be mode 0600 (live disk was chmod'd 2026-09-13; git must keep it).
2) Playbook ensures ~/.nos/ansible.log is 0600 (ansible.cfg log_path creates it 0644).
3) portainer_socket_proxy_can_exec default false in the role defaults (config.yml may still override; do not edit gitignored config.yml).
Gate the first two in pytest (task/mode present). Do not chmod files outside the worktree.`,
      { label: 'converge-modes', phase: 'Patch', schema: SCHEMA },
    ),
  () =>
    agent(
      `${P}

SLUG: datatables-count
TASK: docs/doctrine/cross-repo-contracts.md still says 18 SYSTEM tables; state/keap-tables/ has 32 .table.yml. MEASURE which are SYSTEM vs fixture/user-shaped (kolben-*, print-*, …). Bump the prose to the measured SYSTEM count, not a blind 32. Pin keap_repo_ref as it is TODAY (v2.0.0-rc.1), never the review's stale v1.47.0. If roadmap.table.yml still 409s on live reconcile, name it as a recorded exception rather than silently dropping when. A gate must go red if the doctrine integer drifts from the counted SYSTEM set.`,
      { label: 'datatables-count', phase: 'Patch', schema: SCHEMA },
    ),
  () =>
    agent(
      `${P}

SLUG: migrate-severity-security
TASK: files/anatomy/module_utils/nos_migrate_engine.py _SEVERITY_VALUES lacks 'security' even though the schema allows it. Add it. Gate: a record with severity: security validates; an unknown severity still refuses.`,
      { label: 'migrate-severity-security', phase: 'Patch', schema: SCHEMA },
    ),
  () =>
    agent(
      `${P}

SLUG: slug-leading-digit
TASK: hidden_fees/03 — a digit-initial service slug cannot be a KEAP node id (2FAuth → twofauth workaround is invisible). Add a gate that fails if any role/plugin/app slug or taxonomy_anchor starts with a digit. Document the twofauth exception as the reason the gate exists. Do not rename live services.`,
      { label: 'slug-leading-digit', phase: 'Patch', schema: SCHEMA },
    ),
  () =>
    agent(
      `${P}

SLUG: doctrine-hygiene
TASK: docs only, do not edit docs/doctrine/README.md (Design lane owns the new ssot row).
1) docs/archive/fs-doctrine.md header still says DESIGN (P0); P1/P1b shipped — tell the truth, point at docs/doctrine/filesystem.md.
2) docs/active-work.md still claims drift-watch.sh exits 0 on undeliverable CRITICAL; that is false after 90ae988c (HIGH too). Delete that bullet.
3) secrets.md vs observability.md: observability already defers the shared-secret paragraph to secrets.md — confirm there is no second copy of the HMAC saga as a competing rule; if there is, delete the copy, keep the pointer.
Do not split loops.md / foreign-properties.md in this lane (companions already exist).`,
      { label: 'doctrine-hygiene', phase: 'Patch', schema: SCHEMA },
    ),
])

phase('Design')

const ssot = await agent(
  `${P}

SLUG: ssot-design
TASK: write docs/doctrine/ssot.md as PROPOSED (same banner as agentkit.md). Operator settles before anyone cites it as live.
This is the constitution citation scheme, not a browser.

The incident: an agent said "paragraph eight" and the operator could not find it in code. loops.md §8 is an edge-gate rule; workflow-standard.md has two §9s; idea/08-lifecycle.md is a different file. Unqualified §N is a defect.

Required contents (keep the file under ~130 lines; companions later):
- Citation form: nos-sot:<realm>/<file>#<stable-id> e.g. nos-sot:doctrine/loops.md#8
- Realms: doctrine (constitution), idea, genome, dtt (roadmap slugs), fee (hidden_fees/NN)
- Constitution = docs/doctrine/*.md ; each ## heading is the stable-id (file already claims section numbers stable on loops.md)
- Map the self-describe/genome half: state/genome/entity.schema.json is the machine model; it currently has facets and almost no instances — say that honestly
- Bind to existing queued row dtt-constitution (signed constitution as a dtt row) — do not invent a second constitution store
- KEAP: one node per doctrine file (not per sentence); edges doctrine --governs--> surface (plugin/role/organ) so blast radius is a graph walk, not a paragraph. identity.anchor / taxonomy_anchor is the existing hook — re-measure, do not invent a parallel ontology
- Browsers (Wing + face) consume the SAME export the KEAP nodes consume; name the export (e.g. tools/ssot-index.py JSONL) but do NOT build the UI this wave
- A small gate: every docs/doctrine/*.md ATX heading is unique inside its file; workflow-standard.md duplicate §9 is either fixed or named as a known citation collision

Add a README.md row (status: proposed). Do not settle agentkit.md §6 or organs.md §3.`,
  { label: 'ssot-design', phase: 'Design', schema: SCHEMA },
)

phase('Judge')

log(JSON.stringify({ built, ssot }, null, 2))
