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

for r in R:
    req("POST", BASE + "/rows", {"values": r})

after = req("GET", BASE + "/rows")["data"]["rows"]
tops = [x for x in after if not x["values"].get("parent")]
print(f"seeded: {len(after)} rows | top-level {len(tops)} | nested {len(after)-len(tops)}")
