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

import json, subprocess, sys, urllib.request, datetime
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
row("sec-transport","Datastore transport — encrypted, not merely enabled","2026-08-23","active","security",parent="sec",
    refs="REM-217 · tools/tls-uptake.py · docs/hidden_fees/23",
    body="REM-009 closed on 'TLS enabled'. Measured 2026-08-22: mariadb 72 handshakes / 591811 connections, 23 of 42 pg backends plaintext incl. the vault, redis tls-port 0. Ladder: pg clients -> pg ciphers -> redis argv secret -> mariadb cert -> require_secure_transport.")
row("sec-transport-pg","PostgreSQL clients encrypt, and the pin resolves","2026-08-23","next","security",parent="sec-transport",
    refs="docs/hidden_fees/23-a-pin-that-never-rendered.md",
    body="The June require-pin read a role default out of scope and rendered prefer for nine weeks. Fixed at play scope + per-driver spelling. UNVERIFIED until a converge moves tools/tls-uptake.py off 38.5%.")
row("sec-transport-hedgedoc","HedgeDoc ignores sslmode in its connection URL","2026-08-23","next","security",parent="sec-transport",
    refs="tools/tls-uptake.py · roles/pazny.hedgedoc/templates/config.json.j2",
    body="MEASURED post-converge: the container env carried sslmode=no-verify and pg_stat_ssl still reported its backend ssl=f — the ONE plaintext backend of 40, so postgresql read 97.5%% instead of 100%%. MECHANISM, read in the running image rather than inferred: Sequelize 5.22.5 parses the URL query into dialectOptions, then postgres/connection-manager.js:96 copies it into pg through _.pick(['application_name','ssl','client_encoding',...]) — a list without `sslmode`. Not misread: picked out and dropped. `ssl` is on the list but must be an OBJECT, which no query string can express, so the control moved to a mounted config.json keyed by NODE_ENV; the URL is now clean and a gate keeps it clean. UNVERIFIED until a converge lets the probe decide.")
row("sec-transport-mysqld-exporter","The sixth MariaDB client, which the survey missed","2026-08-23","next","security",parent="sec-transport",
    refs="roles/pazny.grafana/templates/compose.yml.j2 · tools/tls-uptake.py",
    body="Found by sampling information_schema.processlist, NOT by reading the ladder — which enumerated five clients from a survey of the APPS. prom/mysqld-exporter:v0.19.0 connects to mariadb ~4x a minute carrying the mysqld_exporter credential in clear. It takes TLS only from --config.my-cnf (ssl-ca/ssl-mode) or --tls.insecure-skip-verify, verified against the binary's own --help; neither is set, so it is provably plaintext the way redis is. A my.cnf would also move the password off the env, but the file must be readable by the exporter's NON-ROOT user and a 0600 host file appears root-owned through VirtioFS — untested, which is why this is a row and not a patch. The lesson is the row's title: enumerate clients from the SERVER's connection list, not from a list of applications.")
row("sec-transport-redis","Redis: AUTH secret off the argv, then a TLS port","2026-08-23","queued","security",parent="sec-transport",
    refs="REM-217 remediation (1)",
    body="tls-port 0, 56 clients, secret readable by anything that can docker inspect. TLS needs every client URL moved to rediss:// — authentik, infisical, outline, freescout.")
row("obs-loop-dashboard", "The loop is a ledger nothing renders", "2026-08-29",
    "shipped", "platform",
    refs="files/anatomy/plugins/grafana-base/provisioning/dashboards/25-loop.json · docs/hidden_fees/32",
    body="loop_proposals/loop_judge_runs/loop_verdicts and agent_sessions hold 22/154/67/55 rows "
         "and no surface read them; tools/loop-status.py answers in a terminal and Grafana said "
         "nothing. 25-loop.json joins them on session_uuid. Two numbers it exists to make "
         "visible: 22 of 22 proposals name no session (the lineage fix is live and no proposal "
         "has been made since), and `ended_with_no_verdict` — a third of agent runs — which the "
         "old `Success rate` panel counted as success (fee 32; 72.7%% claimed vs 20.0%% honest).")

# TITLE CORRECTED 2026-08-30. It read "cortex-lang runs 390 chains and none of
# them is a pipeline" — the claim the body below withdraws, left standing in the
# one field every listing renders. The body had been fixed the same day and the
# title had not, so `tools/roadmap-status.py` printed the refuted sentence and
# the correction was two clicks away. A retraction that does not reach the
# headline is not a retraction.
row("obs-cortex-dashboard", "A cortex dashboard, and the wrong reading it produced first", "2026-08-29",
    "shipped", "cortex",
    refs="files/anatomy/plugins/grafana-base/provisioning/dashboards/26-cortex.json",
    body="The executor emits cortex_stage_begin/finish with the opcode, the chain id and the "
         "stage's effect, 390 of each, and nothing rendered them. MEASURED WHILE BUILDING IT: "
         "the headline said every one of the 390 chains was a SINGLE STAGE and that the typed "
         "pipeline IR had never executed a pipeline. THAT WAS WRONG, corrected 2026-08-30. The "
         "panel grouped stage events by actor_action_id, and the executor minted a fresh id PER "
         "STAGE — so no two stages of one chain ever shared the key a reader groups on, and the "
         "count could only ever be 1. The stage's own `index` was right all along and runs 0..6. "
         "Read from index: 190 one-stage, 183 two-stage, 20 three, up to seven long. The "
         "composition half of the language IS exercised. Fixed at the mint (one chain, one id, "
         "gate test_a_chain_is_one_action_not_many.py) and the panel now reads index. The lesson "
         "is the estate's oldest one wearing a new hat: a reader grouped by a key nobody sets "
         "correctly measures the bug, not the world — and this one put a false claim into a "
         "dashboard, a roadmap row and a report to the operator before anyone checked it. What "
         "survives from local-llm-corpus is separate and still true: the VALIDATOR does not "
         "constrain composition, which is about what may be emitted, not what has run.")

# ── the night of 2026-08-29: the organs get joined ──────────────────────────
row("wing-map", "Wing had no reader, so every question about it was a grep", "2026-08-29",
    "shipped", "platform",
    refs="tools/wing-status.py · tests/anatomy/test_the_wing_map_reads_both_dialects.py",
    body="The operator's words were that Wing is becoming a hard organ to get hold of. That is "
         "an unanswerable question, not a vague complaint: 33k lines of PHP, 48 presenters, 27 "
         "CLI scripts and 45 tables covering nine unrelated concerns, with nothing able to say "
         "which tables carry anything or what any of it costs. The reader answers per table — "
         "rows, bytes, writers, readers — and found on its first run that 97% of the organ is "
         "one table and 16 more hold nothing. Its detector reads BOTH dialects this codebase "
         "uses: a first draft matched raw SQL only and called ten tables write-only, most of "
         "them falsely, because Wing's repositories use Nette's fluent builder.")

row("ledger-payload-bound", "The vein carried 921 MB no organ has ever read", "2026-08-29",
    "shipped", "platform",
    refs="callback_plugins/wing_telemetry.py · docs/hidden_fees/33",
    body="wing.db held 380 248 events in 1.19 GB, of which 921 MB was result_json and 657 MB of "
         "that was task_ok alone — the full Ansible module result for every task that did "
         "nothing, single rows reaching 4.1 MB. The largest key across the sample was "
         "`invocation`: Ansible echoing back the module's own ARGUMENTS, the input filed as "
         "though it were the outcome. bound_result drops it and caps what remains at 16 KB, "
         "naming every omission in the row itself. Live the same evening: mean result_json "
         "10 425 bytes before, 1 242 after. The retention policy that should have caught the "
         "growth is expressed in days (365) on a ledger that reached a gigabyte in 36, so it "
         "could never once have fired.")

row("audit-anchor-earned", "One authorised discontinuity per converge, 99 of them", "2026-08-29",
    "shipped", "security",
    refs="files/anatomy/wing/bin/backfill-event-chain.php · docs/hidden_fees/35",
    body="A segment anchor is the verifier's permission to resume the hash chain at a prev_hash "
         "it cannot derive. The tool that records one says it must run after each OFF->ON "
         "toggle; post.yml ran it on every converge where the chain was merely ON, and the only "
         "idempotence guard compared the recorded anchor to the tail, which always moved. "
         "Ninety-nine anchors in five weeks, of which two or three were earned, and the nightly "
         "verify reports ok:true across all of them. The chain's entire value is that a "
         "discontinuity is remarkable. Now minted only when the tail is actually unsigned; the "
         "99 stay because each signs real history.")

row("pulse-lineage", "A scheduled run could not name the session it started", "2026-08-29",
    "shipped", "agents",
    refs="files/anatomy/pulse/pulse/daemon.py · tools/run-agent.sh",
    body="pulse_runs.actor_action_id is declared in the schema as the A10 key grouping a run "
         "with its events, and PulseRepository has accepted it since 2026-05-08. The daemon "
         "never sent one: NULL on all 56 051 rows. The agent half of the same lineage worked "
         "(54 of 55 sessions join to events by it), so the estate had one half of an audit "
         "trail and no way to see the join was severed. The daemon now sends its run_id — "
         "already handed to the child as PULSE_RUN_ID, so no second key is minted — and "
         "run-agent.sh adopts it as the session uuid. run_id == actor_action_id == session "
         "uuid == events.actor_action_id, and one SELECT reconstructs scheduler to ledger.")

row("obs-pulse-dashboard", "56 000 runs of the scheduled-job organ, unobserved", "2026-08-29",
    "shipped", "platform",
    refs="files/anatomy/plugins/grafana-base/provisioning/dashboards/27-pulse.json · docs/hidden_fees/34",
    body="Pulse runs every nightly job the estate has and had no Grafana surface at all. Its "
         "headline asks what a notification cannot: which declared job has gone quiet, since a "
         "nightly that stops firing looks exactly like one with nothing to report. Its first "
         "draft made fee 32's mistake one organ over — ranking discovery:contradiction-scan top "
         "of the failure list at 66.7% when all 16 were contradictions FOUND, and "
         "pulse_jobs.findings_exit_codes had said which codes mean that for months. The answer "
         "was already in a column and the new reader did not ask.")

# TITLE ADOPTED FROM THE TABLE 2026-08-30. git owns the title, so `--sync`
# would have overwritten the sharper sentence someone had already put in the
# live row with this file's vaguer one. The drift direction is worth naming:
# git-owned does not mean git-is-right, it means git is where the edit has to
# land — and an improvement made in the Planner is lost the moment anyone
# syncs unless it is carried back here.
row("dry-run-evidence", "20 refusals decide on evidence a --check never gathers", "2026-08-29",
    "shipped", "platform",
    refs="docs/hidden_fees/36 · tests/anatomy/test_a_dry_run_gathers_its_own_evidence.py",
    body="`command` and `uri` perform nothing under --check; the registered result is empty, "
         "`| default(0)` turns the absence into a measurement, and the preflight refuses. "
         "MEASURED: --tags wing --check failed twice on a healthy host — wrong frankenphp "
         "version on a host running exactly the pin, dead daemon on one answering 403. Both "
         "fixed and gated; the role now dry-runs clean at 438 ok. A scan finds twenty more of "
         "the same shape in restore, patch, dnsmasq, ollama, superset, keap and gitea paths, "
         "and NONE was measured — a full --check of main.yml stops at task 29 needing sudo, so "
         "nothing proves those twenty are reached. They are listed rather than edited on "
         "suspicion. The open work is checking them one at a time, not a sweep.")

row("dry-run-evidence-sweep", "Twenty more refusals of that shape, none measured", "2026-09-30",
    "next", "platform", parent="dry-run-evidence",
    refs="docs/hidden_fees/36 §Not closed",
    body="The scan lists twenty refusals in restore, patch, dnsmasq, ollama, superset, keap and "
         "gitea paths whose condition reads a register a --check never fills. NOT ONE WAS "
         "MEASURED: a full --check of main.yml stops at task 29 needing sudo, so nothing proves "
         "any of them is reached in a dry run, and editing twenty files on suspicion turns a "
         "small true finding into a large unverified diff. One was already checked and cleared "
         "this way — tasks/removal-verify.yml reads alarming on the list and is unaffected, "
         "because the `nos --remove` dry run is its own inventory mechanism and not Ansible "
         "check mode. The work is nineteen more of those, one at a time, by whoever needs the "
         "path. Deliberately UNVERIFIABLE: no command distinguishes not-yet-checked from "
         "checked-and-fine.")

row("notify-supersede","A notification that stopped being true has no way to stop being unread","2026-08-23","next","platform",
    refs="tools/red-status.py::_still_holds · docs/hidden_fees/26 · bin/reconcile-inbox.php",
    body="MEASURED THE MORNING AFTER IT SHIPPED, and the wiring being complete was a false green about my own work. Schema, ALTER sweep, four emitters and the reader all landed; the 01:02 backup emitted WITH its supersede_key and retired ZERO rows, because the mechanism matches on the key and every historical row predates it. From tonight each nightly retires exactly its own predecessor and the 57-row backlog the feature was built for sits for ever. The probe now counts the deliverable — unread, un-superseded rows from an emitter that has SINCE declared it repeats, where a newer row from that emitter exists — and reads `restated:57`: os-resume 30, backup 19, backup-verify 5, security-drift 3. THE PATH IS NOT A BACKFILL OF THE KEY, which would be me guessing a class on the sender's behalf; it is bin/reconcile-inbox.php, which already marks rows read only on evidence and deliberately leaves report rows alone. It now HAS evidence for them: a newer row from the same declared-repeating emitter. That extension needs it to write superseded_at rather than wing_inbox_read_at — nobody read them — which is a decision about which tool owns which state, deliberately not taken at 05:40.")
row("sec-backrest-auth","Backrest runs with auth disabled, reachable by 23 containers","2026-08-23","next","security",parent="sec",
    refs="REM-214 remediation (1) · roles/pazny.backrest/templates/config.json.j2",
    body="Measured: POST /v1.Backrest/GetConfig from inside devops-gitea-1 -> 200, auth:disabled. The template justified it as 'loopback only', which REM-194/214 disproved. Not a template edit: config.json is seed-once and daemon-owned, so the live file needs reconciling and a bcrypt credential minting. Config surface includes hook commands.")
row("sec-transport-mariadb","MariaDB: cert on disk, clients, then the switch","2026-08-23","queued","security",parent="sec-transport",
    refs="docs/idea/21-mariadb-tls-ladder.md",
    body="Root password crosses three networks. Rungs 1+2 (cert on disk, server reads it) shipped 2026-08-23; rung 3 (the five clients) written the same day. THIS row is rung 4 — require_secure_transport — and it is a cliff: measured 1 of 9 NEW connections encrypted before rung 3, so flipping it early refuses the estate. It comes after tools/tls-uptake.py --window reads near-100%%, and a gate fails today if it appears.")
row("sec-transport-mariadb-clients","The MariaDB clients, and the five different knobs","2026-08-23","next","security",parent="sec-transport",
    refs="tests/anatomy/test_mariadb_client_tls.py · docs/idea/21-mariadb-tls-ladder.md",
    body="The ladder scoped this as MYSQL_ATTR_SSL_CA per Laravel client. Read in the running images, that is true of ONE of the three: bookstack MYSQL_ATTR_SSL_CA, freescout DB_MYSQL_ATTR_SSL_CA, firefly MYSQL_SSL_CA plus a second gate MYSQL_USE_SSL. WordPress can encrypt (MYSQLI_CLIENT_SSL, measured) but cannot verify — wpdb never calls mysqli_ssl_set. Nextcloud has no env at all. MEASURED AFTER THE CONVERGE, and the first reading was WRONG: bookstack, firefly and wordpress are genuinely encrypted; FREESCOUT IS NOT. Its env resolves (`env(...)` returns the path) but Laravel CACHES config, so `config(database.connections.mysql.options)` is {1013:true} with no CA — the app never sees the variable. The self-test that reported it green read the ENV instead of the app; it now boots the app kernel and reads what the app RESOLVES, which is the only question with a true answer. Nextcloud is UNKNOWN pending a converge: its value is now a rendered *.config.php overlay rather than an occ call, because occ bootstraps the database and cannot repair the option that stops the database opening.")

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
    refs="nos-cortex-lang-wing-executor.md",
    body="Designed, NOT built: files/anatomy/wing/app/Cortex/ does not exist. Blocks the "
         "hydrator. THE DESIGN'S TWO OPEN INTEGRATION RISKS ARE NOW MEASURED CLOSED "
         "(2026-08-08). §8.6 called the Wing-host -> KEAP-container path 'the one genuine "
         "integration risk' — KEAP publishes 8080/tcp on 127.0.0.1:8091, the host gets "
         "/agent/v1/health in 0.09s. §8.5 asked which role mints the RO token into Wing — the "
         "running daemon already carries KEAP_API_URL, KEAP_AGENT_TOKEN_RO and _RW, declared "
         "in its plist. So this is a Wing-only build with no network work: phase 1 is live in "
         "KEAP (validate accepts chains, rejects unknown opcodes, warns on deferred "
         "namespaces), and nothing executes.")
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
row("face-tauri","face2tauri — one shell recipe for macOS, Linux and Windows","2026-08-27","next","face",parent="face",
    refs="Omarchy 4.0 Quattro (2026-08-14) · quickshell.org · files/anatomy/face",
    body="Studied 2026-08-27 after the operator asked whether Quickshell could give one UI recipe for Linux and Windows. It cannot: Quickshell is Wayland/X11 only, and its author's own words on the ports are 'I have not done much research yet and do not plan to until the Linux version is in a state I am happy with', with Windows/macOS planned as a PAID tier. An unresearched intention gated behind another platform's maturity is not a foundation. The cross-platform answer nOS already has is face — a browser runtime renders identically on all three. What face cannot be is the HOST SHELL (bar, launcher, lock screen, polkit agent), which is what Quickshell is for. So this row is NOT 'port face to Quickshell': it is Tauri (Rust + system webview) WRAPPING the existing face, one binary per OS, reusing what is built rather than replacing it. Quickshell would only ever be a Linux-side host-shell layer above that, and only if nOS decides it wants to own the host shell at all — which is a product decision nobody has made. ELEVATED 2026-08-28 (operator): queued -> next, and named the TOP CANDIDATE for the next development. What changed is not the study above but a second consumer: the command centre [cc-app] wants the same DataTable-driven backend, so the projection face already reads stops being a face concern and becomes the shared one. Tauri wraps the browser face; the command centre is a separate front door onto the same tables, not a competing UI. Sequence that follows: settle the projection, then wrap it — wrapping first would freeze a contract two consumers have not agreed on.")
row("face-loop-view", "A loop is a selection, not a filter — draw one at a time", "2026-08-29", "next", "face", parent="face",
    refs="tools/anatomy-graph-gen.py · files/anatomy/face/src/lib/anatomy/ · docs/plans/rsi-research/02-visualisation.md · state/anatomy-graph.json",
    body="Operator, 2026-08-29, looking at the shipped Anatomy graph: 'aktuální graph v anatomy můžeme klidně překopat'. Both layouts were read side by side and both are unusable at 236 nodes / 266 edges — force gives a hairball, non-force a wall of parallel curves. THE DIAGNOSIS IS SELECTION, NOT RENDERING: the view draws everything at once and its fifteen kind-filters answer 'show me all agents', never 'show me one loop'. A third dimension applied to that is a third dimension of hairball, which is why the 3D-axes sketch is NOT what this row builds. WHAT IS ALREADY RIGHT AND MUST SURVIVE: (a) the compiler is the source of truth — every node and edge is DERIVED by tools/anatomy-graph-gen.py from the manifests, never hand-authored, and the footer says the data is as fresh as the last converge rather than pretending to stream; (b) the detail panel is good — live state, schedule, source manifest, cited doctrine (§5.3 with its file:line) and typed edges DATA / GOVERNED_BY / TEMPORAL / TRIGGER; (c) THE GRAPH ALREADY FINDS CYCLES and names their kind — the shipped header reads 'union-kind cycle (feedback loop, review-not-refuse): pulse:cortex:cortex-fs-sync -> pulse:keap:keap-embed-sync -> pulse:cortex:cortex-corpus-diff -> pulse:cortex:cortex-fs-sync'. It can detect a loop and cannot show one. THE BUILD: make a loop a first-class selection — pick a loop, draw only its participants and their edges, and only on that reduction does an animation of flowing data have anything to say. STAYS 2D IN FACE (operator, 2026-08-29); a KEAP import is a later maybe, never a renderer dependency, so this row creates no cross-repo contract [plat-dep-contracts]. STILL MISSING FROM THE MODEL: the DataTable-defined loops of the two planes are not compiled in at all today — they must enter through the compiler like everything else, not be drawn from a second source. Pairs with [cc-app]: same projection, different front door.")
row("cc-app","The command centre becomes an app, not a pane layout","2026-08-28","next","face",parent="face",
    refs="tools/nos-cc.sh · tools/nos-watch.sh · tools/workflow-tree.py · files/anatomy/agents (IIAB Terminal precedent)",
    body="Operator, 2026-08-28: the tmux control centre is 'dost chabé' and is to be replaced by something modern and interactive — tables rather than prose, navigation between runs, toggleable detail like the Claude Code TUI's workflow view — and portable, reachable from a phone (Mochi/Blink over SSH). Runs as a PARALLEL track to [face-tauri], sharing its DataTable-driven backend: one projection, two front doors. What is already right and must survive: every pane re-runs a READER and shows STATE, never scrollback (tools/nos-watch.sh; a tailed log looks healthy right up until its writer stops). What is wrong today, measured: agents and red-status render as prose lists where the data has rows and columns; git log carries no HEAD marker; the workflow pane was unscrollable until `mouse on` (2026-08-28); and nothing is interactive at all. Substrate candidate is Python Textual — the estate already ships one (IIAB Terminal, SSH ForceCommand), which makes the phone story a property of SSH rather than a port. Every data source exists and is a reader already: red-status.py, agent-status.py, roadmap-status.py, loop-status.py, workflow-tree.py. Not started; this row exists so the ask is filed rather than carried in a conversation.")
row("cc-approvals", "What cannot proceed without a person, collected", "2026-08-29", "shipped", "face", parent="cc-app",
    refs="tools/awaiting-operator.py · tools/apex-sign.py · tools/nos-cc.sh ops.1",
    body="red-status answers what BROKE; this answers what cannot proceed without a human, and they are not the same list. A judged proposal that never landed is not red; an agent that stopped to ask is working as designed; a signed ruling amended after signing is neither. Until 2026-08-29 nothing collected them, so each was found by remembering to look. Shipped as a reader (questions, unread CRITICAL/HIGH inbox, unlanded verdicts delegated to loop-status rather than re-derived, and the apex signature) plus a pane under `what is red`. FOUND WHILE BUILDING IT, and closed: the apex signature was a FLAG, not a promise — `status: SIGNED` plus a name records that someone once signed something, not that they signed THIS, and a session amended a SIGNED ruling the same day with every gate green. `signed_digest` is now sha256 over the file without that line; tools/apex-sign.py shows the diff first and takes --confirm as a separate act, because a signature that can be given without reading is the flag again under a longer name.")
row("cc-tui-variants", "Five TUI prototypes, built to be chosen between", "2026-08-29", "next", "face", parent="cc-app",
    refs="worktree branches worktree-agent-a583677b/a928889a/aa90af61/ad8d3436/ad0a5d37",
    body="Operator asked for at least five variants in isolated environments, all clean and data-oriented so an LLM can read the session as well as the admin. Built in parallel git worktrees so none could sweep another's work — the lesson of 2026-08-28, when a git add -A in a shared tree put a concurrent session's 1090 lines under three of this session's commits. A: fixed 3x2 dashboard, no navigation, glance-and-know. B: six keyed one-subject views with drill-down. C: one ranked queue of everything that wants the operator. D: NOT a Textual app — the tmux shape kept and every prose pane replaced by a table through one shared renderer, on the thesis that the container was never the defect. E: the timeline, joining pulse runs, agent sessions and proposals on actor_action_id to show lineage rather than assert it. Every variant ships --demo and --dump json, and each names what it is BAD at in its own header. NOT YET JUDGED: the operator picks, and the losers are deleted rather than merged — five half-adopted TUIs is worse than the tmux panes they replace.")
row("face-app-builder","A builder where a tenant creates apps that cannot violate the standards","2026-08-27","queued","face",parent="face",
    refs="apps/_template.yml · files/anatomy/module_utils/nos_app_parser · docs/tier2-app-onboarding.md",
    body="Operator ask 2026-08-27, framed as 'something like Lovable, so a user can create custom apps that keep hard standards'. The standards half already exists and is the hard part: nos_app_parser REFUSES a manifest without a complete Article-30 gdpr block, and the runner derives routing, SSO, secrets and observability from the manifest rather than trusting the author. What is missing is only the surface — today authoring an app means editing YAML and knowing what a legal_basis enum is. The build is therefore a GUIDED EDITOR over apps/<name>.yml whose validity check is the parser itself, not a re-implementation of it: one schema, two front doors. Two things it must not become: a generator that emits manifests the parser would reject (the standards stop being hard the moment a second definition exists), and a chat box that writes YAML unvalidated. Pairs with [agents-nos-skill] — the skill is the same contract for an agent, the builder is it for a human.")

# ── PLATFORM ───────────────────────────────────────────────────────────────
row("plat","Platform truth","2026-08-02","active","platform",refs="docs/hidden_fees/",
    body="The layers that report success they did not earn.")
row("plat-linux","Linux estate must actually serve","2026-08-05","blocked","platform",parent="plat",
    refs="docs/hidden_fees/08", body="Playbook completes (ok=550) and 1/8 smoke probes pass. Infra stack does not come up. The gate is honest now; the port is not done.")
row("plat-brew-lag","A pin that lags upstream instead of chasing it","2026-08-27","next","platform",parent="plat",
    refs="roles/pazny.openclaw/tasks/main.yml:99 · default.config.yml ollama_version · Omarchy update channels",
    body="The ollama pin guard has now fired three times (0.32.14->15 on 08-22, 0.32.15->0.33.0 mid-converge on 08-27) and every time the RECORD followed brew, after a failed converge. That is `state: latest` deciding and the repo transcribing. Omarchy's answer is a stable channel deliberately running a month behind Arch, 'so we can catch incompatibilities before they cause problems' — and mise ships the same primitive as MISE_MINIMUM_RELEASE_AGE. For brew there is no lagged mirror, so the lever is `state: present` plus a deliberate advance: a reader reports which pins have a newer version that has been out longer than the lag window, and moving the pin becomes an act with a commit rather than a surprise mid-run. THE TRADE, which must be stated wherever this lands: `present` means a security fix does not arrive by itself. The carve-out is the security floor already in docs/doctrine/security-floor.md — a CVE advances the pin immediately, lag or no lag.")
row("plat-dep-contracts","A contract with a dependency that will never run our gate","2026-08-29","next","platform",parent="plat",
    refs="docs/doctrine/cross-repo-contracts.md · docs/doctrine/foreign-properties.md · files/anatomy/skills/contracts/ · docs/archive/nos-genome-and-organelles.md",
    body="Operator asked 2026-08-29 whether nOS has standardised contracts with its FOSS dependencies the way it has one with KEAP. Measured: no. cross-repo-contracts.md is a finished protocol — one spec at one physical location, a FIXTURE owned by the producer (the shape itself, not a description of it), and SYMMETRIC gates, plus the three invariants where drift hides: identity, visibility, removal. Its Live-contracts table holds exactly ONE row (nOS self-model -> KEAP). files/anatomy/skills/contracts/ is adjacent but is the other direction: auto-generated OpenAPI/schema of OUR surfaces, with a CI drift job. WHY IT DOES NOT TRANSFER AS-IS: symmetry is that protocol's whole design, and it is unavailable here — Authentik, Gitea and Nextcloud will never run our gate. A dependency contract is one-sided by construction: nOS states what it needs and detects when the upstream stopped providing it, so the FIXTURE is owned by the CONSUMER. WHAT FILLS THE GAP TODAY, in pieces that cannot fail together: version pins, upgrades/*.yml from_regex, foreign-properties.md (the closest thing — a permanent accommodation must name the code that performs it), discovery-scan.py comparing declared against running. The 77 plugin manifests declare what nOS does TO a service; not one declares what the service PROMISES nOS, and `upstream:` in them is a homepage URL read by nothing but the graph generator's YAML-1.1 trap guard. This is the organelle diagnosis one storey up: what we know about Gitea is spread across a pin, a recipe, a manifest, a healthcheck and a doctrine section, and NONE of them goes red when Gitea changes its API — it surfaces months later as a 404 in a POST nobody reads. Shape to design against: the plugin declares the foreign endpoints, schemas and env keys it stands on, each with a pinned response from the version it was verified against, and a reader compares that to the running instance. Not started.")
row("plat-preconverge-snapshot","A snapshot before the converge, and an honest account of what it covers","2026-08-27","next","platform",parent="plat",
    refs="tools/snapshot-status.py · tmutil localsnapshot · Omarchy limine-snapper-restore",
    body="Omarchy snapshots via snapper before every update and keeps five, so a bad update is a reboot away from undone. nOS has backups (14 sources, restic copy #2 at /Volumes/SSD1TB/nos-restic) and a drill that genuinely replays them, but nothing atomic and nothing one step. MEASURED 2026-08-27, and it decides the shape: ~/wing, ~/keap, ~/stacks and ~/.nos are all on /dev/disk3s5, the APFS Data volume — snapshottable. nos_data_root is /Volumes/SSD1TB/nOS/data on /dev/disk7s2, which is Case-sensitive Journaled HFS+ and CANNOT be snapshotted at all. So this covers the ledger, the WORM audit chain and the KEAP knowledge DB, and does not cover the external data volume or RustFS copy #1 that lives on it. The preflight must NAME the uncovered paths rather than report a snapshot and let the operator infer coverage — a converge that believes it has a net and does not is worse than one that knows it has none. Recovery is mount_apfs read-only plus a copy, not a bootloader pick; say so. Reformatting SSD1TB to APFS would close the gap and is the operator's call, not a step of this row. THE PREREQUISITE IS ALSO NOT MET: `tmutil destinationinfo` reports no Time Machine destination on this host, and `tmutil localsnapshot` is documented to need one — the only local snapshots present are macOS's own com.apple.os.update-*. So the ordering is configure TM (or find a snapshot path that does not need it), THEN wire the preflight. tools/snapshot-status.py already reports all of this and is committed ahead of the mechanism deliberately: knowing there is no net is worth more than a net nobody has verified.")
row("plat-ollama","Ollama 0.30.7 -> 0.32.6, drop the local tap","2026-08-03","next","platform",parent="plat",
    refs="technosideas/swama.md · default.config.yml ollama_version",
    body="VERIFIED not assumed (2026-08-08): homebrew-core 0.32.6 builds llama-server "
         "(cmake --install llama-server) AND its test block spawns it against a GGUF model and "
         "asserts it listens. The tap's reason is gone. WHAT THE ABSENCE OF A PIN COST: "
         "pazny/local is not in homebrew_taps, so the playbook never knew it existed, and "
         "`state: latest` has meant 'latest within the tap' since June — two minor versions "
         "back for weeks while every run reported success. ollama_version is now declared and "
         "read back, and the failure names the shadowing tap. Remaining is one operator "
         "action: brew uninstall ollama && brew untap pazny/local && brew install ollama. "
         "Unblocks local-llm-grammar, which needs the llama-server the tap's build already "
         "had and core's older bottle did not.")
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
    refs="files/anatomy/cortex/scripts/corpus-gen.ts · tests/anatomy/test_the_cortex_oracle_filters_syntax_not_sense.py",
    body="GENERATOR BUILT AND RUN 2026-08-29; the premise needs correcting. 142 stage forms "
         "over 15 opcodes; at depth 2, 20306 of 20306 composed chains VALIDATE — a 100%% pass "
         "rate. `analyzeCortex` rejects STAGE-LOCAL faults (unknown opcode, unknown param, "
         "arity) and imposes no compositional rule at all: `insert | classify` and "
         "`classify | insert` both pass, `rank()` four times passes. So \"the correctness "
         "filter is code\" is TRUE ABOUT SYNTAX AND FALSE ABOUT SENSE, and a corpus filtered "
         "on validity alone is a grammar drill — grammar being the one thing the validator "
         "already checks at inference time without a model. The space size the row asked for: "
         "|stages|=142, unconstrained, so 142^n (20306 at n=2, ~2.9M at n=3). WHAT IS LEFT "
         "THAT IS REAL: the warning set is the only thing that discriminates between chains "
         "(deferred_namespace 15105, deferred_program 12296, mutating_default_dry_run 9975, "
         "commit_requires_confirm_gate 5985), and the natural-language pairing still needs a "
         "model. Both are work; the free lunch is not.")

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

_VOICE = "2026-08-30"

row("local-llm-voice", "Speak a command, see what it would do, rate what it did", _VOICE,
    "next", "cortex", parent="local-llm",
    refs="technosideas/swama · technosideas/voicebox · Apple SpeechAnalyzer (macOS 26) · state/ops-task-families/invoice-extract/family.yml",
    body="OPERATOR WANT, 2026-08-30: drive nOS by voice — judge the syntax-valid chain BEFORE "
         "it runs, execute it sandboxed, then rate the action on -1/0/1/2/3. PoC scope is "
         "DataTable control against `business-partners` (4 rows, already live), never the "
         "roadmap table. WHY IT IS ITS OWN ROW AND NOT A NOTE: every oracle in this arc so "
         "far is either code or a model. Code was measured to filter syntax and not sense "
         "(local-llm-corpus: 20306 of 20306 composed chains validate), and intent grading is "
         "a model grading a model. A rating typed by the person who spoke the sentence is the "
         "one label channel that is neither, and it costs the seconds between speaking and "
         "looking. TWO JUDGEMENTS, NOT ONE: 'is this chain sensible' is asked before "
         "execution, 'was that action right' after it, and one column meaning both corrupts "
         "the set — they disagree exactly where the grammar is fine and the world model is "
         "wrong, which is what qwen3:14b's only two failures already were (unknown_operand, "
         "namespace_not_resolvable). It does NOT contradict local-llm-intent's refusal of a "
         "score: that refusal is about a MODEL hiding behind a number, and the plain-language "
         "preview it asks for is exactly what makes a human rating possible. No new organ, "
         "port or daemon (loop-contract non-goals stand): ASR is an ingress in front of the "
         "emitter, and the executor with its binding gate already exists. What dictation does "
         "NOT solve, so nobody re-sells it later: it supplies the INPUT half of a test case, "
         "and the expensive half is the label — which is the half the star supplies.")

row("local-llm-voice-asr", "Which ear — and vocabulary before fine-tune", _VOICE,
    "queued", "cortex", parent="local-llm-voice",
    refs="developer.apple.com/videos/play/wwdc2025/277 · github.com/senstella/parakeet-mlx · github.com/Trans-N-ai/swama",
    body="Four candidates, all runnable on this host (macOS 26.6.1, Apple Silicon). Apple "
         "SpeechAnalyzer/SpeechTranscriber: on-device, no container, no download beyond the "
         "system model, claimed ~2x Whisper Large V3 Turbo — Swift-only, so it costs a small "
         "CLI wrapper. parakeet-mlx: pip plus a working CLI today, MLX, 68 minutes of audio "
         "in 62 seconds. swama: MIT, pure Swift on MLX, OpenAI-compatible "
         "/v1/audio/transcriptions — so it would join as a ROW in state/llm-backends.yml "
         "rather than as a new organ; its TechNosIdeas `refused` was decided by plat-ollama "
         "against ollama as an LLM RUNTIME and never judged the ASR half. voicebox: MIT, "
         "Whisper plus an MCP server, but its surface is TTS and voice cloning — wider than "
         "this row wants, and cloning is a separate operator decision deliberately not folded "
         "in. FINE-TUNING IS NOT THE FIRST MOVE. The failure will be vocabulary — opcode "
         "names, tax:02.02, service ids — and both SpeechAnalyzer contextualStrings and "
         "Whisper initial_prompt take a bias list the estate can already generate from the "
         "opcode registry and the taxonomy. Measure the hint first: one example in the prompt "
         "moved hermes3:8b from 0/6 to 2/6, and that gap was not in the parameters either.")

row("local-llm-voice-rating", "The star is a label, and it needs a writer that is not the rated thing", _VOICE,
    "queued", "agents", parent="local-llm-voice",
    refs="state/ops-task-families/invoice-extract/family.yml · docs/idea/02-cortex-lang.md",
    body="-1/0/1/2/3 needs every value defined before the first one is typed or the set is "
         "noise: -1 must mean 'would have done harm' and 0 'useless but harmless', because "
         "those are different signals and a scale that blurs them teaches the blur. Recorded "
         "per utterance: both ratings, the transcript, the emitted chain, the ASR engine and "
         "the model uri — the sentence is the constant and the BINDING is the variable "
         "(cortex-lang contract v2), so a run that does not record which model spoke is not "
         "comparable to any other. WHERE IT LANDS is a measurement, not a preference: wing.db "
         "already carries the lineage key (actor_action_id) and 390 cortex_stage events, and "
         "a KEAP DataTable already renders in face with no schema work — decide after "
         "counting what the PoC writes, not before. THE STANDING RULE HOLDS: local-llm-model "
         "forbids training on loop verdicts or judge outcomes. An operator rating is not a "
         "judge outcome — it is a hand-written label, the same provenance invoice-extract's "
         "samples have, and its own header forbids a model labelling a set it is later scored "
         "against. The day anything but a human writes this column, that distinction is gone "
         "and so is the corpus.")

# ── Local models — measured 2026-08-08, and the numbers reordered the arc ───
#
# The four rows above assume a model choice nobody had measured. One afternoon
# with `tools/local-model-bench.py` moved every assumption:
#
#   * `qwen3:14b` — the estate's own `openclaw_model` — makes the knowledge API
#     UNAVAILABLE while resident. Not slow: /agent/v1/health times out at 25s on
#     this M4 Max / 36 GB with 63 containers, and answers in 0.09s the moment
#     `ollama stop` runs. So model size is an ESTATE constraint, not a quality
#     trade-off, and `qwen2.5-coder:32b` at 19 GB was never a real option.
#   * `hermes3:8b` scored 0/6 emitting cortex-lang, every failure a syntax error
#     on an otherwise-correct pipeline. ONE worked example took it to 2/6 and
#     cut the time from 13s to 3s. The gap was the prompt, not the parameters.
#
# Which is why these rows come BEFORE the training row rather than after it.
_LMB = "tools/local-model-bench.py · state/local-model-bench.yml"

row("local-llm-bench", "Which models this box can actually host", "2026-08-08",
    "shipped", "agents", parent="local-llm", refs=_LMB,
    body="A harness that scores a model on the one job the estate has for it — emit a "
         "cortex-lang chain — with KEAP's validator as the judge, so no large model and no "
         "human is needed to grade it. Reports four numbers per model: valid, used-the-asked-"
         "for-opcode, tokens, and what /agent/v1/health answered in WHILE the model was "
         "resident. That last column is the one that disqualifies: a model this host cannot "
         "hold is not a candidate however well it scores.")

row("local-llm-grammar", "Grammar-constrained decoding, so syntax cannot fail", "2026-08-08",
    "next", "cortex", parent="local-llm", refs=_LMB,
    body="cortex-lang is a formal grammar with a closed opcode registry, and llama.cpp's "
         "llama-server supports GBNF constrained decoding — which makes a syntax error "
         "IMPOSSIBLE rather than rarer. Measured: 4 of 6 hermes3:8b failures were punctuation, "
         "not comprehension, so this converts the question from 'is the model smart enough' to "
         "'did it pick the right opcode', which is the part a 4B can plausibly do. Depends on "
         "the ollama that ships llama-server, i.e. plat-ollama — one thread, not two.")

row("local-llm-thinkingcap", "Evaluate ThinkingCap-Qwen3.6-27B on our tasks", "2026-08-08",
    "queued", "agents", parent="local-llm-model", refs="huggingface.co/bottlecapai/ThinkingCap-Qwen3.6-27B",
    body="Apache-2.0 finetune of Qwen3.6-27B from BottleCap AI (Prague), claiming ~46% fewer "
         "thinking tokens at equal accuracy — GSM8K -74.1% thinking tokens with accuracy rising "
         "93.3% -> 96.5%. Tokens are the axis a loaded box feels, so the claim is worth testing "
         "rather than admiring. GGUF and FP8 builds exist. HONEST CAVEAT: 27B at Q4 is ~16 GB "
         "and qwen3:14b at 14 GB already times the estate out, so this is a candidate only if "
         "run when the estate is idle, or on the SERE host once one exists.")

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

row("agents-nos-skill", "nOS ships no skill teaching an agent to extend it", "2026-08-27",
    "next", "agents", parent="agents",
    refs=".claude/skills/ · Omarchy manual/17-ai.md · docs/tier2-app-onboarding.md",
    body="MEASURED 2026-08-27: this repo has exactly ONE committed skill, `devlog`, and seven "
         "workflows. Every one of them is an INTERNAL development procedure — author history, "
         "run a review, build a face view. Nothing is shipped to the operator or a tenant. "
         "Omarchy ships a skill for tailoring the system and symlinks it into ~/.claude/skills, "
         "~/.codex/skills, ~/.pi/agent/skills, ~/.gemini/config/skills and ~/.agents/skills, so "
         "the USER's own agent knows how to change their desktop correctly rather than guessing. "
         "nOS has the stronger version of the thing a skill would protect — nos_app_parser "
         "refuses a manifest that skips Article 30, plugin manifests derive the wiring — and no "
         "text that hands an agent those rules. Scope: a skill for authoring an apps/<name>.yml "
         "and a plugin, installed by the playbook into the agent skill dirs (harness-agnostic, "
         "the way Omarchy does it), whose validity claim is the parser rather than prose. "
         "Carry their caveat too, which is honest and ours would need: treat it as experimental, "
         "different models use it to different effect. Human half is [face-app-builder].")

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

# ── KPro: mine it, do not adopt it (2026-08-19) ────────────────────────────
#
# SAP's Knowledge Provider (BC-SRV-KPR, Basis-era) solved this estate's content
# problem twenty-five years ago: one logical thing, many stores, resolved by
# context at request time. The abstractions are sound and free; the product
# around them — Document Modeling Workbench, document areas, ArchiveLink, ILM,
# the certification programme — is enterprise governance a single-operator
# estate has no use for, and importing it would be rebuild-not-reuse.
#
# Researched 2026-08-19. Source quality is thin and legacy (the 4.6C reference
# PDF is HTTP 410, modern SAP Help pages are JS-rendered); what is cited below
# came from the Content Server HTTP interface PDF and static legacy help pages.

_KPRO = "2026-08-19"

row("kpro", "KPro's three ideas, and nothing else from KPro", _KPRO,
    "queued", "cortex",
    refs="help.sap.com BC-SRV-KPR · SAP Content Server HTTP interface PDF",
    body="Content in nOS is scattered across Nextcloud, Calibre-Web, Kiwix, WordPress, "
         "Outline/BookStack/HedgeDoc and Paperclip with no shared identity, no shared "
         "retrieval and no versioning story across them. KPro's answer was the "
         "INTENSION/EXTENSION split: a logical document (meaning) has N physical "
         "documents (format, language, release), versioned along independent axes, with "
         "LATE BINDING deciding at request time which physical one serves a logical "
         "request. Cortex already holds the relation layer this needs, so the work is a "
         "table, a resolver and an id-scheme fix — not a new subsystem. "
         "EXPLICITLY NOT ADOPTED: the Document Modeling Workbench, document areas, "
         "ArchiveLink, ILM retention, and check-in/check-out locking, which is pointless "
         "on a single-operator estate that already has git. Signed expiring capabilities "
         "(KPro's secKey) are deferred rather than rejected: worth it only once agents "
         "fetch bytes across a network hop, and the cortex organ is loopback-only today.")

row("kpro-ids", "A cortex id that survives a file being moved", _KPRO,
    "next", "cortex", parent="kpro",
    refs="files/anatomy/cortex · KPro docId",
    body="Cortex ids are `fs:<uid>:sha1(relPath)[:16]` — a PHYSICAL id, so moving a file "
         "destroys its identity and forks the corpus silently. KPro's docId is opaque and "
         "stable and the path is an ATTRIBUTE, which is the whole lesson in one sentence. "
         "Cost is near-zero now and rises with every row added to the corpus, which is why "
         "this is the child to do first even though it is the least visible.")

row("kpro-logical", "One logical id, many manifestations", _KPRO,
    "queued", "cortex", parent="kpro",
    refs="files/anatomy/cortex · KEAP relations",
    body="One `logical_id` with N manifestations (`nextcloud:`, `calibre:`, `kiwix:`, "
         "`wp:`), each carrying format, language and source. Roughly one table plus a "
         "resolver in the Cortex organ. WITHOUT IT the same book stays three unrelated "
         "corpus rows for ever and dedupe is not merely unbuilt but impossible.")

row("kpro-get", "get(logical_id, context) -> bytes, across every store", _KPRO,
    "queued", "cortex", parent="kpro",
    refs="docs/idea/03 · KEAP /agent/v1",
    body="The measured gap: KEAP returns metadata and deep links and never content — "
         "docs/idea/03 records it as 'Kiwix and Calibre are deep-linked, never read'. KPro "
         "NAMES this gap (a fixed storage-agnostic verb set over any backend) but does not "
         "close it for you: the expensive part is ZIM and EPUB readers, 1-2 weeks, not the "
         "interface around them. Until it exists the corpus is thin BY INPUT, and further "
         "embedding or extraction work optimises the second bottleneck while the first one "
         "holds.")

row("kpro-table-access", "every DataTable deserves KPro-grade access, not just the roadmap", "2026-09-01",
    "next", "cortex", parent="kpro",
    refs="tools/roadmap-seed.py agent_write · docs/archive/datatables-relations.md",
    body="OPERATOR DIRECTION 2026-08-22: all DataTables should carry MCP-like, KPro-grade "
         "access. Measured the same night, which is what prompted it: the agent door "
         "(/agent/v1/tables/<t>/rows) is an UPSERT KEYED ON `slug`, so it serves the roadmap "
         "and silently INSERTS a duplicate for any table without that column; the human door "
         "answers GET and DELETE and returns 404 to both PATCH and PUT. So a table with no "
         "slug is write-once from every automated door — the ideas table has 55 rows, 12 of "
         "them filed `new` with no research since creation, and nothing but the Planner UI can "
         "ever change them. Verified by probe: one write produced 56 rows and a second copy of "
         "the row it meant to update; the duplicate was deleted and the table restored to 55. "
         "What KPro grade means here is what KPro already means elsewhere — a fixed, "
         "storage-agnostic verb set (list/get/create/update/delete) over a STABLE OPAQUE id, "
         "with the natural key an attribute rather than the address. Until then any agent "
         "maintaining a table either duplicates or destroys createdAt to fake an update.")

# ── The loop's own integrity, and one release policy (2026-08-21 review) ────
#
# Filed after the second Fable pass (docs/idea/19-fable-review-2.md) and a night
# of measurement. Every row below is something a reader OBSERVED, not something
# a plan proposed: the loop's first unattended night, the four merged diffs run
# back through a registry probe, and a full inbox triage. The one idea this
# session did NOT keep — freezing a per-release pin set, "nOS as a distribution"
# — is deliberately absent: four independent critics refuted it (no backports,
# 20 of 54 pending rows are not pins at all, and pin churn ranks fifth among
# what actually delays a tag). What survived it is `sec-severity-floor`.
_REV = "2026-08-25"

row("loop-requires-operator", "requires_operator is stamped and read by nobody", _REV,
    "next", "agents",
    refs="files/anatomy/bone/ledger.py:112 · docs/idea/11-agentic-loop-contract.md §5a",
    body="The ledger marks every gate-add proposal requires_operator=1 and contract §5a says "
         "such a proposal is never auto-accepted. Verified 2026-08-21: only tools/loop-status.py "
         "reads the column, and that is a READER. Neither loop-pr.py nor loop-review.py consults "
         "it, so a gate-add that passes a judge set lands and merges unattended — the "
         "gate-you-can-satisfy-by-editing-the-gate class, through the front door.")

row("loop-pin-bump-gate", "version-pin-bump lands with no operator gate", _REV,
    "next", "security",
    refs="files/anatomy/bone/ledger.py:104-112 · CLAUDE.md kuma 1->2",
    body="OPERATOR_REQUIRED_INTENTS holds only gate-add, so version-pin-bump is auto-acceptable "
         "with NO distinction between a patch and a major crossing. The precedent is already "
         "paid for: Kuma 1->2 moved the pin, gates stayed green, the container was healthy, and "
         "the service ran with zero monitors for ten days because post-start automation was "
         "never reconciled. A freeze policy that limits WHEN pins move without gating WHAT KIND "
         "of move is automatable does not close this.")

row("loop-verdict-vacuity", "a verdict with no oracle overlap must not read as pass", _REV,
    "next", "agents",
    refs="state/judge-sets.yml:296-308 · docs/idea/19-fable-review-2.md §3.1",
    body="Measured: wordpress_version 9.9.9-nonexistent passes the repo set 3868/0. The set is "
         "ansible-lint + genome-codegen + pytest-anatomy; none reads a version value. Three of "
         "four merged diffs were version bumps, so for those three `pass` carried zero "
         "information. THE FIX THIS ROW USED TO NAME IS WITHDRAWN (2026-08-29): it said "
         "\"when no judge has an oracle_paths overlap with the diff, record nothing objected\", "
         "and oracle_paths are exactly what budget_for() FORBIDS to a proposal in that set — "
         "so for any proposal that exists the overlap is empty by construction, and the check "
         "would call every verdict vacuous. Measured + kept runnable in "
         "tests/anatomy/test_oracle_overlap_cannot_measure_vacuity.py. What the finding "
         "actually needs is an oracle that READS THE VALUE, which is loop-pin-resolves-refused "
         "(dropped: a network read is not deterministic). The two rows settle together or "
         "neither does; whoever picks this up owes a decision on that, not a path test.")

row("loop-pin-resolves-refused", "pin-resolves as a gate-set judge — refused, with the count", _REV,
    "dropped", "agents",
    refs="docs/idea/19-fable-review-2.md §6",
    body="The review's own settling test, run 2026-08-21 against the four merged diffs: ARM A "
         "0 objections of 3 (all merged tags resolve). ARM B caught the hallucinated tag but "
         "NOT gitlab-ce:18.11.8-ce.0, which returns HTTP 200 while that diff's own comment says "
         "it was WITHDRAWN upstream — withdrawal is a vendor-advisory fact, not a registry one. "
         "The vulnerable predecessor 7.0.2 also resolves. So the probe catches typos only and is "
         "blind to the REM-178 class. Correctness of a version is not a property of the tree; "
         "the signal belongs wherever fix_version is written.")

row("loop-pulse-runs-poison", "the loop mines itself as a HIGH it may not fix", _REV,
    "next", "agents",
    refs="files/anatomy/bone/weaknesses.py:1324-1396 · tools/red-status.py:137-157",
    body="_source_pulse_runs joins nothing (WHERE exit_code <> 0), so it ignores "
         "findings_exit_codes and two readers of one signal now disagree on the live estate. "
         "Worse than a false positive: loop-base declares [1, 3] where exit 3 is the "
         "committed-evidence deadlock that recurs on the scan's cadence, severity ratchets to "
         "HIGH at streak >= 3, and files/anatomy/bone/** is denied to the loop. Three such "
         "nights and it mines itself. Fix is a subtraction: delegate to red-status.failing_jobs.")

row("loop-queue-retires", "the queue does not learn from a converge", _REV,
    "queued", "security",
    refs="tools/discovery-scan.py · docs/doctrine/loops.md §7.2",
    body="The scanner is the only retirement writer. Proven live 2026-08-21: discovery-scan "
         "reports REM-204 still pending while iiab-wordpress-1 already runs 7.0.4 — the loop "
         "merged that bump and the estate converged it. Twelve rows were already live at their "
         "fix version historically, and REM-178 found a recorded fix BELOW what runs, which "
         "re-opens a gap if anyone acts on it. The reader may only file; closing stays "
         "deliberate.")

row("sec-severity-floor", "severity floor: act on CRITICAL/HIGH, batch the rest to a release", _REV,
    "queued", "security",
    refs="tools/rem-status.py · files/anatomy/docs/notification-fanout.md",
    body="What survived the refuted pin-freeze proposal, and it is arithmetic already on screen: "
         "rem-status prints '+45 pending below HIGH' of 54, i.e. the 83% headline was always just "
         "'stop chasing MEDIUM/LOW between releases'. Mirrors the A9 severity floors. "
         "NON-NEGOTIABLE, because a critic found each one: deferred rows keep status=pending or "
         "they vanish from rem-status's own filter; the reachability verdict becomes a structured "
         "dated field, re-checked per scan cycle, not prose; GHSA-without-CVE is exempt from any "
         "CVE-feed gate (three misses already); 'it is gated' must be falsifiable against a live "
         "probe of the gate, since REM-048 made 13 forward-auth services anonymous when the "
         "outpost 500'd; and an advisory that defeats the control the deferral relies on "
         "auto-escalates.")

row("sec-rem-212-disposition", "REM-212 portainer: CRITICAL with no released fix", _REV,
    "next", "security",
    refs="docs/llm/security/remediation-queue.json REM-212",
    body="The queue names 2.45.0 (STS) or 2.39.7 (LTS); both are reported not to exist. This is "
         "the one live instance of reachable + severe + UNFIXABLE, and it is what generates the "
         "'1 CRITICAL pending' notification that fired three times unread. It needs a recorded "
         "disposition — accept, mitigate or remove the service — not another bump attempt.")

row("sec-gitleaks-noise", "gitleaks burns the HIGH channel on test fixtures", _REV,
    "queued", "security",
    refs="files/anatomy/face/src/lib/anatomy/pulse.test.ts:29",
    body="Inbox row 45 sat unread 15 days as a HIGH. Triaged 2026-08-21: the finding is the "
         "literal string FAKE_hmac_secret_for_tests_only_not_a_real_value_0000000000000000, plus "
         "a prompt in a workflow script and a knowledge taxonomy file. A detector whose "
         "positives cannot be told from its noise trains the operator to ignore the channel, "
         "which is worse than not running it. Needs an allowlist, not a fix.")

row("backup-drill-keap-db", "the restore drill cannot find keap-db, but the backup succeeds", _REV,
    "next", "platform",
    refs="~/.nos/backup-status.json · notifications 134/135",
    body="Standing red for five days and the estate's only proof that a backup is restorable. "
         "The drill says 'keap-db: FAIL - no object at 2026-08-16 (or it decrypted to nothing)' "
         "while wing-db replayed 336701 events. But backup-status.json shows keap-db succeeding "
         "nightly at 347 MB, 14 of 14 sources ok. So this is a lookup, key-format or retention "
         "mismatch in the DRILL, not a backup that is not running — and it must be diagnosed "
         "before the distinction stops being academic. "
         "RESOLVED 2026-08-30, and the guess above was wrong in the reassuring direction: the "
         "drill was right and the BACKUP was bad. Reading backup.log over 29 nights, two of "
         "them (08-13, 08-30) carry no `pages=` completion line from the in-container node "
         "backup and uploaded 296 MB and 310 MB against a steady 347 — truncated snapshots, "
         "shipped and logged `keap-db: OK`. The producer branched on `test -s` because the "
         "backup pipeline ends in a `while` and node's exit code belonged to the loop, so it "
         "substituted the claim it could see for the verdict it could not. A reader now opens "
         "the snapshot in-container before upload and counts the same three tables the drill "
         "counts. See docs/hidden_fees/38.")

row("notify-body-is-prompt", "a notification whose body is its own prompt", _REV,
    "queued", "platform",
    refs="notifications 144/147/151 (os-resume)",
    body="'S2 diff: 14-night ceiling reached' fired three consecutive nights; the body reads "
         "'Report whatever the harness has, with its denominator.' That is the instruction, not "
         "the result. Same family as a success marker written by the attempting code: the "
         "channel carried something, so nothing looked broken.")

# ── Agentic planes — the RSI-research programme, answered 2026-08-28 ────────
#
# Sixteen operator answers (docs/plans/rsi-research/03-questionnaire.md) closed
# the research; the workflow encodes them and REFUSES a questionnaire whose
# answers drift. One row per build phase; Answers/Review are workflow control
# steps, not estate work, and get no row.
_PLANES = "2026-08-28"

row("planes", "Two planes — sere finishing + nos-ops groundwork", _PLANES,
    "queued", "agents",
    refs="docs/plans/rsi-research/ · 04-implementation-workflow.js",
    body="Sixteen answers in, three overruling the recommendation (Q8 no agent memory ever, "
         "Q5 embryos deferred, Q12 mutex widens now). Truth before capability: identity, "
         "oracle-written satisfaction, the output contract and the ledger join land before "
         "any plane work; the ops harness MEASURES the 1B-vs-3-7B boundary rather than "
         "building the plane. Deliverable is commits on a feat/ branch; the operator "
         "converges.")

row("planes-prune", "Agent memory deleted entirely, with a gate against return", _PLANES,
    "queued", "agents", parent="planes",
    refs="Q8 · tests/anatomy/test_agent_memory_does_not_return.py (to ship)",
    body="Q8=c: KEAP is the estate's memory; a second memory beside the cortex is a second "
         "truth. Dreamer, MemoryStore, dream-agent, the agent_memory_stores TABLE and "
         "test_agentkit_dreams.py all go in one commit, and a new gate fails if any of them "
         "reappear. Coordinator/ProcessPool (~800 unreachable lines) go with them.")

row("planes-mutex", "One lock, three slots: AgentKit N=3, claude-CLI exclusive", _PLANES,
    "queued", "agents", parent="planes",
    refs="Q12 · files/anatomy/scripts/agent-run-lock.sh",
    body="Operator overruled the wait: AgentKit runs are PHP in-process, a different failure "
         "mode from the 2026-05-27 CLI crashes, and may run three abreast. A CLI spawn takes "
         "ALL THREE slots — still meets nobody. Per-slot stale reclaim kept; a second lock "
         "for the CLI path is explicitly forbidden. N=3 defended on evidence: wing.db is "
         "WAL (read live 2026-08-28) and Wing web + Pulse already write it concurrently; "
         "the real fix is a busy_timeout where AgentKit opens the DB, so writers queue "
         "instead of erroring. Gate executes the script, not its text.")

row("planes-grant", "mcp-wing split + per-agent principals, grants from measured use", _PLANES,
    "queued", "agents", parent="planes",
    refs="Q14 · arch items 1-2 · McpWingTool.php",
    body="Read/write tool split with per-route allowlists; api_tokens gains enforced scopes. "
         "Q14=b as amended: write routes grandfathered from the FULL agent_tool_use history "
         "— no hardcoded window — with the query output COMMITTED and stating the span it "
         "covered, so every grant is traceable to a measurement whose extent is visible. A "
         "route nobody called is not granted, and that absence is a finding.")

row("planes-oracle", "Oracle-written satisfaction + the three-stage output contract", _PLANES,
    "queued", "agents", parent="planes",
    refs="Q9 Q10 · arch items 3-4 · Runner.php",
    body="satisfied requires a gate_run_id, constraint in the SCHEMA. Q10=b: no grader to "
         "start — oracle raw output is the revision signal; the same-model fallback is "
         "deleted. Q9: hardcoded shape parser, then ONE format-only re-ask, else UNPARSEABLE "
         "— and any repair sets output_repaired, because silent repair is a success marker "
         "written by the thing that failed. Best iteration reported, not last.")

row("planes-ledger", "Proposer onto AgentKit; every proposal names a session", _PLANES,
    "queued", "agents", parent="planes",
    refs="Q13 · arch item 5 · tools/loop-propose.py",
    body="The bypassPermissions claude --print spawn is replaced by a session with ceilings, "
         "scope gate and lineage; loop_proposals gains session_uuid. Q13=a: existing "
         "ceilings. Also cuts the Q6 seam: 'harness' joins INTENT_CLASSES as "
         "declared-but-disabled, refused by name. Until this lands, 'AgentKit-driven "
         "nos-loop' is two systems sharing a string.")

row("planes-surface", "Agent nodes, /questions, and the loop editor with its off toggle", _PLANES,
    "queued", "agents", parent="planes",
    refs="Q6 Q7 Q15 · 02-visualisation.md",
    body="agent:<name> becomes the 14th node kind; /questions is Wing UI only with expiry = "
         "refuse (an approval channel is an authentication surface). Q6: the loop editor "
         "renders every harness read-only plus every intent class incl. the disabled "
         "harness kind; harness_proposals_enabled is a KEAP DataTable row with a committed "
         "default-OFF fixture, its table path denylisted — you cannot consent to what you "
         "cannot see, and a permission a system can grant itself is not a permission.")

row("planes-ops-harness", "The nos-ops measurement harness — where is the tier boundary", _PLANES,
    "queued", "agents", parent="planes",
    refs="Q3 Q4 · state/llm-backends.yml",
    body="Q3=a: the plane's go/no-go is a measurement. mode: one_shot plus a harness over a "
         "model-size RANGE — the question is not 'is 1B enough' but where the boundary sits "
         "between the ~1B chain tier and the ~3-7B tool-use tier fine-tuned on nos-lang:1B "
         "output. Code oracle scores labels; the model never self-assesses. No tenant DBs, "
         "no embryos this cycle (Q11, Q5).")

row("planes-harness-kind", "The guarded 'harness' proposal kind — after the surface", _PLANES,
    "queued", "agents", parent="planes",
    refs="Q6 · 01-architecture.md deferred",
    body="NOT built this cycle, but its seams ARE: 'harness' enters the closed "
         "INTENT_CLASSES enum as declared-but-disabled (refusal names the toggle), the "
         "KEAP toggle row exists default OFF, and the editor already renders the disabled "
         "kind. The later cycle's one change is wiring the ledger's refusal to READ the "
         "live toggle. Judge B's edit-the-gate objection stands until the operator throws "
         "the switch. Unblocks on planes-surface shipping and the operator having seen it.")

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

# ── Three rows that existed only in the live table (authored 2026-08-30) ────
#
# 13 of 148 rows had NO git author: nothing in tools/ writes them, so they
# could not be probed (test_a_probe_cannot_match_its_own_description.py
# refuses a probe for a slug nobody authors) and would not survive a rebuild.
# These three are the ones expressible with the current `row()` signature.
#
# THE REMAINING TEN STAY UNAUTHORED, and the reason is structural rather than
# lazy: rel-011 and the seven `w-*` ladder rows carry an `ordinal`, which
# `row()` has no parameter for. Authoring them without it would silently drop
# the ladder order — the one field they exist to carry. That needs a signature
# change and a look at what else reads `ordinal`, which is its own piece of
# work, not a footnote to this one.
#
# BODIES ARE VERBATIM FROM THE LIVE TABLE. git owns title/parent/track/refs/
# body, so `--sync` would OVERWRITE the live text with whatever stands here —
# a summarised body would have destroyed the measurement each row was written
# to preserve. They are copied, not paraphrased.

row("spine-tools-vs-cli-refusal", "Bound loop runs and MiniMax serves it; the bound agent cannot FILE its report (McpWingTool sends no HMAC — 401 on /api/v1/events)",
    "2026-08-30", "shipped", "agents",
    parent="w-agentkit-spine", refs="",
    body="MEASURED 2026-08-15 BY EXECUTION, preparing the supervised parallel night for librarian:brief-taxonomy.\n\nAll NINE agent definitions declare tools (2-4 each). Runner builds schemas from them unconditionally (Runner.php:401) and passes them to the client. ClaudeCliAdapter REFUSES a non-empty tool schema with LLMCapabilityError -- deliberately: `claude --print` runs its own tool loop, and a dropped schema would let an agent believe it had tools nobody offered. Runner rethrows a capability error without fallback, also deliberately.\n\nEach decision is right alone; together they make the spine unreachable. NO agent runs through AgentKit today, so the parallel night is blocked for every ceremony, not just librarian. Probe against the repo tree:\n  new ClaudeCliAdapter('claude-sonnet','sonnet')->send('sys',[msg],[schema])\n  -> REFUSED: 'the claude CLI backend cannot be handed a tool schema'\n\nThe refusal names both exits: a backend that speaks the tool protocol (an Anthropic API adapter, needing a key this estate does not set), or a ceremony written so the CLI calls the surfaces itself -- which is exactly what pulse-run-agent.sh does today. The second implies deciding whether agent.yml `tools:` is a SCHEMA to pass or a REQUIREMENT to check; adding acceptsToolSchemas() would widen the two-method protocol that test_agentkit_naming.py pins.\n\nSeparately: deployed ~/wing/app/app/AgentKit has neither serveFallback nor BindingResolver -- repo-only until Wing converges. The night needs that converge too, but it would not have helped; this blocker is upstream of it.")

row("gdpr-agent-processors", "Agent ceremonies declare their processor and their EU exit",
    "2026-08-12", "shipped", "security",
    parent="rel-011", refs="",
    body="MEASURED 2026-08-12, and it is false TODAY — independent of MiniMax. state/dpa-register.md:25-30 asserts 'Transfers outside the EU: 0' and 'None. Every processing activity is fully EU-resident and self-hosted with no third-party processor.' All Art-30 records declare processors: []; git log -S shows none was ever added. Meanwhile the nightly ceremonies have shipped prompts and tool results to Anthropic since they began, and pulse-base/plugin.yml — the plugin whose jobs fork the agent runner — affirmatively asserts processors: [], eu_residency: true, 'no tenant end-user data is processed'. WHY IT WAS INVISIBLE: nos_gdpr.all_records() reads plugins/ and apps/ only; no file under files/anatomy/agents/ carries a gdpr: key, and the design promising auto-included processors: [anthropic] rows per agent profile (docs/bones-and-wings-refactor.md:850-854) was never built. test_gdpr_register_coverage.py checks parity and completeness, never VALUES — so a register can be complete and wrong. SCOPE: author the agent-runtime Art-30 activity (Anthropic now, MiniMax pre-drafted), correct pulse-base's assertion, regenerate via tools/gdpr-dpa-register.py. The repo has zero occurrences of SCC, adequacy, third country or Chapter V, so the transfer-mechanism vocabulary does not exist yet. NOT ONLY A MINIMAX PREREQUISITE: docs/idea/15-business-fixture.md:60-71 makes the register entry the gate before the fixture may hold real people. One afternoon serves both.")

row("wing-events-chain-aware-retention", "Chain-aware retention for the wing.db events table",
    "2026-08-12", "queued", "platform",
    parent="", refs="callback_plugins/wing_telemetry.py; files/anatomy/wing/app/Model/AuditChain.php; tests/callback/test_task_noise_gate.py",
    body="Measured 2026-08-12: events held 332,506 rows / 698 MB; task_start+task_skipped were 86% (~108k rows per converge day). The TAP is now gated (task noise off by default, NOS_TELEMETRY_TASK_VERBOSE=1 restores), but the accumulated table remains: every row is WORM-triggered and HMAC-chained, so pruning is a design problem, not a DELETE — it needs an anchor-and-reseal step (the shape the key-rotation machinery already performs) that seals a segment, archives it verifiably, and re-anchors the chain. Until designed, wing.db only grows and nightly chain verification walks every historical skip row.")

# ── Wing's tenants, ranked by what it would cost to evict them (2026-08-31) ──
row("wing-tenants", "Wing hosts systems that are not Wing, and one is cheap to move",
    "2026-08-31", "next", "platform",
    refs="files/anatomy/wing/app/Cortex · files/anatomy/cortex/server/cortex-lang.ts · tools/cortex-status.py",
    body="OPERATOR, 2026-08-31: 'Wing mixes too many systems, spread it into the existing ones.' "
         "MEASURED rather than argued. Wing is ~27k lines of PHP across 25 API presenters "
         "(agents, cortex, gdpr, gitleaks, pentest, pulse, remediation, scan, migrations, "
         "upgrades, coexistence, patches, inbox, notifications, hub). Size is the wrong "
         "ranking; coupling is the right one, and it separates the two big tenants cleanly. "
         "AgentKit is 8073 lines and imports SIX Model repositories — sessions, events, "
         "vaults, subscriptions, questions, audit — every one of them a wing.db table. It is "
         "genuinely Wing-resident and moving it means moving its state, which is a different "
         "and larger question. Cortex is 1714 lines and imports exactly ONE: KeapCortexClient, "
         "an HTTP client to KEAP. That is the whole tie. THE SPLIT IT WOULD CLOSE: cortex-lang "
         "is one language implemented in two runtimes — the pure half (tokenise, parse, "
         "analyse) is TypeScript in files/anatomy/cortex/server/cortex-lang.ts serving "
         "/agent/v1/validate, and the execution half is PHP in files/anatomy/wing/app/Cortex/, "
         "seven opcode handlers. They are bound by a shared opcode registry hash "
         "(cx1:… on both sides, checked by tools/cortex-status.py since today) so the seam is "
         "sound — but it is still a language boundary through the middle of one organ, and it "
         "is why 'how is the cortex' could only ever be answered about KEAP. THE COST IS "
         "HONEST: moving execution to the organ is a PHP->TS rewrite of 1714 lines, not a file "
         "move, and the handlers are where the KEAP round-trips live. What makes it worth "
         "pricing anyway is the operator's framing — the cortex organ belongs in nOS whole, "
         "with KEAP as UI plus general knowledge — and the fact that the executor's only Wing "
         "dependency is a client to the very service the organ already speaks to.")

row("cortex-vendor-staleness", "Four cortex drifts that are staleness, not divergence",
    "2026-08-31", "next", "cortex",
    refs="tools/cortex-drift.py · files/anatomy/cortex/server/{migrations,db,cortex-lang}.ts · shared/contracts/field-concepts.ts",
    body="Read one at a time 2026-08-31, and the UNDECLARED bucket held three different "
         "things. TWO WERE OURS AND ARE NOW DECLARED: fs-roots.ts rewrites an overlap guard "
         "KEAP keys on KEAP_USER_FILES_DIR — KEAP's compose sets it so the guard runs there, "
         "the organ's plist never does, so on this deployment the `if` never ran and a "
         "mapped-folder root over the per-user tree would have mirrored every user's documents "
         "with the MAPPING's visibility; cortex-opcodes.ts adds `openai` to MODEL_URI_RE "
         "because two nOS agents bind openai-local-haiku and KEAP's regex rejects that URI. "
         "THE OTHER FOUR ARE STALENESS AND DECLARING THEM WOULD BE A LIE, in both directions. "
         "KEAP is behind on two: server/cortex-lang.ts and server/db.ts cite "
         "docs/plans/{nos-cortex-lang,keap-curator-agent,keap-semantic-lens}.md, and all three "
         "live in nOS docs/archive/ — the paths exist in neither repo, so KEAP's citations "
         "point nowhere and the organ simply followed the move. That is an upstream one-liner, "
         "not a divergence. THE ORGAN is behind on two, and they are the same feature: "
         "shared/contracts/field-concepts.ts lacks `rowRef` in the graph.* kinds and "
         "server/migrations.ts lacks migration 007-row-refs (the table_row_refs back-reference "
         "mirror). That is w-keap-relations, which shipped on the KEAP side. CHECKED BEFORE "
         "ALARM: the organ has NO code referencing table_row_refs either, so it is internally "
         "consistent — one feature behind, not broken, and its store carries data_tables / "
         "table_rows / table_row_history without the mirror. Re-vendor when the organ needs "
         "rowRef; doing it now drags in tables.ts and its writer for a feature nothing here "
         "calls. WHAT THE TOOL STILL CANNOT SAY: `undeclared` conflates 'we diverged on "
         "purpose' with 'one side is behind', and a third state would have made this reading "
         "unnecessary. Worth adding the day a fifth file joins the bucket, not before.")

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

# ── The half git owns, and the half the table owns (--sync, 2026-08-08) ──────
#
# "Additive on rows" had a consequence nobody had named: this file is the SOURCE
# OF TRUTH for a row's TITLE, PARENT, TRACK, REFS and BODY — they are authored
# here and nowhere else — and an existing slug was skipped entirely. So editing
# a body in git, committing it, and re-running changed nothing in the table. The
# text went green in review and never reached a reader. Same shape as everything
# else this week: two representations, nothing comparing them.
#
# The fix is not to make the seeder write everything. The columns split cleanly
# by who can know them:
#
#     git owns   slug title parent track refs body   — authored, reviewable
#     table owns status target occurred_at verified* — moved by the operator,
#                                                      by tools/roadmap-update.py
#                                                      and roadmap-verify.py
#
# `--sync` reconciles the git-owned half for rows that already exist and does
# not touch the other half. Without it this stays purely additive, because
# rewriting 68 rows should be something you asked for.
SYNC = "--sync" in sys.argv
GIT_OWNED = ("title", "parent", "track", "refs", "body")

live_rows = {r["values"].get("slug"): r for r in req("GET", BASE + "/rows?limit=500")["data"]["rows"]}
existing = set(live_rows)
fresh = [r for r in R if r["slug"] not in existing]
skipped = len(R) - len(fresh)

drifted = []
if SYNC:
    for r in R:
        cur = live_rows.get(r["slug"])
        if cur is None:
            continue
        delta = {k: r[k] for k in GIT_OWNED
                 if k in r and r[k] != (cur["values"].get(k) or "")}
        if delta:
            drifted.append((r, delta, cur["id"]))

print(f"already present: {skipped} · to insert: {len(fresh)}"
      + (f" · git-owned drift on {len(drifted)}" if SYNC else ""))

if DRY_RUN:
    for r in fresh:
        print(f"  [dry] would insert {r['slug']:<24} {r['title'][:60]}")
    for r, delta, _ in drifted:
        print(f"  [dry] would sync   {r['slug']:<24} {', '.join(sorted(delta))}")
    print(f"DRY RUN — nothing was written. {len(fresh)} insert(s), "
          f"{len(drifted)} sync(s).")
    sys.exit(0)

# BOTH WRITES GO THROUGH THE AGENT DOOR, AND THE DOOR IS NOT A DETAIL.
#
# A KEAP row has two names: the id it is addressed by, and what its `slug` cell
# says. The human API mints a UUID; the agent API uses the slug — and the agent
# API's upsert, the only update path that exists at all, keys on the ID. So a
# row inserted through the human door can never be changed afterwards: an
# "update" matches nothing and inserts a duplicate beside it.
#
# That is not hypothetical. Every roadmap row was created that way and not one
# had ever been updated since it was filed; `tools/keap-reid-rows.py` exists to
# repair it. This file caused three more the first time --sync ran, because the
# insert path had been left on the old door while the sync path used the new
# one — the fix applied to the symptom and not to the source.
_agent_tok = None


def _agent_token():
    global _agent_tok
    if _agent_tok is None:
        import os
        _agent_tok = os.environ.get("KEAP_AGENT_TOKEN_RW", "").strip() or subprocess.run(
            ["docker", "exec", "iiab-keap-1", "printenv", "KEAP_AGENT_TOKEN_RW"],
            capture_output=True, text=True).stdout.strip()
        if not _agent_tok:
            sys.exit("REFUSING: no KEAP_AGENT_TOKEN_RW. The human API has no row "
                     "update at all, and its inserts mint ids no later write can "
                     "reach — so neither half of this run may use it.")
    return _agent_tok


AGENT = f"http://127.0.0.1:8091/agent/v1/tables/{TABLE}/rows"


def agent_write(values):
    rq = urllib.request.Request(
        AGENT, data=json.dumps(values).encode(), method="POST",
        headers={"authorization": f"Bearer {_agent_token()}",
                 "content-type": "application/json"})
    with urllib.request.urlopen(rq) as resp:
        return json.loads(resp.read())


for r in fresh:
    agent_write(r)

if drifted:
    unkeyed = [r["slug"] for r, _, rid in drifted if rid != r["slug"]]
    if unkeyed:
        sys.exit("REFUSING: these rows are not addressed by their slug, so a "
                 f"sync would duplicate them: {', '.join(unkeyed)}\n"
                 "  run `tools/keap-reid-rows.py --apply` first.")
    for r, delta, _ in drifted:
        agent_write({"slug": r["slug"], "title": r["title"],
                     "status": live_rows[r["slug"]]["values"].get("status"), **delta})
        print(f"  synced {r['slug']:<24} {', '.join(sorted(delta))}")

after = req("GET", BASE + "/rows?limit=500")["data"]["rows"]
tops = [x for x in after if not x["values"].get("parent")]
print(f"seeded: {len(after)} rows | top-level {len(tops)} | nested {len(after)-len(tops)}")
