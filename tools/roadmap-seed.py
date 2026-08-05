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

ONE MIGRATION IS OWED AND NOT DONE HERE. This script writes a single `when` per
row, which the new definition splits into `target` (an intention) and
`occurred_at` (a fact) — precisely so the table can answer "did this land when
we said it would", which one column cannot. Shipped rows should migrate to
`occurred_at`, queued rows to `target`. Doing it silently inside a seeding pass
would rewrite history no one asked to have rewritten, so it waits for a
deliberate run.

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

R = []
def row(slug, title, when, status, track, parent="", release="", refs="", body=""):
    R.append(dict(slug=slug, title=title, parent=parent, when=ts(when), status=status,
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
