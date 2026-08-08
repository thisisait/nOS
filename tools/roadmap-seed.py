#!/usr/bin/env python3
"""Create + seed the nOS Roadmap DataTable in KEAP.

THE BLOCKER THIS FILE CARRIED IS CLEARED (2026-08-03). It read: "the L1 concept
vocabulary has no concept that accepts `kind: date` (verified 2026-08-02 — none
of the 36 do), so a timeline table cannot live in state/keap-tables/ until
`time.occurred_at` is added to KEAP + the vendored copy." KEAP v1.39.0 adds
`time.target`, `time.occurred_at` and `time.verified_at`, and the copy is
re-vendored — so `state/keap-tables/roadmap.table.yml` now exists.

WHAT THAT DOES AND DOES NOT CHANGE. The definition is git-owned from here on.
The ROWS still come from this script, the same split as apps (app generator) and
systems (service registry); it is recorded in the seeder gate's UNSEEDED list
with that reason rather than left as an orphan.

THE OWED MIGRATION IS DONE HERE, IN THE WRITER (2026-08-07). This script wrote a
single `when` per row; the definition splits it into `target` (an intention) and
`occurred_at` (a fact), precisely so the table can answer "did this land when we
said it would", which one column cannot. Shipped rows now carry `occurred_at`,
everything else carries `target`.

WHAT FORCED IT was not the split but what the divergence hid. The definition and
this script had never been compared, and they disagreed twice: on the date column,
and on three `status` values (`active`, `next`, `parked`) that this script writes
into all 60 live rows and the definition did not list. A definition that would
reject every row its own writer produces is not a definition. Both halves are now
pinned by `tests/anatomy/test_the_roadmap_declares_the_table_it_fills.py`.

Declaring a deprecated `when` alongside `occurred_at` was tried first and refused
within the hour by `test_keap_table_concepts.py`: two columns may not claim one
concept, and `time.occurred_at` is the only concept `when` could honestly claim.
The L1 vocabulary has no name for a date that is sometimes a plan and sometimes a
fact. That absence is the answer.

WHAT IS STILL NOT DONE, AND IS NOW LOUD RATHER THAN SILENT. The LIVE table
predates the definition: nine columns, a single `when`, and none of `target` /
`occurred_at` / `verified`. Nothing applies the definition — the playbook seeds
only the three `face-*` tables. So this script PREFLIGHTS the live schema and
refuses, naming the missing columns, instead of writing dates into a column the
definition no longer has. Rewriting the 60 rows already filed stays out of scope:
that changes filed history and belongs to a deliberate migration, not a re-seed.

This script remains the reproducible path for rows: idempotent on the table (it
refuses to create a second one) and additive on rows.

Usage:  python3 tools/roadmap-seed.py [--dry-run]
"""

import json, sys, urllib.request, datetime
TABLE = "2d498264-bc9a-4324-9935-489e5e4d92f3"
BASE = f"http://127.0.0.1:8091/api/tables/{TABLE}"
H = {"X-Authentik-Username": "akadmin", "X-Authentik-Email": "admin@pazny.eu",
     "X-Authentik-Groups": "nos-providers,nos-admins", "Content-Type": "application/json"}
def req(m, u, b=None):
    r = urllib.request.Request(u, data=json.dumps(b).encode() if b else None, headers=H, method=m)
    with urllib.request.urlopen(r) as x: return json.loads(x.read())
def ts(d): return int(datetime.datetime.strptime(d, "%Y-%m-%d").timestamp())

#: A date on a shipped row is an observation; on any other row it is an
#: intention. The call sites still pass one date because at authoring time that
#: is all anyone knows — the STATUS is what says which kind of date it is, and
#: it is the only thing that can say so. Keep this the single place that decides.
SHIPPED = "shipped"

R = []
def row(slug, title, when, status, track, parent="", release="", refs="", body=""):
    at = ts(when)
    # Exactly one date key is SET, never both-with-one-null: a null in a column
    # is indistinguishable from a value nobody wrote, and the whole reason these
    # two columns exist is to keep an intention and a fact tellable apart.
    R.append(dict(slug=slug, title=title, parent=parent, status=status,
                  **({"occurred_at": at} if status == SHIPPED else {"target": at}),
                  track=track, release=release, refs=refs, body=body))

# ── Shipped releases — the spine ────────────────────────────────────────────
rel = [
 ("v0-1","v0.1-beta","2026-05-15","first tag"),
 ("v0-2","v0.2-beta — plugin wiring + health-wait","2026-05-24","A19: notification routing unified 55/55, in-stream health-wait replaces blocking --wait"),
 ("v0-3","v0.3-beta — observability veins","2026-05-30","grafana-wing datasource, agent serialization, fleet review"),
 ("v0-4","v0.4-beta — Linux port","2026-06-01","Ubuntu 24.04 end-to-end; macOS byte-identical; systemd --user units"),
 ("v0-5","v0.5-beta — SSO/MFA coherence","2026-06-08","posture B default, SEC-02 header-trust isolation, REM-043 n8n SSRF"),
 ("v0-6","v0.6-beta — OpenTofu Authentik cutover","2026-06-12","ADR-0001 Phase 1: tofu owns providers+applications+outposts"),
 ("v0-8","v0.8-beta — KEAP cortex 1.0 GA","2026-07-13","cortex as anatomy organ; v0.7 line absorbed into this tag, never separately tagged"),
 ("v0-9","v0.9-beta — face + self-model","2026-07-23","nOS face becomes a window manager; KEAP models nOS's own architecture"),
 ("v0-10","v0.10-beta — stop believing success reports","2026-08-02","188 commits. Delivery stamping on failure, a scan stamping freshness, a daemon older than its code, 175 swallowed failures vs 2 asserts"),
]
for slug, title, when, body in rel:
    row(slug, title, when, "shipped", "release", release=title.split(" ")[0], refs="RELEASE.md", body=body)

# ── v0.10 sub-steps, to demonstrate the nesting ─────────────────────────────
row("v0-10-genome","Genome L1 + the schema write path","2026-08-01","shipped","cortex",parent="v0-10",
    refs="state/genome/entity.schema.json · nos-genome-and-organelles.md",
    body="First cross-file $ref in the estate. 32 of 76 L1 columns reach the DB — apps/systems are annotated in git only.")
row("v0-10-parity","Cortex corpus parity AGREE, streak 6","2026-08-02","shipped","cortex",parent="v0-10",
    refs="~/.nos/cortex-corpus-diff.json", body="2500/2500 taxonomy nodes, knowledge_objects[fs:] 317/317, relations 1438/1438.")
row("v0-10-audits","Two adversarial audits + the converge audit","2026-08-02","shipped","platform",parent="v0-10",
    refs="test_post_wiring_is_not_self_reporting.py", body="26 agents, 27 surviving findings. Then the converge found three more that no static pass could.")
row("v0-10-linux","Linux wet-test reaches ok=550","2026-08-02","shipped","platform",parent="v0-10",
    refs="docs/hidden_fees/08", body="Was ok=226. Cortex mount sentinel + the ungated-brew class fixed. Still red at the smoke gate — the estate does not serve.")

# ── SECURITY — the active epic ──────────────────────────────────────────────
row("sec","Secrets — kill the blast radius","2026-08-02","active","security",
    refs="docs/archive/secret-blast-radius.md", release="v0.11",
    body="One leaked string yielded 103 credentials. REM-144 leaked exactly that string. Operator priority: highest.")
row("sec-p4","P4 — blast radius becomes a measured number","2026-08-02","shipped","security",parent="sec",
    refs="tests/anatomy/test_secret_blast_radius.py",
    body="Ratchets, not targets: declared 101, runtime 86, crown jewels 0. The gate caught its own first version reading declarations instead of runtime.")
row("sec-p0","P0 — weak-prefix gate loses the local carve-out","2026-08-02","shipped","security",parent="sec",
    refs="REM-151 · main.yml", body="REM-144 leaked the prefix from a LOCAL install, so 'local is not exposed' was already disproven.")
row("sec-p2","P2 — archive key stops deriving from the prefix","2026-08-02","shipped","security",parent="sec",
    refs="roles/pazny.backup · tasks/restore.yml",
    body="A KEY RING, not a swap: current key writes, retired keys still read. A bare swap would have orphaned every existing archive.")
row("sec-p1","P1 — HKDF derivation + per-user scope","2026-08-03","next","security",parent="sec",
    refs=".claude/workflows/p1-hkdf-derivation.js",
    body="The structural fix: a leaked credential becomes 32 random bytes. Needs a blank — 86 passwords change at once. Workflow written, NOT run.")
row("sec-p3","P3 — canary that makes a leak observable","2026-08-03","queued","security",parent="sec",
    refs="secret-blast-radius.md P3", body="A credential no service uses, rendered where real ones are. If presented, a rendered artifact was read.")
row("sec-p5","P5 — OS keychain for the master only","2026-08-03","queued","security",parent="sec",
    refs="secret-blast-radius.md P5",
    body="Shrinks from 86 items to 1 AFTER P1. Verified live: a launchd agent reads the login keychain non-interactively.")
row("sec-rem","Open HIGHs — REM-152 n8n 17-GHSA wave","2026-08-02","queued","security",parent="sec",
    refs="docs/llm/security/remediation-queue.json", body="Cycle-21, unattended nightly. 15 pending, 0 CRITICAL.")

# ── FILESYSTEM ─────────────────────────────────────────────────────────────
row("fs","One filesystem","2026-08-01","active","filesystem",
    refs="docs/archive/one-filesystem-architecture.md",
    body="The estate can hold one document in three disjoint places. Measured, not built.")
row("fs-s0","S-0 — one canonical identity","2026-08-01","active","filesystem",parent="fs",
    refs="tasks/stacks/authentik_service_post.yml",
    body="Nextcloud keyed accounts on a HASH of the canonical uid. Fixed forward; the legacy hashed account is still live and unmigrated.")
row("fs-s1","S-1 — Nextcloud mounts the VFS tree RW","2026-08-05","queued","filesystem",parent="fs",
    refs="one-filesystem-architecture.md S-1", body="The testable thing: open a .docx in ONLYOFFICE, save, verify the bytes changed in the VFS tree.")
row("fs-peruser","Per-user containers","2026-08-10","queued","filesystem",parent="fs",
    refs="docs/archive/per-user-container-roadmap.md",
    body="Measured: apple/container start 2.1s vs Docker 2.4s; per-user prices CONCURRENCY, not headcount. Blocker: macOS Local Network permission cannot be granted from a playbook.")

# ── CORTEX ─────────────────────────────────────────────────────────────────
row("cortex","Cortex integration — the next major arc","2026-08-03","next","cortex",
    refs="docs/archive/nos-cortex-lang.md · cortex-self-core.md", body="Operator's stated next direction after the v0.10 release.")
row("cortex-lang","nos-cortex-lang — ontology-typed pipeline IR","2026-08-05","queued","cortex",parent="cortex",
    refs="nos-cortex-lang.md · nos-cortex-lang-wing-executor.md",
    body="WrenAI independently converged on the same validate/execute split and hashed contract — external evidence the design is right. Their enumeration-oracle error is the thing to NOT copy.")
row("cortex-exec","Wing cortex-lang executor","2026-08-07","queued","cortex",parent="cortex",
    refs="nos-cortex-lang-wing-executor.md", body="Designed, NOT built: files/anatomy/wing/app/Cortex/ does not exist. Blocks the hydrator.")
row("cortex-rows","syncRows — rows as first-class objects","2026-08-06","queued","cortex",parent="cortex",
    refs="nos-genome-and-organelles.md B2", body="Ratified D3=materialised; graphMetaSchema already accepts mode:'rows'.")
row("cortex-readers","ZIM/EPUB readers","2026-08-08","queued","cortex",parent="cortex",
    refs="cortex-corpus-parallel.md",
    body="The user tree measures at ONE real document; Kiwix and Calibre are deep-linked, never read. Extraction is the second bottleneck — this is the first.")

# ── FACE ───────────────────────────────────────────────────────────────────
row("face","nOS face — DataTables + explore","2026-08-02","active","face",
    refs="files/anatomy/face", body="Four render styles shipped; the settings surface is the open half.")
row("face-styles","Style picker in the panel + per-style settings","2026-08-03","next","face",parent="face",
    refs="operator request 2026-08-02",
    body="Style chosen at table creation; a dropdown beside +Add row to switch back to grid; per-blog column selection and ellipsis length; a view modal with copy-to-clipboard.")
row("face-tree","Tree rendering for nested tables","2026-08-04","queued","face",parent="face",
    refs="this table", body="Roadmap rows nest via `parent`. KEAP has no rowRef kind, so integrity is seed-gated, not schema-enforced.")

# ── PLATFORM ───────────────────────────────────────────────────────────────
row("plat","Platform truth","2026-08-02","active","platform",refs="docs/hidden_fees/",
    body="The layers that report success they did not earn.")
row("plat-linux","Linux estate must actually serve","2026-08-05","blocked","platform",parent="plat",
    refs="docs/hidden_fees/08", body="Playbook completes (ok=550) and 1/8 smoke probes pass. Infra stack does not come up. The gate is honest now; the port is not done.")
row("plat-ollama","Ollama 0.30.7 -> 0.32.5, drop the local tap","2026-08-03","next","platform",parent="plat",
    refs="technosideas/swama.md",
    body="homebrew-core now builds AND tests llama-server; the tap's reason is gone. Consumers: hermes, openclaw, open-webui, keap embeddings, face ask, opencode. n8n's credentials live in its own DB and the playbook cannot see them.")
row("plat-v07","38 v0.7 plan docs, none implemented","2026-07-09","parked","platform",parent="plat",
    refs="docs/archive/v07-overnight/",
    body="All target branch feat/v0.7-overnight, which has ZERO commits not already in master. Either fold the live ones into the backlog or archive them; leaving 38 'PLAN (not implemented)' docs is noise that looks like a plan.")
row("plat-signing","Commit signing is required and never satisfied","2026-08-02","queued","platform",parent="plat",
    refs="CLAUDE.md git workflow",
    body="The master ruleset requires signatures; the v0.10 push logged 'Found 188 violations' and admin-bypassed. Either enable commit.gpgsign or drop the rule.")

# ── Anatomy app — the row the three view workflows implement ───────────────
row("face-anatomy", "Anatomy app — one window, three read-only views", "2026-08-04",
    "queued", "face", parent="face",
    refs=".claude/workflows/anatomy-view-{pulse,bone,wing}.js",
    body="Wing / Pulse / Bone as three views of ONE app, not three apps: a pulse run, a "
         "wing event and a bone action share an actor_action_id and are one story, which "
         "three windows lose. Read-only for now; actions stay in Wing UI where the tier "
         "gates already are. Each view has a committed workflow spec — that commit IS the "
         "triage gate, see docs/doctrine/workflows.md.")
row("sec-pulse-env", "The job catalog handed out 57 live credentials", "2026-08-05",
    "shipped", "security", parent="sec",
    refs="files/anatomy/wing/app/Presenters/Api/PulsePresenter.php withoutSecrets()",
    body="Found while grounding the face Anatomy view: GET /api/v1/pulse_jobs returned each "
         "job's env_json verbatim — 57 live values across 23 of 25 jobs, incl. Bone's HMAC "
         "secret x15, the Wing API token x11, agent client secrets x10, MariaDB root and "
         "MAIL_PASSWORD. Any Wing API token could read them from a listing whose own docblock "
         "calls it 'admin/debug'. Fixed at the source: values stripped, KEY NAMES kept (a name "
         "is not a credential, and it is the half an auditor needs). /pulse_jobs/due is "
         "untouched — the daemon needs the real env to run the job. Open question for triage: "
         "the same env blocks sit in cleartext in wing.db, which the nightly backup ships to "
         "RustFS; the API is the reachable surface, the store is the durable one.")

row("sec-queue-authorship", "The scan overwrites what a human wrote in the queue", "2026-08-05",
    "queued", "security", parent="sec",
    refs="docs/llm/security/remediation-queue.json · tools/scan-state-snapshot.py",
    body="remediation-queue.json is TWO records in one file — the scanner's findings and the "
         "operator's dispositions — and the scanner rewrites the whole file every night. "
         "MEASURED 2026-08-05: REM-144's resolved_by and resolved_detail, which carried the "
         "live-verification evidence for the Traefik prefix leak, were both null in the "
         "working copy and intact in the committed one. The scanner did not merge; it "
         "regenerated, and the fields it does not model went to null. Nothing noticed for a "
         "day, and the reconciliation was a two-way merge rather than the copy it looks like. "
         "Note also that the two sides spell the same fact differently — the scanner writes "
         "`resolution`, the human wrote `resolved_by`/`resolved_detail` — which is the usual "
         "shape one layer down. THE FIX IS NOT 'be careful': either the scanner reads the "
         "committed file and preserves unmodelled fields, or dispositions move out of the "
         "generated artifact entirely. FOUND BY THE LOOP, and that is the part worth keeping: "
         "the ledger refused to key a retry ceiling on uncommitted evidence, which is what "
         "made anyone look at the file at all.")

# ── Local-LLM cortex pipeline — filed 2026-08-04, DESIGNED NOT DECIDED ──────
#
# Filed here rather than in a doc so the planner can revise it and the operator
# can approve implementation from the UI instead of from a conversation.
#
# THE DATES ARE FILING DATES, NOT TARGETS. `when` is one column that the
# git-owned definition already splits into `target` (an intention) and
# `occurred_at` (a fact) — the migration this file's docstring says is owed and
# deliberately not done. Until it lands there is nowhere honest to put "no
# target set", so these carry the day they were filed and say so.
#
# WHAT IS ALREADY BUILT, so nobody re-plans it: the cortex language, parser,
# resolver, opcode registry and a four-phase validator all exist and are tested
# (files/anatomy/cortex/server/cortex-{lang,validate,resolve,opcodes}.ts).
# cortex-validate reports `authorizes: false` as a LITERAL CONSTANT so that no
# consumer can read `valid: true` as permission — that distinction is the spine
# of the whole plan below.
_FILED = "2026-08-04"

row("local-llm", "Local LLM proposes cortex chains, code validates", _FILED,
    "queued", "cortex", refs="cortex-validate.ts · nos-cortex-lang",
    body="A user says 'založ nového obchodního partnera'; a SMALL local model emits a "
         "cortex-lang chain; deterministic code decides whether it is a valid program and "
         "whether it may run; a LARGE model is asked only whether the chain matches the "
         "INTENT. Motivation is measured: on 2026-08-04, 90% of multi-agent spend was "
         "context, not product — a model that holds the API surface in its weights pays no "
         "orientation tax. Rejected framing: 'the big model validates the call'. Validity is "
         "a type-check (free, built) and authorisation is RBAC (free, code); neither needs "
         "an LLM. Only intent does.")

row("local-llm-executor", "Wing executor — authorisation + execution (phase 2)", _FILED,
    "queued", "cortex", parent="local-llm",
    body="THE PREREQUISITE. KEAP owns phase 1 (parse, structure, resolution) and explicitly "
         "does not authorise. Nothing executes a validated chain yet, so everything below is "
         "theory until this exists. Scoped tokens on three axes (verbs / namespaces / "
         "tenants) per the executor design; read-only chains run freely, effectful ones need "
         "the confirm gate the estate already uses for destructive operations.")

row("local-llm-corpus", "Corpus generator: opcodes + validator as a free oracle", _FILED,
    "queued", "cortex", parent="local-llm",
    body="Synthesise chains from the opcode registry, run them through cortex-validate, keep "
         "the valid ones, and have a large model back-translate each into the sentence a user "
         "would have said. Distillation where the teacher runs once and the correctness "
         "filter is code. This is an unusually good starting position — most fine-tuning "
         "projects have no oracle to filter on. Do this SECOND: it also measures how large "
         "the space actually is, which decides whether a small model is worth training.")

row("local-llm-model", "The small local model", _FILED,
    "queued", "agents", parent="local-llm",
    body="Ollama MLX, local, free at inference. Train only after the corpus exists and its "
         "size is known. NOT to be trained on loop verdicts or judge outcomes — a model that "
         "learns to please the judge is reward hacking with an extra step, and the "
         "proposer/judge asymmetry exists to prevent exactly that. The task here is narrow "
         "and well-posed (natural language -> constrained typed IR), which is the case where "
         "fine-tuning genuinely beats prompting.")

row("local-llm-intent", "Intent grading — effectful chains only", _FILED,
    "queued", "agents", parent="local-llm",
    body="A chain can be valid, authorised, and still not be what was asked: 'create a "
         "partner' emitting a well-typed chain that UPDATES one type-checks perfectly. No "
         "checker catches that, so a large model grades how precisely the chain fulfils the "
         "request. Reserved for effectful chains — read-only ones do not earn the cost — and "
         "phrased as 'say in plain language what this will do' for the operator, rather than "
         "as a score, because a score is a comfortable place for a model to hide.")

# ── SERE — the environment the loop needs before it can be autonomous ───────
#
# Named by the operator 2026-08-05: Self Enhancing Recursive Environment. The
# name matters because "dreaming" was the first candidate and is already taken —
# `AgentKit/Memory/Dreamer.php` + `agent_memory_stores` are cross-session memory
# consolidation. One word for two things is the defect this estate spent the
# month removing from its own code; it should not be introduced into its
# vocabulary on purpose.
#
# THE ARGUMENT, in one line: a loop that modifies the estate cannot be verified
# against the estate it modifies.

_SERE = "2026-08-05"

row("sere", "SERE — an environment the loop can develop in", _SERE,
    "queued", "platform",
    refs="docs/doctrine/workflows.md §5 · tools/worktree-lease.py · nos_coexistence",
    body="Isolation for an autonomous loop, in three tiers, of which only two parallelise. "
         "Almost every part already exists and was built for another purpose — worktrees, "
         "the shape lease, the coexistence framework, tools/ci-local.sh, nos-stacks.sh, "
         "profiles/all-on.yml. SERE is composition, not greenfield; the one genuinely "
         "missing piece is a wet-test that does not pass an empty estate.")

row("sere-a", "Tier A — verification without an estate", _SERE,
    "next", "platform", parent="sere",
    refs="tests/anatomy · files/anatomy/face vitest · tools/ci-local.sh",
    body="pytest + vitest + syntax-check + the frozen CI venv. No containers, no shared "
         "resource, so it parallelises without a lock and 90% of loop iterations should "
         "never leave it. This tier is DONE — 2788 tests today — and enabling the loop "
         "against it costs nothing. Start here rather than waiting for the rest. "
         "SAY WHICH SETS THOUGH (review 2026-08-05): three of the five judges are "
         "estate-free, so Tier A unlocks the `fast` and `repo` sets and neither of the two "
         "that contain nos-smoke. `live` declares requires: live_estate and `full` is "
         "unattended: false — so until sere-c exists, an autonomous loop's best available "
         "verdict comes from 3 of 5 judges, and no unattended configuration ever runs all "
         "five. That is what makes sere-c a prerequisite rather than an upgrade.")

row("sere-b", "Tier B — an ephemeral estate that actually serves", _SERE,
    "blocked", "platform", parent="sere",
    refs="docs/hidden_fees/08 · plat-linux",
    body="Build an estate from nothing, verify, discard. CI does this on Ubuntu and it "
         "proves nothing: infra does not render, `docker compose up infra` returns rc=1, and "
         "the STRICT probe reports the empty result as `0/0 ready`. It was green for weeks "
         "with no containers at all. THIS IS SERE'S PREREQUISITE, not a detail — a loop "
         "whose test environment can pass empty is not autonomous, it is blind. Blocked on "
         "plat-linux; do not duplicate that work here.")

row("sere-c", "Tier C — the live estate is a mutex, not a test bed", _SERE,
    "queued", "platform", parent="sere",
    refs="files/anatomy/scripts/pulse-run-agent.sh · tools/worktree-lease.py",
    body="One Mac, one Docker daemon, one Traefik on :443, one Authentik: two estates do not "
         "fit on one machine, and coexistence provisions ONE service on a shifted port, not "
         "a parallel estate. So Tier C is a scarce serialised resource and needs a MUTEX, "
         "not a lease — the distinction is already drawn in-repo: worktree-lease.py guards a "
         "worktree's SHAPE (paths immutable, content free) while pulse-run-agent.sh takes an "
         "atomic mkdir lock because concurrent agent runs crashed every participant. A "
         "converge belongs to the second kind. SERE asks the operator for this key; it does "
         "not hold it.")

row("sere-hosts", "Linux and a VPS, with Macs as the fallback", _SERE,
    "queued", "platform", parent="sere",
    refs="docs/linux-port.md · .github/workflows/ci.yml",
    body="Operator's direction, 2026-08-05: multiple Macs would work but Linux plus a VPS is "
         "the right target and is wanted soon. It is also the cheaper answer — Tier B needs "
         "a host that can be created and destroyed, which a Mac cannot be, and v0.4-beta "
         "already provisions Ubuntu 24.04 end-to-end. Parallelism then comes from hosts "
         "rather than from contention on one daemon. Sequence it after sere-b: a second host "
         "running the same blind wet-test buys two blind wet-tests.")

# ── The loop's own gaps, distinct from the environment ──────────────────────

row("loop-operator-model", "The operator's five steps, written down", _SERE,
    "queued", "agents", parent="sere",
    body="Stated 2026-08-05, recorded so it does not live only in a conversation: (1) promote "
         "an idea from the planner to a plan; (2) review proposed plans and promote to a "
         "workflow; (3) release it — cron, or a manual run; (4) file ideas and plans through "
         "a channel OUTSIDE the master session (claw / hermes / a separate session); (5) "
         "manual testing, to be replaced by a real Playwright e2e suite. Step 4 is the "
         "riskiest, not the easiest: several channels writing ideas without dedup fills the "
         "planner with near-duplicates, and discovery already needs an `obs-` prefix and a "
         "slug-skip for exactly that reason.")

row("loop-driver", "The loop engine has no driver", _SERE,
    "queued", "agents", parent="sere",
    refs="files/anatomy/bone/{judges,ledger,budget,looproutes}.py",
    body="The engine is real: the proposer and the evaluator hold different bearer tokens, and "
         "no route lets a caller submit a verdict of its own — the input surface is absent "
         "rather than guarded, which is why there is nothing to bypass. But nothing schedules "
         "it: 9 proposals and 19 judge runs, all 2026-08-02/03, and no pulse job. It is a "
         "substrate awaiting a motor. The motor is also what closes the operator's five steps, "
         "which describe the way IN and not how iteration N+1 learns from N: a run must "
         "produce evidence, a judge read it, the ledger record it. "
         "CORRECTED 2026-08-05 (review): this row said budget.py was unused. It is not — "
         "looproutes.py imports it, serves it at GET /loop/budget, and enforces it on both the "
         "proposal and the seal. The live KEAP row still carries the wrong sentence; the "
         "seeder is additive and will not rewrite it.")

row("loop-reach", "What the loop may touch vs where the bugs are", "2026-08-05",
    "queued", "agents", parent="sere",
    refs="files/anatomy/bone/budget.py ALLOWED_ROOTS (§5.3)",
    body="§5.3 is a positive whitelist — roles/, files/anatomy/plugins/, tasks/, apps/, "
         "upgrades/, default.config.yml — and everything outside it is denied whether or not "
         "a rule names it. That is the right shape. The question the review raises is whether "
         "the shape matches where defects actually are, and the honest answer today is "
         "PARTLY. Measured against the four fixes of 2026-08-05: two sat in tasks/ and roles/ "
         "and were inside the loop's reach; two were not. tools/nos-smoke.py is outside "
         "(tools/ is not a root), and main.yml is outside (it is not listed) — so the orphaned "
         "coexist-provision/cutover/cleanup entry points, a defect discovery is well shaped to "
         "FIND, needed a fix the loop may not WRITE. Do not widen the list reflexively: "
         "main.yml is the orchestrator and default-denying it is defensible. The work is to "
         "decide deliberately, per root, and to record the reason — a proposer that keeps "
         "hitting a wall it cannot see is a proposer that learns to propose nothing.")

row("loop-forget", "Nothing records what was already tried", _SERE,
    "queued", "agents", parent="sere",
    refs="wing.db loop_forgets (0 rows)",
    body="An idea that was attempted and failed must be recorded AS attempted, or the planner "
         "proposes it again — and keeps proposing it. The table exists and is empty. This is "
         "the failure mode that makes a self-improving loop feel busy while going in circles, "
         "and it is cheap to close before there is a driver rather than after.")

# ── From the TechNosIdeas audits, 2026-08-07/08 ─────────────────────────────
#
# 24 candidates were audited and each carries a `decision` in that table. Only
# `decision: implement` earns a row here — that is what the word MEANS, and it
# is checkable against the table rather than being a mood. `steal`, `postpone`
# and `watch` deliberately get no row: the estate's most expensive documentation
# failure was 38 plan documents naming a branch with zero commits, and a row for
# every good idea is how that starts. The audit file is the record until a
# decision moves.
#
# The strongest signal in the batch was one nobody went looking for: THREE
# independent audits (openworker, cloudflare-os, channels-sdk) converged on the
# same missing organ — an agent can broadcast but cannot ASK. A9 notification
# fanout is one-way; there is no way for an unattended run to stop and wait for
# a human, and no way for a human to answer from whatever channel they are in.
_TNI = "2026-08-08"

row("agents", "Agents that can ask, and be graded", _TNI, "next", "agents",
    refs="documents/research/technosideas/{openworker,cloudflare-os,channels-sdk,skilltune}.md",
    body="Two capabilities the runtime lacks, both found by auditing other people's tools rather "
         "than by reading our own. AgentKit can act and can report; it cannot pause for consent, "
         "and nothing measures whether a prompt change made an agent better or worse.")

row("agents-inbox", "An agent can ask, and suspend until answered", _TNI, "queued", "agents",
    parent="agents", refs="technosideas/openworker.md · technosideas/cloudflare-os.md",
    body="openworker's inbox.py: resolve-once, first-responder-wins, the run SUSPENDS, and the "
         "answer may arrive from any channel via an id-token reply. cloudflare-os's Gatekeeper "
         "adds the better half — deferred approval with SIMULATED results, so the agent keeps "
         "going instead of blocking. Lands in Wing (queue + presenter), Bone (the API), Hermes "
         "(the reply path). ~2-4 days. Unblocks every unattended AgentKit run.")

row("agents-evals", "A prompt change must prove it did not regress", _TNI, "queued", "agents",
    parent="agents", refs="technosideas/skilltune.md · github.com/danielsogl/skills",
    body="The estate gates code and does not gate prompts: every agent.yml, system.md and rubric "
         "is unversioned against behaviour. Steal the mechanism, not the $199/yr product — eval "
         "cases hash-locked BEFORE a change, A/B against base, refuse on non-monotonic result. "
         "danielsogl/skills is the open reference (41 assertions, token accounting). ~1-2 days "
         "on AgentKit, which already owns the grader loop.")

row("loop-sandbox", "The loop's two named open questions have MIT answers", _TNI, "queued",
    "agents", parent="sere", refs="technosideas/shepherd.md · docs/idea/11-agentic-loop-contract.md",
    body="shepherd must not carry the loop — paper-launch alpha, mid-ABI-rewrite, and its "
         "meta-agent-as-judge premise is what the contract rejected. But two tested files answer "
         "questions the contract itself leaves open: _clonefile_carrier.py (APFS cp -c -R CoW "
         "sandbox, §9.2, hours) and _seatbelt_containment.py (deny-closed SBPL jail for the "
         "single-UID §3.3 boundary, ~1-2 days). Both belong in Bone's judges.py.")

row("face-planner", "The Planner is declared as existing and is not built", _TNI, "next", "face",
    parent="face", refs="technosideas/circle.md · state/keap-tables/roadmap.table.yml",
    body="roadmap.table.yml says 'RENDERED BY the nOS-face Planner app: board, tree, timeline'. "
         "Zero files under face/src mention planner — the third unchecked claim in that one file. "
         "circle (MIT, no backend) supplies two of the three readings: a grouped-board engine "
         "including the 'n issues hidden by filters' footer, which is absence-doctrine rendered "
         "in UI, and a timeline zoom ladder that now has target/occurred_at to draw. ~1-1.5 wks.")

row("local-llm-lfm25", "Benchmark LFM2.5-2.6B as the emitter", _TNI, "queued", "agents",
    parent="local-llm-model", refs="technosideas/lfm25-26b.md",
    body="The cheapest test of the whole local-LLM arc: first-party GGUF + MLX, ~2 GB, zero "
         "containers, one line in openclaw_additional_models. Its admitted weaknesses (agentic "
         "coding, knowledge recall) are precisely what cortex-lang designs out of the emitter. "
         "Judge with /agent/v1/validate against qwen3-coder:30b. CARRIES A LICENCE DECISION: LFM "
         "Open License v1.0 is $10M-revenue-conditional and derivatives inherit it — the first "
         "non-Apache weight in the estate, and that is the operator's call, not a benchmark's.")

print(f"prepared {len(R)} rows")

# ── Orphan gate: KEAP cannot enforce this, so the seeder must ───────────────
slugs = {r["slug"] for r in R}
orphans = [(r["slug"], r["parent"]) for r in R if r["parent"] and r["parent"] not in slugs]
if orphans:
    sys.exit(f"REFUSING: parent slugs that resolve to nothing: {orphans}")
dupes = [s for s in slugs if sum(1 for r in R if r["slug"] == s) > 1]
if dupes:
    sys.exit(f"REFUSING: duplicate slugs: {dupes}")
print("orphan check: OK · duplicate check: OK")

# ── Two defects, both found by running this file on 2026-08-04 ─────────────
#
# 1. `--dry-run` was in the usage line and NOWHERE ELSE. There was no argv
#    handling at all, so a run intended as a rehearsal wrote 43 rows to the
#    live table. A documented flag that does nothing is the estate's signature
#    defect wearing a new hat, and this one bit the person documenting it.
#
# 2. "additive on rows" meant literally additive: a second run POSTed every
#    row again, duplicating 38 slugs. The orphan/duplicate gate above checks
#    the rows this script PREPARES against each other, and never against what
#    the table already holds — so it passed while producing duplicates.
#
# Both are fixed here: the flag is real, and seeding reads existing slugs first
# and skips them. Deleting or updating an existing row is still deliberately
# out of scope — this script adds, and a change to a filed row belongs to the
# planner, not to a re-seed.
DRY_RUN = "--dry-run" in sys.argv

# ── Preflight: does the live table have the columns this script writes? ──────
#
# Added 2026-08-07 with the target/occurred_at migration. The live table was
# created before `state/keap-tables/roadmap.table.yml` existed and nothing has
# ever applied that definition — the playbook seeds only the three `face-*`
# tables. So the columns below may simply not be there, and a POST carrying an
# unknown key is the kind of failure that is easy to write and hard to read.
#
# This refuses BEFORE writing anything, names the missing columns, and exits
# non-zero — a step that cannot do its job must not exit 0. It runs under
# --dry-run too: a rehearsal that skips the check would rehearse the wrong run.
_live_cols = {
    c.get("key")
    for c in (req("GET", BASE)["data"].get("schema", {}).get("columns") or [])
}
_need = {k for r in R for k in r}
_missing = sorted(_need - _live_cols)
if _live_cols and _missing:
    sys.exit(
        "REFUSING: the live table is missing column(s) this script writes: "
        + ", ".join(_missing)
        + "\n  The live table predates state/keap-tables/roadmap.table.yml and"
          "\n  nothing applies that definition. Apply it (or add the columns in"
          "\n  the Planner) before seeding — do not widen this script to fit a"
          "\n  schema the definition has already moved past."
        + f"\n  live columns: {' '.join(sorted(_live_cols))}"
    )
if not _live_cols:
    sys.exit("REFUSING: could not read the live table's schema — "
             "cannot tell whether a write would land. Is KEAP up?")

existing = {
    r["values"].get("slug")
    for r in req("GET", BASE + "/rows?limit=500")["data"]["rows"]
}
fresh = [r for r in R if r["slug"] not in existing]
skipped = len(R) - len(fresh)
print(f"already present: {skipped} · to insert: {len(fresh)}")

if DRY_RUN:
    for r in fresh:
        print(f"  [dry] would insert {r['slug']:<24} {r['title'][:60]}")
    print(f"DRY RUN — nothing was written. {len(fresh)} row(s) would be inserted.")
    sys.exit(0)

for r in fresh:
    req("POST", BASE + "/rows", {"values": r})

after = req("GET", BASE + "/rows?limit=500")["data"]["rows"]
tops = [x for x in after if not x["values"].get("parent")]
print(f"seeded: {len(after)} rows | top-level {len(tops)} | nested {len(after)-len(tops)}")
