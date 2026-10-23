export const meta = {
  "name": "rel-018-advisory",
  "description": "v0.18 security: every pin and lockfile matched deterministically against public advisories (GitHub repo advisories, OSV, cve.now); nightly patrol, release stopper, Iris security_check",
  "whenToUse": "After 2026-10-23. Rows 2 and 3 build on row 1. Network reads only to the three advisory sources; nothing about the estate is sent except public lockfile contents and the ids of hits.",
  "phases": [
    {
      "title": "Build",
      "detail": "each row in its own worktree, gate first"
    },
    {
      "title": "Review",
      "detail": "one skeptic per row, one re-review of the fixed"
    },
    {
      "title": "Fix",
      "detail": "at most two fix passes in all"
    },
    {
      "title": "Integrate",
      "detail": "merge the landed rows, one full run, report"
    }
  ]
}

// Rows are the spec: slug = the roadmap row in nos-seed; facts are the 2026-10-21 audits (verify, never trust).
const ROWS = [
  {
    "depends_on": [],
    "expected_red": [
      "everything a regenerate plus a re-sign clears, because the reader is a new graph node: apex projection/sign/serve, anatomy-graph --check, body-plan --check, test_imprint_is_rendered, the face layout pin"
    ],
    "operator_decisions": [
      "whether OSV querybatch may receive the lockfile package list (default yes: the lockfiles are public in the repo)",
      "a GITHUB_TOKEN for higher rate limits (default: none, anonymous 60/h is enough for ~40 repos nightly? measure and say)"
    ],
    "security_lens": "",
    "slug": "advisory-receptors-and-matcher",
    "branch": "feat/advisory-receptors-and-matcher",
    "facts": "Measured 2026-10-23 (seed row advisory-patrol): the estate ran FrankenPHP 1.13.1 two days after upstream published GHSA-6q3j-62j9-f9hh (high) + GHSA-ccgp/fq24 (medium) + GHSA-4gfw (low), fixed in 1.13.2; nOS said nothing. The nightly vuln scan files/vuln-scan/scan-runner.sh + scan-prompt.md is a MODEL doing web searches per component; it never read the pins in default.config.yml (65 lines match ^[a-z0-9_]+_(version|tag|image_tag): e.g. frankenphp_version, mariadb_version '11.8.9', postgresql_version '16.15-alpine', redis_version, ollama_version, santa_version). Sources, measured: (a) GitHub repo advisories `GET repos/<owner>/<repo>/security-advisories` held all four FrankenPHP ones with vulnerabilities[].patched_versions; (b) OSV `POST https://api.osv.dev/v1/query` {package:{purl},version} and `/v1/querybatch` returned only GO-2026-4442 for pkg:golang/github.com/dunglas/frankenphp@1.13.1; (c) cve.now: `GET https://cve.now/api/v1/entries/<CVE-id>` returns {id, aliases[], severity{cvss,vector}, exploitation{kev,epssReached,exploitDb}, affected[{ecosystem,package,ranges[{introduced,fixed}]} | {vendor,product,ranges}], references}; a GHSA-only id is 404; `/feed?format=json` (JSON Feed, items {id,url,title,content_text,date_modified}, no ranges), filters `filter=critical|kev`, `ecosystem=npm|pypi|go|maven|crates.io|packagist|rubygems|hex|nuget`, `tech=<slug>` (uneven: redis 62, postgresql 135, caddy 0, frankenphp 0, mariadb 0); free, no key, rate limits unstated. Lockfiles (public in the repo): files/anatomy/thalamus/Cargo.lock, files/anatomy/wing/composer.lock, files/anatomy/face/package-lock.json, files/anatomy/cortex/package-lock.json. Existing queue: ~/.nos/security/remediation-queue.json read by tools/rem-status.py (tools/nos_security.py: the scanner owns the queue, dispositions.json overlays; NOS_SECURITY_DIR overrides). Immune doctrine ssot/doctrine/immune-system.md §2 indicator contract (kind, antigen deterministic first, receptor read-only, effector report, signal, heartbeat, tolerance, verdicts). Feed parser to reuse: tools/loops/news-scout.py (stdlib xml.etree RSS/Atom; its loop files/anatomy/loops/news-scout.loop.yml runs daily and is green). red-status probes are functions in tools/red-status.py (security_scan :646, stalled_verdicts :783). Release checklist: .claude/skills/release-prep/SKILL.md step 1 'Stoppers'.",
    "files_owned": [
      "state/genome/advisory-receptors.yml (new: one row per pin var in default.config.yml and config.d/*.yml: {github: owner/repo} | {osv: purl-without-version} | {tech: cve.now slug} | {none: reason}; several allowed per pin; the version is read from the pin, never copied)",
      "tools/advisory-status.py (new reader: inventory = pins via the receptors + the four lockfiles; sources = GitHub repo advisories (gh api or urllib with GITHUB_TOKEN if set), OSV querybatch for lockfile packages, cve.now entry by id for KEV/EPSS/ranges; exact range match (introduced <= v < fixed, last_affected, no keyword match); --json, --offline <fixture-dir>; every source UNKNOWN on its own; exit 0 always)",
      "tests/anatomy/test_advisory_matcher.py (new; offline fixtures only)",
      "tests/anatomy/test_every_pin_has_an_advisory_receptor.py (new)",
      "tools/README.md (§Readers line) and the tools index allow-lists this reader needs (GATE CHANGE commit of this row)"
    ],
    "gates": [
      "new gate: matcher on fixtures: in range, below introduced, at fixed (not affected), last_affected inclusive, a prerelease, an image tag like '16.15-alpine' compared as 16.15; red today: no matcher",
      "new gate: every pin var in default.config.yml + config.d has a receptor row (a new pin without one is refused, naming the var); red today: no file",
      "new gate: with every source unreachable (fixture) the reader prints UNKNOWN per source and exits 0; never 'no findings'",
      "the FrankenPHP case as a fixture: frankenphp_version 1.13.1 + the four GHSA records -> 4 matches, 1.13.3 -> 0"
    ],
    "steps": "(1) Receptor file for all pins: github where the pin names a GitHub release, osv where the ecosystem is a package registry, tech where only cve.now knows it, none with a reason otherwise (say why, e.g. 'distro package, covered by trivy image scan'). (2) Matcher as a pure function with its own version parser (stdlib; no new dependency). (3) Sources behind one fetch seam so tests inject fixtures; HTTP timeouts 20 s; a source failure is UNKNOWN. (4) Output rows {component, pin, version, source, advisory id, aliases, severity, kev, epss, fixed_in, url}. Never writes anything."
  },
  {
    "depends_on": [
      "advisory-receptors-and-matcher"
    ],
    "expected_red": [
      "everything a regenerate plus a re-sign clears (new loop node): apex projection/sign/serve, anatomy-graph --check, body-plan --check, test_imprint_is_rendered, the face layout pin"
    ],
    "operator_decisions": [
      "cadence (default 07:30 daily, after news-scout)",
      "whether a KEV match also pages ntfy (default inbox only)"
    ],
    "security_lens": "",
    "slug": "advisory-patrol-loop",
    "branch": "feat/advisory-patrol-loop",
    "facts": "Measured 2026-10-23 (seed row advisory-patrol): the estate ran FrankenPHP 1.13.1 two days after upstream published GHSA-6q3j-62j9-f9hh (high) + GHSA-ccgp/fq24 (medium) + GHSA-4gfw (low), fixed in 1.13.2; nOS said nothing. The nightly vuln scan files/vuln-scan/scan-runner.sh + scan-prompt.md is a MODEL doing web searches per component; it never read the pins in default.config.yml (65 lines match ^[a-z0-9_]+_(version|tag|image_tag): e.g. frankenphp_version, mariadb_version '11.8.9', postgresql_version '16.15-alpine', redis_version, ollama_version, santa_version). Sources, measured: (a) GitHub repo advisories `GET repos/<owner>/<repo>/security-advisories` held all four FrankenPHP ones with vulnerabilities[].patched_versions; (b) OSV `POST https://api.osv.dev/v1/query` {package:{purl},version} and `/v1/querybatch` returned only GO-2026-4442 for pkg:golang/github.com/dunglas/frankenphp@1.13.1; (c) cve.now: `GET https://cve.now/api/v1/entries/<CVE-id>` returns {id, aliases[], severity{cvss,vector}, exploitation{kev,epssReached,exploitDb}, affected[{ecosystem,package,ranges[{introduced,fixed}]} | {vendor,product,ranges}], references}; a GHSA-only id is 404; `/feed?format=json` (JSON Feed, items {id,url,title,content_text,date_modified}, no ranges), filters `filter=critical|kev`, `ecosystem=npm|pypi|go|maven|crates.io|packagist|rubygems|hex|nuget`, `tech=<slug>` (uneven: redis 62, postgresql 135, caddy 0, frankenphp 0, mariadb 0); free, no key, rate limits unstated. Lockfiles (public in the repo): files/anatomy/thalamus/Cargo.lock, files/anatomy/wing/composer.lock, files/anatomy/face/package-lock.json, files/anatomy/cortex/package-lock.json. Existing queue: ~/.nos/security/remediation-queue.json read by tools/rem-status.py (tools/nos_security.py: the scanner owns the queue, dispositions.json overlays; NOS_SECURITY_DIR overrides). Immune doctrine ssot/doctrine/immune-system.md §2 indicator contract (kind, antigen deterministic first, receptor read-only, effector report, signal, heartbeat, tolerance, verdicts). Feed parser to reuse: tools/loops/news-scout.py (stdlib xml.etree RSS/Atom; its loop files/anatomy/loops/news-scout.loop.yml runs daily and is green). red-status probes are functions in tools/red-status.py (security_scan :646, stalled_verdicts :783). Release checklist: .claude/skills/release-prep/SKILL.md step 1 'Stoppers'.",
    "files_owned": [
      "files/anatomy/loops/advisory-patrol.loop.yml (new loop manifest, owner install_loops, daily cadence after news-scout, run tools/loops/advisory-patrol.py)",
      "tools/loops/advisory-patrol.py (runner: calls tools/advisory-status.py --json, writes NEW matches into the remediation queue via the nos_security seam with source=advisory-patrol and a stable id per (component, advisory), never touching disposition keys; posts a Wing inbox notification for HIGH/CRITICAL/KEV through the existing notification path)",
      "tools/red-status.py (a probe: unjudged HIGH/CRITICAL/KEV advisory matches, and patrol silence past 36 h is red)",
      ".claude/skills/release-prep/SKILL.md (step 1: no unjudged HIGH/CRITICAL/KEV advisory match on a pin; command tools/advisory-status.py)",
      "tests/anatomy/test_advisory_patrol_*.py (new)",
      "tests/anatomy/test_loop_generates_its_pulse_job.py only if the new loop needs a GATE CHANGE"
    ],
    "gates": [
      "new gate: a fixture run adds a match once (idempotent on re-run), keeps an operator disposition, and never deletes a row; red today",
      "new gate: red-status names an unjudged HIGH match and says UNKNOWN when the patrol never ran; red today",
      "loop-graph-gen.py --validate accepts the manifest; discover-pulse-catalog emits loop:advisory-patrol installed when install_loops is on"
    ],
    "steps": "(1) Runner reuses the reader, not a second matcher. (2) Queue writes through tools/nos_security.py only. (3) The applicability judgement (does it touch nOS?) is NOT in this row: leave a 'needs_judgement' marker for an agent row later. (4) Notification: reuse the Wing notification path red-status already reads (unread_inbox :485), severity mapped HIGH->high, CRITICAL/KEV->critical."
  },
  {
    "depends_on": [
      "advisory-receptors-and-matcher"
    ],
    "expected_red": [
      "test_imprint_is_rendered if the tool list feeds IMPRINT (the integrator regenerates)"
    ],
    "operator_decisions": [
      "Tier 1 only (default) or Tier 2 read"
    ],
    "security_lens": "Tier 1 only; the model renders the reader's rows and adds no finding of its own; free text from advisories is data (FREE_TEXT + data_notice in serve.rs).",
    "slug": "iris-security-check",
    "branch": "feat/iris-security-check",
    "facts": "Measured 2026-10-23 (seed row advisory-patrol): the estate ran FrankenPHP 1.13.1 two days after upstream published GHSA-6q3j-62j9-f9hh (high) + GHSA-ccgp/fq24 (medium) + GHSA-4gfw (low), fixed in 1.13.2; nOS said nothing. The nightly vuln scan files/vuln-scan/scan-runner.sh + scan-prompt.md is a MODEL doing web searches per component; it never read the pins in default.config.yml (65 lines match ^[a-z0-9_]+_(version|tag|image_tag): e.g. frankenphp_version, mariadb_version '11.8.9', postgresql_version '16.15-alpine', redis_version, ollama_version, santa_version). Sources, measured: (a) GitHub repo advisories `GET repos/<owner>/<repo>/security-advisories` held all four FrankenPHP ones with vulnerabilities[].patched_versions; (b) OSV `POST https://api.osv.dev/v1/query` {package:{purl},version} and `/v1/querybatch` returned only GO-2026-4442 for pkg:golang/github.com/dunglas/frankenphp@1.13.1; (c) cve.now: `GET https://cve.now/api/v1/entries/<CVE-id>` returns {id, aliases[], severity{cvss,vector}, exploitation{kev,epssReached,exploitDb}, affected[{ecosystem,package,ranges[{introduced,fixed}]} | {vendor,product,ranges}], references}; a GHSA-only id is 404; `/feed?format=json` (JSON Feed, items {id,url,title,content_text,date_modified}, no ranges), filters `filter=critical|kev`, `ecosystem=npm|pypi|go|maven|crates.io|packagist|rubygems|hex|nuget`, `tech=<slug>` (uneven: redis 62, postgresql 135, caddy 0, frankenphp 0, mariadb 0); free, no key, rate limits unstated. Lockfiles (public in the repo): files/anatomy/thalamus/Cargo.lock, files/anatomy/wing/composer.lock, files/anatomy/face/package-lock.json, files/anatomy/cortex/package-lock.json. Existing queue: ~/.nos/security/remediation-queue.json read by tools/rem-status.py (tools/nos_security.py: the scanner owns the queue, dispositions.json overlays; NOS_SECURITY_DIR overrides). Immune doctrine ssot/doctrine/immune-system.md §2 indicator contract (kind, antigen deterministic first, receptor read-only, effector report, signal, heartbeat, tolerance, verdicts). Feed parser to reuse: tools/loops/news-scout.py (stdlib xml.etree RSS/Atom; its loop files/anatomy/loops/news-scout.loop.yml runs daily and is green). red-status probes are functions in tools/red-status.py (security_scan :646, stalled_verdicts :783). Release checklist: .claude/skills/release-prep/SKILL.md step 1 'Stoppers'. Thalamus reader tools follow red_status/read_run: const docs near serve.rs RED_STATUS/READ_RUN, tools() list, reader() at serve.rs:4321 (python3 tools/<name> --json, timeout, UNKNOWN on failure), FREE_TEXT const and data_notice() at serve.rs:~713/~5233, Tier 1 check like red_status; tool-name pin in thalamus/tests/serve.rs.",
    "files_owned": [
      "files/anatomy/thalamus/thalamus/src/serve.rs (tool security_check: runs tools/advisory-status.py --json via reader(), renders a table: component, version, advisory, severity, KEV, fixed in; Tier 1 only; listed in FREE_TEXT with a data_notice)",
      "files/anatomy/thalamus/thalamus/tests/serve.rs (tests + the tool-name pin as a GATE CHANGE commit)",
      "files/anatomy/agents/iris/agent.yml or the imprint source only if the tool list is declared there"
    ],
    "gates": [
      "new serve tests: a fixture reader output renders the table; reader failure says UNKNOWN, never 'secure'; below Tier 1 refused; the model hears the data notice",
      "GATE CHANGE: the tool-name pin gains security_check"
    ],
    "steps": "(1) Copy the red_status tool's shape. (2) The tool description says: the answer is the table; say what is UNKNOWN; never claim the system is secure. (3) cargo test --workspace green."
  }
]
const INTEGRATION_BRANCH = "feat/rel-018-advisory"
const INTEGRATION_EXTRA = ""

// ---- harness (shared by the v0.18-beta workflows; edit all or none) ------------------------------------
const A = typeof args !== 'undefined' && args ? args : {}
const BASE = A.base || 'origin/dev'
const SEED = A.seed || '/Users/pazny/projects/nos-seed'
const MAX_FIXES = 2 // builds + reviews + fixes + re-review + integrate <= 10 agents

const RULES = `House rules (nOS; the repo's CLAUDE.md applies):
- Work ONLY in your own git worktree. Branch as your task names it, cut from ${BASE}.
- Push with "tools/nos-push --skip-sync origin HEAD:<branch>" (no Gitea mirror write), then confirm with
  "git ls-remote origin refs/heads/<branch>". NEVER push to dev or master; never merge into dev.
- Gate first: write the gate, run it to a log file, read the exit code (never through a pipe), see it RED for the
  RIGHT reason (the failing assertion names the missing behaviour; an ImportError/SyntaxError/missing fixture is
  not red), commit "test: ... (red)"; then the fix, green, commit. Changing an EXISTING test's expectation is its
  own commit "test: GATE CHANGE ..." with the why.
- Commits: Conventional Commits, subject <= 50 chars, body <= 6 bullets, NO Co-Authored-By line.
- Never read ~/.nos/secrets.yml, credentials.yml or any .env; never print a secret.
- Never touch the live estate: no ansible-playbook, no nos (except read-only "nos dtt status"), no
  launchctl/systemctl, no useradd/groupadd/chown, no writes to ~/wing, ~/thalamus, ~/.nos, ~/stacks, /var/lib,
  /etc. Never run anything under tests/e2e/journeys or tests/e2e/estate (they default to the LIVE Wing
  127.0.0.1:9000 and the live wing.db) and never import tests/e2e/lib/estate_secrets.py. Any test you write that
  talks HTTP or SQLite takes an explicit scratch URL/path with NO default pointing at a live one. Read-only live
  reads through the repo's readers (tools/*-status.py) are allowed and must be reported as such.
- Run only the lanes you touch plus the full "cargo test" of every crate you touch
  (CARGO_TARGET_DIR=/Users/pazny/.cargo-target-nos). Gates stay Python; never port a gate.
- A new node in the anatomy graph gets an apex ruling entry (files/anatomy/apex/ruling.yml, "withheld" unless the
  row says otherwise) in its OWN clearly headed block. Do NOT commit regenerated artifacts (anatomy-graph,
  body-plan, IMPRINT, glossary, face layout pin): the integrator regenerates them once. Never run tools/apex-sign.py.
- The row that CREATES a thing owns every gate allow-list that thing needs (a new ssot article: its _BORN_IN_SSOT
  line in tests/anatomy/test_ssot_index.py; a new reader: its tools/README §Readers line; a new lockfile: its
  dependabot entry) as a "test: GATE CHANGE ..." commit of that row, never left for the operator.
- Expected-red is explicit per row: nothing else may be red on your branch; a reviewer refutes any other red lane.
  A row that adds a graph node (reader, article, organ, tool) lists as expected-red everything a regenerate plus a
  re-sign clears (apex projection/sign/serve, anatomy-graph, body-plan, IMPRINT, the face pin), because artifacts
  are regenerated once by the integrator, not by the row.
- Rows are the spec; the roadmap files under ${SEED} are their source. Config keys, sudo, converges, closures of
  roadmap rows and anything destructive are the operator's: leave them in operator_questions.`

const BUILD_SCHEMA = { type: 'object', properties: {
  branch: { type: 'string' }, pushed: { type: 'boolean' }, worktree: { type: 'string' },
  commits: { type: 'array', items: { type: 'string' } }, red_shown: { type: 'array', items: { type: 'string' } },
  green: { type: 'array', items: { type: 'string' } }, not_verified: { type: 'array', items: { type: 'string' } },
  apex_resign_needed: { type: 'boolean' }, operator_questions: { type: 'array', items: { type: 'string' } } },
  required: ['branch', 'pushed', 'worktree', 'commits', 'red_shown', 'green', 'not_verified', 'apex_resign_needed', 'operator_questions'] }
const VERDICT_PROPS = { refuted: { type: 'boolean' }, defects: { type: 'array', items: { type: 'string' } },
  checked: { type: 'array', items: { type: 'string' } } }
const VERDICT_SCHEMA = { type: 'object', properties: VERDICT_PROPS, required: ['refuted', 'defects', 'checked'] }
const RECHECK_SCHEMA = { type: 'object', properties: { rows: { type: 'array', items: { type: 'object',
  properties: { slug: { type: 'string' }, ...VERDICT_PROPS }, required: ['slug', 'refuted', 'defects', 'checked'] } } },
  required: ['rows'] }
const honest = (v, who) => !v ? { refuted: true, defects: [`${who} returned nothing`], checked: [] }
  : (!v.checked || !v.checked.length) ? { ...v, refuted: true, defects: [...(v.defects || []), `${who} listed no command it ran`] } : v
const METHOD = `Method (in your own worktree): "git fetch origin", "git checkout --detach origin/<branch>",
"git diff <diff base>...origin/<branch>" where the diff base is the row's dependency branch when it has one (its files are
not this row's), else ${BASE}; for red-before, "git checkout --detach <the (red) commit>" and run that gate.
Run every gate to a log file and read the exit code, never through a pipe. List every command with its exit code in
"checked". refuted=true if any gate is not green, was never red for the RIGHT reason, a house rule is broken, a file
outside the row's ownership changed, or any new test/tool has a default URL/path/token pointing at the live Wing,
wing.db, ~/.nos or the Docker socket. Default to refuted=true when uncertain.`

const bySlug = Object.fromEntries(ROWS.map(r => [r.slug, r]))
const results = {}
for (const [s, b] of Object.entries(A.landed || {})) if (bySlug[s]) results[s] = { built: { branch: b, pushed: true,
  worktree: '(earlier run)', commits: [], red_shown: [], green: [], not_verified: ['landed by an earlier run'],
  apex_resign_needed: false, operator_questions: [] }, verdicts: [], defects: [], fixed: null, landed: true, still_refuted: false }
let fixes = 0

const build = row => agent(`${RULES}

Build roadmap row ${row.slug} on branch ${row.branch} (cut from ${BASE}${row.depends_on.length ?
  `, then merge ${row.depends_on.map(d => `origin/${bySlug[d].branch}`).join(' and ')} into it first` : ''}).
Measured facts (2026-10-21 audits; verify before relying on them): ${row.facts}
You own these files and no others: ${row.files_owned.join(', ')}.
Gates (each shown red first): ${row.gates.join('; ')}.
Expected red until the integrator regenerates (and nothing else): ${row.expected_red.join('; ') || 'none'}.
Steps: ${row.steps}
Leave open for the operator: ${row.operator_decisions.join('; ') || 'nothing named'}.
Return what you committed, what you saw red and green (exact commands + exit codes), your worktree path, what you did not verify.`,
  { label: `build:${row.slug}`, phase: 'Build', schema: BUILD_SCHEMA, isolation: 'worktree', model: 'opus' })

const review = (row, built, lens) => agent(`You are a skeptic reviewing branch origin/${built.branch} (roadmap row ${row.slug}) through the ${lens} lens.
Try to REFUTE that it is done. Its gates: ${row.gates.join('; ')}. It may change only: ${row.files_owned.join(', ')}.
Diff base for ownership: ${row.depends_on.length ? row.depends_on.map(d => `origin/${bySlug[d].branch}`).join(' + ') : BASE}.
Red is allowed ONLY on: ${row.expected_red.join('; ') || 'nothing'}; any other red lane among the row's lanes refutes it.
${METHOD}
${row.security_lens && lens === 'security' ? `Security lens: ${row.security_lens}` : ''}
Builder said: ${JSON.stringify(built)}`,
  { label: `review:${row.slug}:${lens}`, phase: 'Review', schema: VERDICT_SCHEMA, isolation: 'worktree', model: 'opus' })

async function runRow(row) {
  const built = await build(row)
  if (!built) return (results[row.slug] = { built: null, landed: false, why: 'the builder returned nothing' })
  const lenses = row.security_lens ? ['correctness', 'security'] : ['correctness']
  const raw = await parallel(lenses.map(l => () => review(row, built, l)))
  const verdicts = raw.map((v, i) => honest(v, `reviewer ${lenses[i]}`))
  const defects = verdicts.filter(v => v.refuted).flatMap(v => v.defects)
  let fixed = null
  if (defects.length && fixes < MAX_FIXES) {
    fixes++
    log(`${row.slug}: refuted, fix pass ${fixes}/${MAX_FIXES} (${defects.length} defects)`)
    fixed = await agent(`${RULES}

Fix branch ${built.branch} (roadmap row ${row.slug}); a reviewer refuted it:
${defects.map(d => `- ${d}`).join('\n')}
In your own worktree: "git fetch origin && git checkout --detach origin/${built.branch}", fix each defect with its own
commit (gate first where a gate is missing), push with "tools/nos-push --skip-sync origin HEAD:${built.branch}" and
confirm with git ls-remote. Files you may touch: ${row.files_owned.join(', ')}, plus a gate allow-list the row's new
thing needs as its own GATE CHANGE commit.`,
      { label: `fix:${row.slug}`, phase: 'Fix', schema: BUILD_SCHEMA, isolation: 'worktree', model: 'opus' })
  } else if (defects.length) log(`${row.slug}: refuted, no fix budget left (${MAX_FIXES} used)`)
  results[row.slug] = { built, verdicts, defects, fixed, landed: !defects.length && built.pushed, still_refuted: defects.length > 0 }
  return results[row.slug]
}

async function recheckFixed(tag) {
  const rows = Object.entries(results).filter(([, r]) => r.fixed && r.still_refuted && !r.rechecked)
  if (!rows.length) return
  phase('Review')
  const v = await agent(`You are a skeptic re-reviewing fixed branches:
${rows.map(([s, r]) => `- ${s}: origin/${r.fixed.branch}; defects claimed fixed: ${r.defects.join('; ')}; gates: ${bySlug[s].gates.join('; ')}; red allowed only on: ${bySlug[s].expected_red.join('; ') || 'nothing'}`).join('\n')}
${METHOD}
Return one verdict per slug.`, { label: `rereview${tag}`, phase: 'Review', schema: RECHECK_SCHEMA, isolation: 'worktree', model: 'opus' })
  for (const [s, r] of rows) {
    const h = honest(v && v.rows.find(x => x.slug === s), `re-reviewer of ${s}`)
    r.rechecked = h; r.still_refuted = h.refuted; r.landed = r.fixed.pushed && !h.refuted
  }
}

phase('Build')
const pending = new Set(ROWS.map(r => r.slug))
while (pending.size) {
  for (const s of [...pending]) if (results[s] && results[s].landed) pending.delete(s)
  if (!pending.size) break
  const ready = [...pending].map(s => bySlug[s]).filter(r => r.depends_on.every(d => results[d] && results[d].landed))
  if (!ready.length) {
    const waiting = Object.values(results).some(r => r.fixed && r.still_refuted && !r.rechecked)
    if (waiting) { await recheckFixed(''); phase('Build'); continue }
    log(`not built, a dependency did not land: ${[...pending].join(', ')}`); break
  }
  ready.forEach(r => pending.delete(r.slug))
  await parallel(ready.map(r => () => runRow(r)))
}
await recheckFixed('-late')

phase('Integrate')
const landed = ROWS.filter(r => results[r.slug] && results[r.slug].landed).map(r => (results[r.slug].fixed || results[r.slug].built).branch)
const integration = landed.length ? await agent(`${RULES}

Integrate ${landed.map(b => `origin/${b}`).join(', ')} into a new branch ${INTEGRATION_BRANCH} cut from ${BASE}, in your own
worktree (merge the origin/ refs, never local branch names: other worktrees hold them). Resolve conflicts keeping both
sides' intent; a ruling.yml conflict keeps every entry. Regenerate generated artifacts with their writers, once
(tools/anatomy-graph-gen.py --refreeze, tools/body-plan-gen.py, tools/imprint-gen.py, tools/genome-codegen.py if the
lexicon changed) and commit them. Your ONE full run, each to its own log file in the background with a long timeout,
reading the summary line and the exit code: "python3 -m pytest tests/anatomy -q -p no:cacheprovider", the full
"cargo test --locked" of every crate touched, the face vitest lane if face changed. Push with
"tools/nos-push --skip-sync origin HEAD:${INTEGRATION_BRANCH}". Report every failure with its reason; the apex signature
failing is expected (the operator signs): set apex_resign_needed. Put the output of "git worktree list" in
operator_questions' last entry. ${INTEGRATION_EXTRA || ''}`,
  { label: 'integrate', phase: 'Integrate', schema: BUILD_SCHEMA, isolation: 'worktree', model: 'opus' }) : null

return {
  rows: Object.fromEntries(ROWS.map(r => { const x = results[r.slug]; if (!x) return [r.slug, { built: false, why: 'a dependency did not land' }]
    const b = x.fixed || x.built; return [r.slug, b ? { branch: b.branch, worktree: b.worktree, pushed: b.pushed, landed: x.landed,
    fixed: !!x.fixed, still_refuted: !!x.still_refuted, commits: b.commits, red_shown: b.red_shown,
    review: (x.verdicts || []).map(v => ({ refuted: v.refuted, defects: v.defects, checked: v.checked })), rereview: x.rechecked || null,
    not_verified: b.not_verified, operator_questions: b.operator_questions } : { built: false, why: x.why }] })),
  integration,
  apex_resign_needed: !!(integration && integration.apex_resign_needed) || Object.values(results).some(r => r && (r.fixed || r.built) && (r.fixed || r.built).apex_resign_needed),
  operator_merge: integration && integration.pushed ? `from a checkout that does not hold the branch: git fetch origin && git merge --ff-only origin/${INTEGRATION_BRANCH}` : null,
}

