# nOS — Release notes

`nOS` is the open-source Ansible engine behind [**This is AIT — Agentic IT**](https://thisisait.eu): one command turns an Apple Silicon Mac into a reproducible, self-hosted, self-managing cloud of ~50 FOSS services behind one SSO.

Versioning is by git tag `v<semver>` cut from `master`. The prior tag was `v0.10-beta`.

---

## v0.11-beta (unreleased — drafted 2026-08-19)

> **The estate closes a loop it cannot cheat.** ~500 commits since `v0.10-beta`,
> and the through-line is a machine built so that no step in it can record its
> own success: a weakness was detected by a scanner, proposed against by an
> agent, judged by gates the proposer cannot touch, landed by a driver that
> holds no propose scope, merged by a reviewer that asks three questions and
> refuses on any non-answer — and whether the patch reached the tree is git's
> answer, read back by a tool that cannot be told what to think. On 2026-08-19
> that chain ran end to end for the first time, twice.

### The agentic loop — from contract to two merged commits

- **The engine** (`files/anatomy/bone/`): weakness reader over seven sources,
  proposal ledger with WORM triggers and a hash chain, five judges with
  `min_work` ratchets, three-valued verdicts (INDETERMINATE is an outcome, not
  a maybe), a budget that reads the diff in both directions, and a §4 attempt
  ceiling whose lift key is derived, never supplied. Verdicts replay:
  `nos-loop verdict --replay` re-runs the recorded argv against the recorded
  tree.
- **Four identities, no overlap.** Proposer proposes and stops; the judge
  runner is the only actor the schema lets seal a verdict; the driver
  (`tools/loop-pr.py`) re-judges decayed verdicts, pushes, opens the MR and
  stops; the reviewer (`tools/loop-review.py`) merges only when CI passed on
  THIS sha, the judges passed THIS proposal, and the MR diff IS the judged
  diff — byte-compared. Nothing in the chain writes its own outcome anywhere.
- **§11 proof, delivered live 2026-08-19:** `rem:REM-204`
  (wordpress `7.0.2 → 7.0.4`, merge `64bc8b1b`, pipeline #7) and `rem:REM-159`
  (gitlab → `18.11.9-ce.0`, merge `713b015c`, pipeline #9) merged to `dev`
  behind green Woodpecker pipelines on the local agent forge.
  `tools/loop-status.py --awaiting` reads both as `landed` — from
  `git apply --check -R`, not from any participant's claim.
- **The contract corrected itself where it was unsatisfiable.** §11 had adopted
  "the weakness leaves the list", which `budget.py`'s `docs/**` wall forbids the
  loop from ever satisfying; the criterion is now the reachable one (judged
  diff merged behind green CI) and the wall stays shut. The ledger gained
  `passed-awaiting-act` so a solved weakness stops burning attempts, and the
  readers segregate the nine 2026-08-02 build-time fixture rows that headed
  every surface answering "is the loop working" — kept in the ledger, out of
  the tallies.
- **What the first live runs cost, and taught:** a re-run wedged on its own
  branch name (now: refresh-in-place with `--force-with-lease` pinned to a tip
  the driver PROVES it made), a leftover local ref (now: detached commits, no
  local ref ever), GitLab 404-ing a raw branch slash where Gitea 400s the
  encoded one (now: spelled per forge, gated), and a Gitea repo with zero
  webhooks certifying pushes into a void (now: hook count is measured and
  said).

### Agents get a runtime they can be held to

- **Bound ceremonies complete.** A14 sessions carry budget ceilings checked
  before the spend, a terminated run reports the tokens it burned, a fallback
  answer no longer wears the primary's name, and the grader reads a real page.
- **A backend is a binding, not a provider.** One OpenAI-protocol adapter; the
  MiniMax path built to the switch and no further; `mistral-eu` recorded as the
  first EU-residency row, inert; the Pulse catalog carries no backend, ever.
- **Agents entered the GDPR Article-30 register**, their cost is recorded per
  run and read by a daily tally, and `ask_operator` suspends a run until a
  human answers — on a phone, via ntfy, with approvals and questions unified
  into `/inbox`.

### The estate answers questions instead of being derived

- `tools/red-status.py` (what is red RIGHT NOW, across every source — built
  after two nightly jobs failed silently for two days), `tools/estate-status.py`
  (host vs repo vs origin), `tools/loop-status.py`, `tools/nos-cc.sh` — a tmux
  control centre whose one rule is that a pane shows STATE re-read by a reader,
  never scrollback that looks identical after its writer dies.
- The doctrine caught up: citations in code resolve to their documents or CI
  goes red; the anatomy graph carries the law's edges; `tier` means RBAC and
  nothing else (`docs/doctrine/layers.md`).

### Security

- **Secret blast radius P0/P2/P4:** the backup archive key no longer derives
  from the global prefix; minted-but-never-persisted secrets found and fixed;
  the audit-chain key can rotate over a key ring, sealed before minting.
- **The audit chain earned its red twice, and both were real findings:** the
  nightly verify caught 37 unsigned rows (a bare `php bin/run-agent.php`
  carrying none of the daemon's env — writers now REFUSE an unsigned append to
  a chained database) and one "content tampered" row that was actually a writer
  signing PHP `false` where SQLite stores `"0"` — writers now type-stabilize
  before hashing, the verifier retries exactly the two historical variants
  (strict round-trip), and the reviewed gap is acknowledged by an operator act
  that verifies the window is a clean chain-off before recording the anchor.
  Live at draft time: `ok:true, checked=347637, unsigned=37, type_coerced=1`.
- **Queue at draft, cycle-33: 204 rows — 144 resolved, 50 pending (6 HIGH /
  25 MEDIUM / 19 LOW), 5 vendor-blocked, 4 wontfix, 1 obsolete.** Two of the
  six HIGHs are the loop's own merges awaiting converge + rescan (REM-204,
  REM-159). Ask `tools/rem-status.py`; do not copy these numbers forward.

### Why this is a beta, stated before anyone asks

The operator asked whether this tag could drop the suffix. It cannot, on
evidence, and the notes owe the list:

1. **The audit-chain fix is committed, not deployed.** The repo is not the
   running system: the nightly verify runs the estate's copy of
   `verify-audit-chain.php`, which predates the type-retry — it will keep
   exiting 2 at row 339176 until a `--tags wing` converge ships it. A non-beta
   cannot be cut while the tamper-evidence control reports broken on the box.
2. **The restore drill's last SCHEDULED run failed** (2026-08-16: that night's
   `keap-db.gz` was missing from the set — the drill doing exactly its job).
   A manual drill against the 2026-08-19 set passes (`keap-db OK`,
   `wing-db OK, events=343860`), but a backup discipline is a cadence, not a
   good day; the proof is next Sunday's run, green, unattended.
3. **69 unread CRITICAL/HIGH notifications, oldest 25 days.** Non-beta claims
   an operating discipline; an attention queue this deep says the estate
   produces more signal than its one operator consumes.
4. **50 pending remediation rows, 6 HIGH**, plus 5 vendor-blocked CRITICALs
   (FreePBX image abandoned upstream) that operators must accept explicitly.
5. **The Linux wet-test still does not prove the estate comes up**
   (`docs/hidden_fees/08` OPEN; the stack layer is unproven on the runner), and
   FreeScout's `native_oidc` remains aspirational.
6. **Every release to date has bypassed the master signature rule** rather than
   satisfied it (`Found N violations`, admin bypass). A gate that only ever
   reports its own defeat is not a gate a non-beta should ship over.

What would earn the suffix's removal is mostly operational, not code: a green
week of nightly verifies and one green scheduled drill after a converge, the
inbox worked down, the HIGHs dispatched or ruled, and the signature rule either
met or removed.

---

## v0.10-beta (2026-08-02)

> **The estate stops believing its own success reports.** 179 commits since
> `v0.9-beta`, and the through-line is one sentence that turned out to describe
> a whole family of defects: *a step recorded its own outcome as the fact of
> having attempted, and the record was written by the attempting code.* Four
> arcs — the cortex agreement harness reaching parity, the genome's first layer,
> two adversarial audits of the layers nobody had read, and the beginning of one
> filesystem — all converge on it.

### The cortex corpus agrees with itself, measurably

- **Verdict `AGREE`, all six clauses, `agreeStreak: 6`** — read from the ledger
  on release morning, not from the gate night. KEAP and the vendored organ each
  carry **2 500** taxonomy nodes with zero on either side alone;
  `knowledge_objects[fs:]` **317/317**, `relations` **1 438/1 438**.
- **The harness stopped inventing divergence it could not see.** The denominator
  was seeded, the capture queue made enumerable, the vendored knowledge tree
  caught lagging the pin by ten nodes, and the organ's corpus reader identified
  as a port rather than a stray.
- Asymmetries are now *named* rather than counted as drift: the estate's own
  1 088 doc nodes (`organ-docs-corpus`), the 97 nodes outside the referee's
  jurisdiction, and the KEAP-only table cards.

### The genome — L1, and the write path it needed

- **`state/genome/entity.schema.json`** — a base entity with `identity` /
  `compliance` / `access` / `cortex` / `face` facets, composed by `$ref` +
  `allOf`. The first cross-file `$ref` in the estate; `tools/genome-codegen.py`
  emits the Python and TypeScript mirrors and `--check` fails CI on drift.
- **The `access` facet reconciled five separate declarations** of "how is this
  service reached and what gates it" — the split that produced REM-144.
- **L1 field concepts: every column says what it MEANS.** A closed, git-owned
  vocabulary with a membership gate; all **76** columns across the five table
  definitions carry a `concept:`. Mapping the live columns forced two vocabulary
  splits the one-concept-per-table rule refused to absorb (`net.url` vs
  `net.repo`, `graph.uses` vs `graph.stores`).
- **The write path `data_tables.schema_json` never had.** Until this change a
  table's columns were immutable for its lifetime, so a changed definition was a
  silent **no-op on every converged install**.
- **How far into the database they actually reach — 32 of 76, not 76.** The
  seeder (`roles/pazny.keap/tasks/seed-face-tables.yml`) enumerates exactly
  three slugs — `face-layouts`, `face-wallpapers`, `face-controls` — so the 44
  columns belonging to `apps` (23) and `systems` (21) are annotated in git and
  belong to tables that **do not exist on a converged host**. The repo's own
  gate says so in `tests/anatomy/test_keap_table_concepts.py`; an earlier draft
  of these notes did not, which is a fair sample of the defect this release is
  named after. `keap_nos_full_catalog` — the flag that reads as if it seeds
  the rest — is declared and set by `profiles/all-on.yml` but **read by nothing**.
- **Honest scope:** the concept token in a row body buys the *lexical* retrieval
  leg. It does not make embeddings concept-aware — one vector, truncated body.
  That is L2's job and is not claimed here.

### face and explore — four ways to read a table, and a core you can navigate

- **Per-table render style.** A DataTable now declares how it wants to be read —
  `grid`, `blog`, `timeline` or `tiles` — persisted in the card's frontmatter
  beside the existing `graph` block, with a prose editor for the body column.
  Declaring a style the data cannot support **degrades and says so** rather than
  rendering an empty frame.
- **`/explore` core mode clusters by type**, with θ frozen by hash so a node
  keeps its position between sessions — spatial memory was the point of the view,
  and rehashing on every load destroyed it.
- **LOD opens much earlier** (apparent-size thresholds cut ~2.5×) and labels
  appear on hover rather than only at point-blank range. The reported "skills
  appear twice, red and green" was chased to ground and **disproven at three
  levels** — object identity, graph payload ids, and the placement branches,
  which are mutually exclusive. What looked like duplication was two cluster
  envelopes drawn over one set of nodes.
- Shipped as KEAP **v1.37.0** (the schema write path) and **v1.38.0**.

### Backup is an organelle, and the drill proves it

- The nightly set reaches **the brain**: `keap.db` is copied container-side with
  the page-level `backup()` API (`VACUUM INTO` cannot rebuild a libSQL vector
  index, and failed silently when it tried), sidestepping the launchd context's
  missing disk access for `/Volumes`.
- **`backup-verify.sh`** — a weekly restore drill that fetches, decrypts and
  opens the newest objects, registered as a Pulse job by the new `backup-base`
  plugin. `"Restore drill checked NOTHING"` is a HIGH, not a silence.
- **Absent is a failure, not a skip.** An enabled source whose data was missing
  used to record nothing at all, so the nightly notification said *"Backup OK — N
  sources"* with `wing.db`, the gitea repos and the tofu state quietly outside
  the set.

### REM-144 — the dashboard was on the edge

- Traefik's API answered unauthenticated at the edge, and `/api/http/middlewares`
  served both SEC-6 edge tokens verbatim. One of them was
  `{prefix}_pw_face_edge`, so the disclosure was **the global password prefix**,
  from which every credential in the estate derives.
- Fixed by routing (`traefik_skip_ids`), by minting `face_edge_token` off the
  prefix and persisting it, and by a gate that makes an ungated route carry a
  **justification field** rather than a comment nothing compares. REM-145 rode
  along as v3.6.24. Public exposure was proven, and the access log showed zero
  unexplained requests across the six days it covers.

### Two audits of the layers nobody had read

26 agents across two adversarial sweeps; 27 findings survived refutation and ~20
were killed on review — most of them because the service is off by default.

- **Delivery**: `mark_dispatched()` stamped `dispatched_at` on *failure* too, and
  the pending query selects on that column — so one unreachable moment for ntfy
  or SMTP lost the message permanently and left the row indistinguishable from a
  delivered one. GDPR breach alerts included. Now: attempt counters, stamp on
  success or budget.
- **The scan that never ran** stamped `status=scanned` with fresh timestamps —
  and that fabricated freshness is exactly what the drift watcher reads for
  staleness, so the alarm built to make scan rot loud was fed the value that
  silenced it.
- **A daemon older than its own code**: pulse ran 07-27 code through four
  converges because `pip --quiet` prints nothing and `changed_when` keyed on
  stdout. The role now *observes the effect* — comparing the running process
  against the code on disk — which also repairs drift that already happened.
- **The wiring layer**: 175 `failed_when: false` against 2 asserts. Gitea's
  SSO-lockout guard, one of those two, tested `.status` on a `command` result and
  could never fire. Jellyfin sealed a one-shot setup wizard over an admin POST
  that admits 400 and 500. FreeScout read its own probe failure as "no admin
  exists". All three fixed, plus a gate over the four statically-decidable shapes.

### Then the converge audited the audit

Three defects surfaced only by running the fixed playbook against a live estate,
and all three are the same shape one level up — **a check that had never once
executed the branch it claimed to cover.**

- **The FreeScout ownerless-gate fired against a FreeScout that had its admin all
  along.** The probe behind it had never worked: wrong working directory, *and*
  an `--execute` flag that tinker does not have. It had been returning empty
  stdout, which the old logic read as the string `0` — "no admin exists". The
  gate was right to be loud and wrong about what it was reading; it now keys on
  a printed marker and cannot confuse *"no admin"* with *"the probe failed"*.
- **Metabase had never run its setup task against a configured Metabase.**
  `setup-token` comes back as JSON `null` once setup completes, and one-arg
  `default('')` substitutes only *undefined* — so the None reached `| length`
  and aborted the whole run. Two more instances of the same filter mistake were
  found and fixed with it.
- The gate written for that last one **caught its own unsoundness**: the real
  defect spans two lines — the `default()` in a `set_fact`, the `| length` in a
  later `when:` over a renamed fact — so a single-expression scanner would have
  shipped green against the very bug it was written for. It now follows the
  laundered fact through the file.

### The red we are shipping with — `Integration (ubuntu-24.04)`

**This job is red at the tag, and it should be.** It is the standing Linux
acceptance gate, it runs only on non-draft PRs, and it had not executed since
`pazny.cortex` was Ansible-ized *during this cycle*. On the release PR it ran
four times and walked forward one real defect per run:

| run | reached | stopped on |
|---|---|---|
| 1 | `ok=226` | cortex mount sentinel: "volume not mounted" conflated with "directory does not exist" |
| 2 | `pazny.backup` | ungated brew — Linuxbrew *ran* the formula and crashed in its own post-install |
| 3 | `pazny.backup` | our apt branch — `awscli` is not in the Ubuntu 24.04 archive |
| 4 | **`ok=550 changed=141 failed=1`** | the final smoke gate: `Infra: FAILED`, apps stack-up `rc != 0`, **1 / 8 probes OK** |

Runs 1–3 were defects and are fixed. **Run 4 is the Linux port itself**: the
playbook now completes end-to-end and the estate does not come up, which is the
pre-existing gap of `docs/hidden_fees/08` finally being *reported* instead of
passing as `0/0 ready`. Nothing in this release regressed it; this release is
what made it visible.

The supported platform is unaffected — the macOS estate converges
`ok=1431 failed=0`, and every blocking non-integration job is green.

### Known open at cut time

Named here because v0.9-beta named its red and this one owes the same.

- **FreeScout is local-auth-only; its `native_oidc` classification is
  aspirational.** Measured on the live estate during the release survey: both
  sources for the `freescout-oauth` module are HTTP 404, so `/data/Modules` is
  empty, the rendered `FREESCOUT_OIDC_*` env block is inert (the module is what
  consumes it), and `/login` offers no "Sign in with Authentik" button. The
  clone task reported `changed` on every converge because its `changed_when`
  matched `"Cloning into…"` — a string git prints *before* it fails. Two further
  tasks in the same block could never have worked either: `module:enable` ran
  from `/` where `php artisan` is "Could not open input file", and the config
  writer used `tinker --execute=`, a flag this image's tinker does not have. All
  three are fixed to observe effects and to say so out loud; **no replacement
  module source is invented**, because guessing one is how a second silent
  failure gets stacked on the first.
- **`stack-health-probe.py` passes an empty stack as `0/0 ready`** — unchanged
  since 2026-05-23; `docs/hidden_fees/08` remains `OPEN`. But the standing claim
  that the Linux wet-test therefore "proves nothing" is now **too pessimistic
  and is withdrawn**: on the release PR — the first non-draft PR since
  `pazny.cortex` was Ansible-ized, and the only trigger shape that actually runs
  the job — it got 226 tasks deep and stopped on a real defect. The cortex mount
  sentinel hard-failed on *any* absent `nos_data_root`, conflating "removable
  volume not mounted" with "ordinary directory nobody has created", so **every
  default-config install (`$HOME/nos`) failed there**, on Linux and macOS alike.
  It looked green only because the operator's `nos_data_root` had long been
  redirected to an external disk that exists. Fixed, and gated.
- **Ungated Homebrew calls do not skip on Linux — Linuxbrew runs them.** The
  next thing the wet-test found: `pazny.backup` brew-installed `awscli` on
  Ubuntu and died inside Homebrew's own post-install. The doctrine that every
  brew call is gated on `nos_pkg_manager` was simply not applied in six places.
  All six fixed — `backup` and `opencode` gained a platform split, `acme`,
  `tasks/tailscale.yml` and `tasks/observability.yml` are Darwin-gated at their
  include sites — and pinned by a gate that understands both role and
  `import_tasks` include sites. Two of those files default to **enabled**, so
  this was reachable on any real Linux install, not just CI.
- **Linux port scope, stated plainly:** host-side Grafana Alloy and Tailscale
  are macOS-only. The observability *stack* (Grafana/Prometheus/Loki/Tempo) is
  Docker and unaffected; only the host agent is skipped.
- **REM-151 / REM-152** (above) are open HIGHs.
- The **v0.9-beta GitHub Release was never published** — only the tag exists.

### One filesystem — measured, not yet built

The estate can hold the same document in three disjoint places and has no answer
to *"where does this file live"*. This release does not fix that; it establishes
what is true, which is the part that was missing.

- **S-0 identity, first cut.** Nextcloud was the single service keying accounts
  on a **hash** of the canonical uid — `user_oidc`'s `uniqueUid` defaults to on
  and hashes whatever the mapping produced, so the configuration read correctly
  while the result did not. `--unique-uid=0` on both provider paths, plus a
  read-back that verifies the **effect** (a 64-hex id is a hash whatever the
  provider table says). **Honest scope: this fixes the next login.** The existing
  hashed account is still present, is not migrated, and the converge says so by
  name — moving it needs `occ files:transfer-ownership` before any deletion.
- **Three candidate architectures written down and one rejected on the record**
  (`docs/archive/one-filesystem-architecture.md`), including the finding that POSIX
  mode bits are *decorative* on this estate: VirtioFS remaps ownership and every
  container runs as a different uid, so a design depending on `chmod` would work
  on Linux and be theatre on the operator's Mac.
- **apple/container measured against Docker** on a real 1.09 GB image rather than
  a toy: start time is a tie (2.1 s vs 2.4 s), bulk I/O favours apple by ~30 %,
  `stat` favours Docker by 9×, and the memory figures are **not** the 85× they
  appear to be — that is one container against a whole estate's shared VM. The
  measurement that decides adoption has a blocker no playbook can clear: macOS
  gates published ports behind the **Local Network** privacy permission, whose
  failure mode is a listening socket that silently drops traffic.
- Sequenced as its own roadmap (`docs/archive/per-user-container-roadmap.md`),
  explicitly **after** this tag.

### Security

**0 pending CRITICAL** — and this time the number is re-derived from the running
estate rather than inherited: six queue items were already live at their fix
version and had simply never been reconciled. Both former CRITICALs are now
**live-verified against `docker ps`**, not merely pinned — Gitea `1.27.0`
(REM-137, a 36-CVE cluster) and Metabase `v0.61.9` (REM-153,
`GHSA-cwxq-fmxq-jv8h`), the latter confirmed after the release converge
recreated the container.

Queue at cut, cycle-21: **152 items — 128 resolved, 15 pending (5 HIGH /
6 MEDIUM / 4 LOW), 5 vendor-blocked, 3 wontfix, 1 obsolete.**

The three sharpest findings of the cycle share one methodological cause: **a
GHSA with no CVE id**. A scan phrased as "no new *CVE* past the pin" was
literally true and wrong by six days.

**Cycle-21 ran unattended** at 02:14 on the release morning — the nightly Pulse
scan, whose verdict pipeline had never once produced output until it was fixed
earlier in this cycle. It is worth naming the two open items it raised that a
reader should weigh before deploying:

- **REM-151 (HIGH)** — `global_password_prefix` still defaults to `changeme`,
  and the weak-prefix assert does not cover local tenants. Given that REM-144
  was a *disclosure of the prefix*, this is the other half of the same surface.
  Open, and the fix (random prefix on first run, or extend the assert) is not in
  this tag.
- **REM-152 (HIGH)** — n8n `2.28.1` against a 17-GHSA advisory wave fixed in
  `2.32.7`. Another advisory-feed finding with no CVE id.

---

## v0.9-beta (2026-07-22)

> **nOS grows a face, the cortex learns itself, and the lifecycle becomes one
> command.** Two arcs, 228 commits since `v0.8-beta`. The first is below; the
> second (2026-07-20 → 22) replaces `blank`/`flush`/`uninstall` with a single
> `nos` CLI and an ordered removal ladder, negotiates the KEAP self-model
> contract to v1 as symmetric cross-repo gates, and opens `docs/hidden_fees/`
> as a standing ledger of deferred costs. Narrative: devlog
> `2026-07-22-nos-cli-and-removal-ladder`.

### The `nos` CLI and the removal ladder

- **One ladder, four levels.** `nos --remove=none|data|deep|all` replaces the
  overlapping `blank=true` / `flush=deep` / `uninstall=true` switches; `--leave`
  ends the play after removal instead of reconverging (machine handoff). Old
  switches still work through an unconditional compat shim.
- **Dry run unless confirmed.** Any level without `--confirm`/`-y` prints the
  resolved inventory — every path with `[exists]`/`[absent]` against the live
  filesystem — and stops. An off-allowlist value is a hard failure, never a
  silent no-op.
- **One source of truth + a verifier.** `tasks/removal-set.yml` is the only
  place each level's path set is built; the printer, the wipe, the source
  removal and a **post-removal absence assertion** all read it, so they cannot
  drift. The assertion exists because a 2026-07-21 uninstall reported success
  while leaving `~/keap` (2.1 GB) and a Nextcloud tree behind, and the surviving
  config then broke the next install.
- Built only after an independent review **rejected** the first plan for
  specifying a safety contract that appeared in no commit — then four more
  defects surfaced in the first live run, including a Docker mount preflight
  that had **never once succeeded** (a skipped task's registration overwrote the
  healthy probe's result) and a removal whose path overrides keyed on a
  different condition than the deploy's.

### Cross-repo contracts, and a ledger of what we owe

- **Self-model contract v1 with KEAP** — slug taxonomy ids, canonical knowledge
  format, producer-owned golden fixture, and **symmetric** gates: each repo pins
  the other's half. Protocol in `docs/doctrine/cross-repo-contracts.md`.
- **`docs/doctrine/gates.md`** — *a check that cannot fail is not a check*.
  Earned repeatedly this arc: a confirmation gate that pinned a literal level
  name had been certifying the very lie it existed to catch.
- **`docs/hidden_fees/`** — deferred costs, entry test *"nothing is failing and
  nobody is looking."* Seven entries, honestly unpaid; fee 07 records a
  mechanism nobody has explained yet, deliberately without a guessed remedy.
- **`nos_data_root` on external storage** — one lever moves the whole estate;
  validated by a full teardown plus a clean all-on install (**1531 tasks,
  `failed=0`, 63 containers, none unhealthy**).

### Known red at cut time — the Linux wet-test

`Integration (ubuntu-24.04)` is RED on this tag, and the tag ships anyway. The
honest reason: the defect is not new, it was *found* here. `stacks/infra/docker-compose.yml`
is not rendered on Linux, so `docker compose up infra` returns rc=1 and the STRICT
health probe passes the resulting empty stack as `0/0 ready` — the job had been
**green for weeks with no infra stack at all**, and only the post-run smoke ever
noticed (its 0.5 failure tolerance hid that until the probe count grew).
`docs/hidden_fees/08` carries the analysis; `CLAUDE.md`'s claim that this job
"proves the playbook" is corrected until the three pieces are closed.

What DOES back this tag is the macOS estate, live: a full teardown at
`--remove=all --leave` followed by a clean all-on install — **1531 tasks,
`failed=0`, 63 containers, 0 unhealthy, 48/48 smoke probes green** — plus
`tools/ci-local.sh` on the frozen 2.21.0 toolchain and 1901 passing anatomy
tests. Three real Linux defects were fixed on the way to finding the fourth
(`~/.local` chown, a FrankenPHP pin that did not govern its own fetch, and a
smoke probe that tested DNS instead of the service).

### The face and the cortex (2026-07-13 → 20)

> **nOS grows a face, and the cortex learns itself.** The seven days after the
> cortex GA produced 175 commits, two of which change what nOS *is*: the
> web-desktop (**nOS face**) becomes a real window manager with native apps over
> Bone's VFS, and **KEAP gains a self-model** — a knowledge tree describing nOS's
> own deployed architecture, generated from live state and mirrored into the
> star-map as its own constellation. Around them the **lifecycle closes** (`blank`
> gained a matching `uninstall`), the **constitution layer** lands
> (`docs/doctrine/` + a single-source path resolver), a run stops being wedgeable
> by its own telemetry, and the security queue reaches **zero CRITICAL pending**.
> Narrative: devlog `2026-07-20-release-v0-9-beta`.

### nOS face — a desktop, not a dashboard

- **Window manager v2–v4** — snap + tiling (thirds, 2×2, live gutters),
  dock unified with the app list, drag-to-top layout picker, live taskbar
  thumbnails, `Ctrl+Space` command palette, control panel + wallpapers.
- **Native app framework over Bone's VFS**, with three apps: **Files**
  (file-picker on root-guarded, fuzz-corpus-tested VFS copy/delete endpoints),
  **Tables** (DataTable editor with a gated write layer — RowEditor + KEAP RW
  token + `CreateTableModal`), **Explore** (the KEAP star-map, embedded).
- **`ServiceFrame` iframe windows** — every other service opens as a real window
  instead of a new tab. This also fixed the always-empty dock: Wing was keyed on
  `id` where the hub emits `slug`, so 0 of 37 services rendered.
- Vendored in-repo (`files/anatomy/face`, synced + built by `roles/pazny.face`),
  with a node CI job, a wiring linter, and security/datatable gates.

### KEAP cortex v1.6.2 → v1.17.2

- **Self-model** (`keap_selfmodel`) — a deterministic platform → stack → service
  knowledge tree generated **from real deployed state** (auto-derived
  SSO→authentik dependency edges), written to a doctrine class-2 shared dir and
  bind-mounted as a reserved fs-sync uid, so KEAP mirrors it into a standalone
  "nOS" constellation in `/explore` and embeds every card into vector space.
- **Git-SoT knowledge ingest** — `knowledge/canonical/` is the source of truth;
  `ingest.mjs` is a single idempotent import (per-file sha256 markers), with
  round-trip identity CI-gated. Data changes ride the git ref, no image rebuild.
- **Semantic lens** — exemplar axes + centrality + clusters computed by a Pulse
  job into a derived `node_features` layer.
- **Linked data** — Wikidata QID + entity typing + QRank scope onto the taxonomy,
  behind three disambiguation guards (search-description allow/deny, P31
  publication reject, embedding cosine veto); the naive top-hit baseline measured
  ~40% and was homonym-trapped.
- **Curator agent** (propose-only taxonomy reconciler) and **Track R3** typed
  cross-domain relations.

### Lifecycle — install ↔ uninstall

- **`uninstall`** — `-e uninstall=true` dry-runs by default,
  `+ confirm_uninstall=true` executes; removes source trees + anatomy runtime dirs.
- **Blank drift fixes**, from an operator catching a 2026-04-20 screenshot and a
  duplicate KEAP table surviving `blank=true`: blank now wipes KEAP's derived
  `/data` and removes the OpenClaw gateway daemon.
- **uid stability** — uids are keyed on username with a Czech-safe
  diacritic-folding slug; an unstable uid across blanks orphans the tree it owns.

### Resilience — a run you can't wedge

- **Telemetry circuit-breaker (now half-open)** + capped ring buffer on the
  fallback path + 4xx-no-retry. Root cause fixed: the callback signed with an
  un-rendered `{{ … }}` URL and a self-referential secret template; Bone
  self-heals a stale env secret inline.
- **External-volume mount preflight + self-heal** — a remounted SSD leaves
  Docker's VM a stale `/host_mnt` ref → every bind-mount fails and the STRICT
  health-wait hangs ~20 min with no clue. Probed before the first `compose up`;
  on blank, Docker Desktop is restarted and re-probed.
- **dnsmasq is actually started** (a blank had been shipping with DNS down) and a
  **systemic-failure smoke gate** fails a run when the platform is broadly dead.

### Doctrine + hardening

- **`docs/doctrine/` constitution layer** — doctrine is law, not a proposal;
  opens with `filesystem.md` (storage classes) and `observability.md`. Code-side
  counterpart: **`nos_data_root`**, a single-source path resolver replacing
  scattered per-role path guessing, with the service-engine path surface on top.
- **Healthcheck coverage** — `HEALTHCHECK` added to 12 health-blind services plus
  a coverage gate, so a booted-but-broken container stops passing as ready.
- **macOS 27 "Golden Gate"** forward-compat preflight + greppable
  `# VFS-DOCTRINE` markers on the three VirtioFS workarounds.
- **Security → 0 CRITICAL pending** (104 resolved / 14 pending / 4 vendor-blocked
  / 1 wontfix). REM-127 Traefik ForwardAuth underscore-header strip bypass
  (`X_authentik_groups` survives `Header.Del` → identity forgery on the SSO gate)
  closed at v3.6.23; REM-002 Woodpecker resolved; pin-wave batches 1–3;
  `wing.db` "database is locked" fixed via `busy_timeout` on all 13 writers;
  WordPress CVE-2026-63030 mitigated by blocking the REST batch endpoint (the
  fixed upstream is not dockerized yet).
- Named fixes: Nextcloud's OIDC provider registered **with literal quotes** (SSO
  silently dead), Gitea OIDC discovery failing for a missing `auth.<tld>` host
  mapping, PostgreSQL healing dir-mounted/empty SSL cert paths, Bone's launchd fd
  limit 256→8192.

### Not in this tag

The roadmap had pencilled v0.9 in as "epic acceptance" — PG 16→17 cut over
end-to-end, the first real migration authored *and* applied, blank reproducibility
re-proven. Those are operator-gated live converges and move to the **RC**; holding
a 175-commit arc for them would reproduce the release-debt pattern that left
`master` six weeks stale earlier this month.

---

## v0.8-beta (2026-07-13)

> **The cortex reaches 1.0.** This arc lands **KEAP — the knowledge organ of
> the nOS anatomy — at its first GA (`nos/keap:1.0.0`)**, integrated Tier-1 and
> enabled by default. It spans the Track K knowledge-filling epic, a browser
> capture surface, per-tier data-table sharing, and the backup/restore + agent
> wiring that makes the cortex a first-class, durable nOS service. No behaviour
> change for a non-`+keap` run; `install_keap: true` (default) now ships a
> fully-populated, agent-fed knowledge base. This single `v0.8-beta` tag
> absorbs the v0.7-beta line (which was never cut) plus the KEAP GA.

### KEAP cortex v1.0.0 — GA

- **Track K — knowledge filling, complete.** The seed 790-node taxonomy went
  from mostly-empty to a populated reference work, agent-authored and
  human-moderated end-to-end: **778/778 K1 descriptions** (the load-bearing
  search/embedding text, DescGraph doctrine) plus **node-article briefs** for
  levels 0–2 (abstract → article with mandatory `[[node-id]]` vazby + durable
  external links). Authored by the `librarian` agent on cost-tiered models
  (`NOS_AGENT_MODEL` per ceremony: describe = haiku, brief/judge = sonnet — so a
  bulk sweep never inherits the operator's flagship default), under a shared
  **house-style** contract (one encyclopedic voice, fixed terminology, cs
  mirrors en 1:1). Embeddings are generated **locally** via Ollama
  (`nomic-embed-text`, zero API cost). A `listPromotions` LIMIT-200 blindness
  that let the dup-guards re-serve nodes past 200 open proposals was closed
  (`db.openPromotions()` uncapped + an init-time dedupe).
- **Browser extension (MV3) capture surface.** An operator-installable
  companion pairs to a KEAP instance and captures pages/selections into the
  review queue. The `/ext/v1` surface gets its **own Traefik router without the
  Authentik middleware** (mirroring the `/ingest` device route) — an extension
  is a cross-origin, cookieless caller, so an SSO-gated route answered pairing
  with the login page; the server enforces its own pairing-bootstrap +
  Bearer-credential auth. Security review fixes shipped: RustFS row-id
  path-traversal guard, brief-renderer `javascript:`-URL XSS block, and a
  fail-closed CSRF guard on the pairing-approval endpoints.
- **Data tables — global RBAC tiers + sharing.** The R2′ TableStore now honours
  the four nOS Authentik tiers: a widened `visibility` scope
  (`private | tier-managers | tier-users | tier-guests | shared`, no migration)
  threaded through read/list access, guests read-only, and a `PATCH` route to
  re-scope a table after creation. An opt-in **fixture seed**
  (`keap_seed_fixtures`, once-only) offers a fresh install three illustrative,
  OLAP-shaped demo tables (one per scope) so the grid — and the RBAC — is
  legible on first boot.
- **Backup/restore + admin.** KEAP's libSQL store (`keap.db` — taxonomy, curated
  text, table registry+rows, and the vector corpus) joins the nightly backup via
  sqlite3 online `.backup` (WAL-consistent, and vector-index-safe where a
  `.dump` is not) with a matching container-aware restore path. The Admin ›
  Taxonomy tab was rebuilt from a sparse metadata overlay onto the real
  790-node tree (names + K1 descriptions, depth-indented, filterable). The
  agent surface (`mcp-keap` tool + `librarian` runner) and the moderated
  promotion pipeline round out the GA.

### Release mechanics

- `keap_repo_ref: v1.0.0` + `keap_version: 1.0.0`; the cortex source is pinned to
  the annotated GA tag on the app repo's release branch. Live-verified:
  `nos/keap:1.0.0` healthy, converge `failed=0`, smoke `49/49`, RBAC tier matrix
  + fixture seed + `/ext/v1` JSON all confirmed against the live edge.

---

## v0.7-beta (2026-07-09)

> **The converge becomes idempotent — and the security backlog's live-exploitable
> tip is closed.** This tag spans v0.6 → 2026-07-09 in two arcs. The first
> (2026-06-15) made `authentik_engine: tofu` survive non-blank re-runs. The second
> (late-June → 2026-07-09) closed the live-exploitable CRITICAL CVEs, brought the
> full ~61-container converge to green, and shipped the **first agent-authored
> upgrade recipe** (Gitea 1.25 EOL → 1.26.4) driven end-to-end through the nOS
> Wing/AgentKit agents. No new services; a non-`+all` run is behaviourally
> unchanged except that re-converges now succeed where they used to fail loud and
> the FreeScout / Bone / Alloy / Gitea CVE exposure is remediated.
>
> **Arc 1 — idempotency (2026-06-15).** v0.6 made OpenTofu the Authentik
> authority but only ever proved it on a *blank*. The first time the operator
> ran a second, non-blank converge, the tofu engine refused every plan —
> Authentik re-issues provider PKs on each converge, so the state pointed at
> stale IDs and the destroy guard correctly fired with no single object to
> blame. This tag makes `authentik_engine: tofu` survive re-runs, fixes the
> matching Portainer SSO false-failure, and lands an overnight multi-agent
> review (~40 mechanical fixes + 48 staged plan docs + a RAG architecture MVP).

### OpenTofu Authentik — idempotent across non-blank converges

- **The bug, root-caused live:** provider PKs churn out from under the tofu
  state on every non-blank converge (the providers are `managed=None` — no
  single churner to eliminate), so `tofu plan` read a dangerous in-place
  `client_id`/`external_host` flip and the destroy guard refused *every* re-run.
- **The fix:** a pre-plan **self-reconcile preflight**
  (`tasks/tofu-authentik.yml` + `tools/tofu-authentik-reconcile.sh --preflight`)
  re-points `module.service[*]` at the live PK via the stable
  `application.slug → provider` bridge *before* planning. Drift-conditional
  (no-op when aligned), **identity-only** (attributes are still diffed, so a
  real config edit still trips the guard), best-effort (plan + guard stay the
  rails), never calls `tofu apply`, backs up state first. The destroy guard also
  now catches dangerous in-place UPDATEs to immutable lookup fields. Proven by a
  3-converge arc (non-blank REFUSE → blank `failed=0` → non-blank `failed=0`
  end-to-end). Gate: `tests/anatomy/test_tofu_reconcile_preflight.py`.

### Portainer SSO — verify-via-public, no false drift

- Once OAuth2 is active, Portainer's internal admin login `422`s **by design**,
  so the JWT-based SSO verify (`POST /api/auth` → `GET /api/settings`)
  false-failed the converge though SSO was healthy, and raised a scary
  "DRIFT — manual reset" + "OAuth SKIPPED" on every re-run.
- Fix: read the **unauthenticated** `/api/settings/public` and fail loud **only**
  when `AuthenticationMethod != 3` (genuine dead SSO) — password-independent.
  Drift excludes `==3`; the OAuth-config JWT fetch is skipped when already active
  (break-glass drift downgraded to info, no heal — don't nuke working SSO). Opt-in
  `portainer_admin_auto_reset` heals a real drift. Gates
  `test_portainer_sso_verify_loud.py`, `test_portainer_admin_self_heal.py`.

### SSO fleet hardening (live-diagnosed)

A read-only multi-agent SSO fleet diagnosis (`docs/sso-fleet-diagnosis-2026-06.md`)
proved the SSO layer healthy and surfaced the real, recurring bugs:

- **Nextcloud OIDC — `allow_local_remote_servers`.** The browser login died with
  "Could not reach the OpenID Connect provider": user_oidc fetches discovery via
  NC's IClientService, whose SSRF guard (default off) blocked the call because
  `auth.<tld>` resolves through `extra_hosts:host-gateway` to a PRIVATE IP. A raw
  curl masked it (only NC's own client enforces the guard). Enabled in both OIDC
  paths (needed on public tenants too). Gate `test_nextcloud_oidc_local_idp.py`.
- **Hermes daemon — off the TCC-blocked SSD.** The forward_auth gate was healthy
  but the upstream daemon crash-looped: its launchd venv lived on `/Volumes/SSD1TB`
  and macOS TCC denies launchd reads there. Moved back under `$HOME`; the reload
  now bootout+bootstraps so a changed plist actually re-reads. Gate
  `test_hermes_venv_not_on_external_ssd.py`.
- **Uptime Kuma — single sign-in.** Kuma v1 has no OIDC, so its own login behind
  the Authentik gate was a pointless second password. Disabled (gated on
  install_authentik, idempotent, monitor-setup-safe). Gate `test_kuma_single_login.py`.
- **Working-as-designed, documented:** forward_auth services have no in-app SSO
  button by design; the XOAUTH2-via-forward_auth webmail SSO is architecturally
  impossible (the proxy forwards no token) — the master-user path is scoped as a
  deferred greenfield epic (`docs/archive/v07-overnight/v07-webmail-stalwart-oidc-single-login.md`).

### Security / CVE sweep (overnight review)

- PostgreSQL `16.13 → 16.14-alpine` (REM-088); Open WebUI tool-call retry cap
  (REM-055); Redis `requirepass` + client-auth (REM-003); nginx fail-closed
  locations (REM-048) + `X-authentik` header-overwrite (REM-047) gated;
  hedgedoc/paperclip Postgres SSL require-pinned; MariaDB test-db drop `no_log`'d
  (secret-leak fix) + CVE-citation synced across three sites.

### Blank-reset correctness

- Reset evicts **all** anatomy LaunchAgent plists, wipes the tofu Authentik
  state (so a clean-slate converge re-creates aligned PKs) + timestamped state
  backups + snappymail/spacetimedb bind dirs; the confirmation prompt and DB
  auto-deps were re-synced to the *real* wipe behaviour. New blank-safety gates.

### CI / release + docs

- Integration jobs capped at a 45-min timeout; GH Pages publish gated on
  release-artifact validation; shared actions → v6; `master` branch-protection
  setup documented. The overnight review staged 48 plan docs (Darwin-27 horizon,
  ansible-core 2.24 jump, `{{ vars }}` retirement Phase-1, euro-office toggle,
  SSO hardening, ISDS/eIDAS scaffold, retention enforcement) + a RAG-memory MVP
  architecture; a premature "restart-handler fail-loud" change was reverted (the
  rendered command was broken) and re-planned.

### Security cluster — live-exploitable CRITICALs closed (2026-07-08)

_Arc 2 begins here (late-June → 2026-07-09)._

- **REM-118 FreeScout (CVE-2026-53595, CVSS 9.4 — unauth account takeover).** The
  pinned tiredofit `php8.3-1.17.159` (FreeScout 1.8.219) is exploitable via a
  `%20`/empty `invite_hash` collision at `/user-setup` on MySQL/MariaDB. Fixed by
  the cross-org migration to **nfrastack 2.1.3-php8.3** (FreeScout 1.8.226) —
  tiredofit EOL'd the 1.17 line; `SITE_URL` → `APP_URL`. Shipped `upgrades/freescout.yml`
  (the first real upgrade recipe) to wrap the transition with DB-dump + health-gate + rollback.
- **REM-110 Bone — unauth recon scope-gated.** The `/api/services`, `/api/status`,
  `/api/health/aggregate` endpoints leaked every internal hostname/port/version to
  anonymous callers. Now `require_scope("nos:state:read")`-gated (liveness `/api/health`
  stays open); PyJWT floor bumped `>=2.13.0` (CVE-2026-32597/48525 residuals).
- **REM-107 Alloy — OTLP loopback bind.** The OTLP gRPC/HTTP receivers bound
  `0.0.0.0`; now `{{ alloy_otlp_bind_addr | default('127.0.0.1') }}`.

### Stacks converge-green — three degraded services unblocked

The STRICT `wait-stacks-healthy` gate had three services failing on a full run:

- **qgis** — a compose `entrypoint:` override *clears the image CMD*, so an
  idempotent stale-lock guard left Apache with no args → exit-0 restart loop.
  Restored `command: ["apache2", "-DFOREGROUND"]`.
- **gitlab** — puma 7.x `File.realdirpath()` on a VirtioFS-backed unix socket
  returns `Errno::ENOTSUP` → crash-loop. Put the rails sockets dir on a `tmpfs`.
- **puter** — upstream `puter:latest` preloads `-r telemetry.js`, which `require()`s
  a module the base image stopped bundling → `MODULE_NOT_FOUND` crash. Dropped the
  preload via an explicit `command:`.

Live-verified: **61 containers, 0 unhealthy, 0 restarting**; `failed=0`.

### Gitea 1.25 (EOL) → 1.26.4 — first agent-authored upgrade recipe (REM-099)

The Gitea 1.25 line is end-of-life; the unauth **CVE-2026-27771** (private
package/OCI registry served to anonymous pulls) + a cluster of 1.26-only fixes
(webhook SSRF, OAuth2 scope bypass, pre-receive multi-ref escalation) forced the
bump. This is the **first upgrade driven end-to-end through the nOS Wing/AgentKit
agents**, operator-supervised:

- **upgrade-architect** authored `upgrades/gitea.yml` — and corrected two ticket
  assumptions by live-inspecting the running container: the DB backend is **sqlite3**
  (not MariaDB → sqlite `.backup`, not mariadb-dump), and Gitea has **no `/-/readiness`**
  (that's GitLab's; the verified health gate is `GET /api/healthz`).
- **migration-author** wrote the migration record + the mandatory shadow-pin bump
  (`gitea_version` 1.25.5 → 1.26.4 in `default.config.yml`, source-of-truth wins).
- Recipe: `gitea-1.25-to-1.26`, `^1\.25\.` → `1.26.4`, security, container-scope,
  coexistence off (in-place same-org tag bump), self-disabling after apply.

### CI red→green

CI had been red on `dev` for three commits (pre-existing):

- **Pytest** — a Python module shadow: `test_upgrade_apply_detached_wiring.py`
  lazily imported `tests/upgrades/__init__.py` (+ sibling `migrations`/`state`
  shadows) instead of Bone's `upgrades.py`, failing the `UPGRADES_DIR`/`invoke_playbook`
  monkeypatch. Fixed by clearing the cached bare names so `syspath_prepend(BONE)` wins.
- **Contracts drift** — bone/wing OpenAPI + wing DB-schema snapshots were stale vs
  prior code (REM-110 scope-gate docstrings, coexistence copy-data route,
  plan-choice/detached schema columns). Regenerated; now idempotent.

### Verification

- **Arc 1 (2026-06-15):** `failed=0` on the confirm converge (idempotent,
  end-to-end) and the blank; tofu no-REFUSE on the second converge (the run that
  always refused before); Portainer SSO verify OK via the public endpoint.
- **Arc 2 (2026-07-09):** full converge `ok=1321 failed=0`, **61 containers /
  0 unhealthy**; e2e journeys **10/10** live-green (RBAC tiers, operator login,
  native OIDC, approval/halt-resume); offline suite **2301 passed / 0 errors**
  (CI-exact); contracts idempotent; **CI green on all jobs**. The Gitea 1.26.4
  upgrade is *armed* (pin bumped) and validated by recipe/schema/gate — its
  live-apply lands on the operator's next converge (STRICT health-wait is the gate).

### Known / residual

- **Gitea 1.26.4 upgrade is armed, not yet live-applied.** The pin is bumped and
  the recipe/migration validated, but the STRICT-health-wait converge that proves
  1.26.4 comes up healthy runs on the operator's next `ansible-playbook main.yml`
  (or blank). This is the release-validation gate before the tag is cut.
- **Version-pin drift wave (~28 items remaining, 1 CRITICAL: REM-002 Woodpecker).**
  Gitea (REM-099) was the first closed via the agentic recipe path; GitLab
  (REM-016, target moved 18.11.6 → 18.11.7 on the 2026-07-09 re-scan) and the rest
  are mechanical same-org bumps. Authoritative: `docs/roadmap.md`.
- The tofu reconcile is **identity-only** + best-effort — it re-aligns PKs but a
  genuine attribute edit still trips the destroy guard (by design). Carried from
  v0.6: gov is scaffolding (ISDS / NIA-eIDAS greenfield, retention is metadata);
  the MTI provider-flip reconcile is still hard-coded to the known flip set; the
  restart-handler corrective fix (per-class container restart) is planned, not yet
  shipped (only the safety revert landed).
- **GitLab root password** rejected by GitLab's dictionary policy on converge
  (`Password must not contain commonly used combinations`) — non-fatal status only;
  GitLab uses native OIDC (SSO login works), root pw is break-glass. Cosmetic;
  regenerate without dictionary words to silence it. FreePBX CVEs vendor-blocked
  (abandoned image); ERPNext parked; Bluesky PDS federation needs public DNS.

---

## v0.6-beta (2026-06-12)

> **OpenTofu becomes the Authentik authority (ADR-0001 Phase 1 — complete).**
> The SSO wiring layer — every provider, application, and outpost attachment —
> is now declarative HCL applied by OpenTofu, replacing the imperative
> `ak apply_blueprint` path for that layer (`authentik_engine: tofu`). The
> cutover was executed the hard way (Path B: tofu-engine blank from scratch),
> which surfaced and closed six structural traps plus three latent AgentKit
> runner bugs — each pinned by a CI gate. Validated end-to-end: tofu-engine
> blank `failed=0`, `tofu plan` no-op across the full tenant, smoke catalog
> 48/48, e2e SSO journeys green, and a full conductor agent run.

### OpenTofu Authentik cutover

- **Ownership split:** OpenTofu owns providers + applications + outpost
  attachments via one hand-authored `for_each` module
  (`modules/nos-authentik-app`) over a committed, generated registry
  (`state/tofu-authentik-services.yml` ← plugin + Tier-2 app-manifest
  `authentik:` blocks). The other six blueprints (groups / MFA / RBAC /
  agents / enrollment / brand) stay imperative by design.
- **Safety rails:** destroy guard (apply refuses ANY delete in the plan) +
  `-parallelism=1` (the outpost attachment is a read-modify-write list; the
  default parallelism raced 20 writes and kept 11) + reversible engine flag.
- **Six cutover traps fixed + gated** (full archaeology in
  `docs/opentofu-authentik-cutover.md`): Authentik auto-applies mounted
  blueprints (no-op render under tofu); `lookup('file')` never resolves
  nested Jinja post-2.19 (`lookup('template')` bridge); the outpost m2m race;
  Tier-2 app manifests missing from the registry; perpetual
  `internal_host_ssl_validation` diff; and **missing `grant_types`** —
  Authentik 2026.5.x made it an explicit ArrayField, so tofu-created
  providers rejected every native_oidc login with `invalid_request` while
  forward_auth stayed green (now declared in the module AND probed live by
  the new `tests/e2e/journeys/test_native_oidc_authorize.py`).
- **Post-cutover punch list shipped same-day:** tofu state artifacts in the
  nightly encrypted backup set (`run_tofu_state()`); disabled services
  filtered out of the tfvars (no SSO objects for `install_*: false`); a daily
  plan-only drift Pulse job (`authentik-tofu-drift-base`, never applies,
  drift → A9 notification).

### AgentKit runner — first live exercise

The release sweep ran the AgentKit native trigger paths on a deployed box for
the first time (the pulse claude-CLI runtime had masked them) and fixed three
latent bugs: the CLI agents-root off-by-one (Nette `%appDir%` is
bootstrap-caller-derived → `agentsDir` parameter + a CLI override valid in
both the repo and deployed nesting), the operator-trigger 500 (`PHP_BINARY`
is empty under FrankenPHP's embedded SAPI → `WING_PHP_BIN` → fallback chain),
and a missing RobotLoader in the CLI bootstrap (AgentKit keeps value objects
beside their aggregates — PSR-4 can't autoload them). Gate:
`test_agentkit_runner_paths.py`. The claude-CLI runtime remains the live
agent path (verified: full conductor self-test, exit 0, report event in Wing).

### Validation

Tofu-engine blank `failed=0` (ok=1418, all 8 stacks healthy) → smoke 48/48 →
`tofu plan` rc=0 (full parity) → e2e SSO/web-UI journeys green incl. the new
native_oidc authorize probe (18/18 providers) → agents: conductor + scout +
remediator full runs rc=0. Anatomy suite: 1225 tests.

## v0.5-beta (2026-06-06)

> **SSO/MFA coherence + a pre-release security cluster.** This tag makes the
> single-sign-on story *honest and load-bearing*: MFA posture is explicit
> (remembered by default, strict for gov), autologin is documented exactly where
> upstream allows it (and where it can't), and three security findings that the
> SSO work surfaced — a forgeable identity-header trust boundary, an n8n SSRF, and
> an Authentik provider-flip collision — are closed and live-verified. No new
> services; the change is in how the existing fleet authenticates. A non-gov,
> non-`+all` run is behaviourally unchanged except for the network-isolation move.

### SSO autologin — honest coverage

The goal is "it feels like one app": sign in to Authentik once, then every
`*.<tld>` service is zero-to-one click. What that actually delivers per service
is bounded by what each upstream supports — stated here rather than over-promised:

| Login UX | Services (representative) | Why |
|---|---|---|
| **0-click** (forward_auth passthrough) | Kiwix, Uptime Kuma, Paperclip, Puter, Wing, Mailpit, BI | Authentik session **is** the auth; service has no own login |
| **0-click** (native_oidc auto-redirect) | Grafana | Upstream supports forced OIDC redirect — no login form shown |
| **1-click** ("Sign in with Authentik") | Gitea, Nextcloud, Outline, BookStack, 2FAuth, Superset, Vaultwarden | Upstream OIDC, but no auto-redirect — one button on the service's own page |
| **gate + own login** (documented ceiling) | **portainer** (OIDC button, no auto-redirect), **infisical** (CE org-OIDC is enterprise-licensed → forward_auth gate + own form), **metabase** (OSS has no OIDC → gate + shared operator account) | Upstream limitation, not a bug — gate-enforced `supports:` so it can't be falsely promised |

The global force-OIDC mechanism (`sso_autologin`, single config var → plugin
loader) ships **dormant (default `false`)**; the per-service upstream-support
truth lives in `docs/sso-autologin-plan.md` and `docs/sso-and-attribution.md`.

### MFA posture — explicit, per-tenant

- **Default (non-gov):** posture B — global MFA, *remembered*. An enrolled user
  re-challenges once per `mfa_remember_window` (default `hours=8`), not every login.
- **Gov (`profiles/gov-local.yml`):** **strict step-up** — `mfa_remember_window:
  "seconds=0"`, 2FA on every authentication-flow run, no remember-device.
- MFA is **configure-not-deny** (`nos-tier1-mfa-flow`, TOTP + WebAuthn passkey):
  an un-enrolled Tier-1 user is prompted to set up a device inline and continues —
  never a hard lockout. Non-Tier-1 providers keep the stock flow byte-unchanged.

### Security cluster (SEC-02 + REM-043 + MTI)

- **SEC-02 — header-trust isolation.** calibre-web, 2FAuth and Firefly trust the
  forwarded `X-authentik-*` / `REMOTE_USER` identity header with **zero upstream
  validation**, so on the flat `shared_net` any peer container could forge it
  straight to the backend, off-Traefik. Fix: a Traefik-only `gated_net`
  (calibre + 2FAuth) and `gated_b2b_net` (Firefly, with MariaDB + Redis joined for
  DB reach) — the backends leave `shared_net`; only Traefik routes them. Firefly's
  `TRUSTED_PROXIES` narrowed from `**` to `172.16.0.0/12`. **Live-verified:** an
  n8n→backend forge is unreachable (rc=1) while the edge still serves 302→auth and
  Firefly stays healthy. Pinned by `tests/anatomy/test_sec02_*`.
- **REM-043 — n8n SSRF closed.** Enabled n8n's built-in
  `N8N_SSRF_PROTECTION_ENABLED` guard (n8n core since 2.12, ships default-OFF) via
  the n8n-base plugin compose-extension, gated by `n8n_ssrf_protection` (default
  true), with optional blocked/allowed-range overrides. The previously-queued
  remediation (`N8N_WEBHOOK_AUTH=true`) was a **non-existent env var** — corrected
  in the remediation queue. Pinned by `tests/anatomy/test_n8n_ssrf_protection.py`.
- **MTI provider-flip reconcile.** Authentik's `ProxyProvider` is a Django
  multi-table-inheritance subclass of `OAuth2Provider` sharing the base PK and the
  globally-unique Provider `name`; flipping a service native_oidc→forward_auth
  (e.g. infisical) left a stale `OAuth2Provider` row that collided with the new
  proxy provider (the live symptom was infisical 404). `main.yml` now deletes the
  stale row idempotently before re-applying blueprints (no-op on a blank run).

### Other

- **Calibre library autowiring** — empty-DB bootstrap (`calibredb` create on an
  unseeded library, config dir + ownership) plus a seeded Project Gutenberg sample
  book, so a fresh Calibre-Web has a working library on the first run.
- **Remediation queue reconciled** — 16 pending / 69 resolved / 2 vendor-blocked of
  87 (CLAUDE.md + the queue's own summary block were stale; recomputed from items).
- **Housekeeping** — gov MFA strict pinned, `.gitignore` covers the operator's
  local Calibre-sync helper.

### Known / residual

- **SSO ceilings are upstream, not bugs** — portainer/infisical/metabase keep an
  own-login step (see the coverage table). `sso_autologin` global force-OIDC is
  dormant pending the per-service rollout.
- **Gov is scaffolding, not deployable** — ISDS (datové schránky) + NIA/eIDAS
  federation are greenfield; retention is metadata, not enforced. See
  `docs/compliance/gov-readiness-audit-2026q2.md`.
- **MTI reconcile is hard-coded to the known flip set** (`infisical`); a future
  native_oidc→forward_auth flip must add its slug to the `_FLIPPED` map in `main.yml`.

---

## v0.4-beta (2026-06-01)

> **Cross-platform + gov-readiness in one tag.** The playbook now provisions
> **Ubuntu 24.04 LTS** end-to-end (macOS Apple Silicon remains the reference
> platform; every Linux gate is macOS-byte-identical, so macOS behaviour is
> unchanged), and a Czech public-administration audit drove a remediation batch
> closing the structural GDPR / NIS2 P0 controls — all **default-OFF +
> `profiles/gov-local.yml` opt-in** (a non-gov run is byte-unchanged on both OSes).
> Plus a CVE remediation batch, observability metrics wiring, macOS idempotence,
> and a pre-release CodeQL/security hardening pass. Built + reviewed via
> multi-agent workflows; the post-batch adversarial review (35 agents → 22
> findings) is folded in.

### Cross-platform (Linux)

- **Platform seam.** `tasks/_platform.yml` resolves `nos_pkg_manager`
  (homebrew|apt|dnf), `nos_service_manager` (launchd|systemd-user), `nos_nginx_*`
  paths and `nos_docker_bin` per OS; every Homebrew install, brew shell-out,
  `launchctl`/`osascript`/`defaults`/`pmset` call and macOS system-settings task
  is gated on `nos_pkg_manager == 'homebrew'` / `ansible_os_family == 'Darwin'`.
  Gates resolve true on a Mac — macOS behaviour is byte-identical.
- **Host daemons on Linux.** Bone, Pulse, the backup orchestrator and the
  heartbeat render `systemd --user` units (`pazny.linux.systemd_user::ensure_unit`,
  `loginctl enable-linger`) instead of launchd; a Persistent= timer's
  bound-oneshot failure during provisioning is tolerated (the timer's service
  may not be ready when the timer starts). Bone/Pulse venvs build from the system
  `python3` (`tasks/python.yml` apt-installs `python3-venv`).
- **Wing on Linux.** Wing runs the FrankenPHP single binary downloaded to
  `~/.local/bin` (brew on macOS), composer driven via `frankenphp php-cli`;
  `~/.local` is forced operator-owned before the download so prior become/pip
  steps can't leave it root-owned and break the unprivileged fetch. The
  FrankenPHP static-binary download + systemd-user wiring still carry
  `NEEDS-VM-VALIDATION` markers (`roles/pazny.wing/tasks/main.yml`) — exercised in
  CI's minimal config but not yet full-runtime-validated on a real Ubuntu 24.04 VM.
- **TLS + proxy.** mkcert installs via apt on Linux (CAROOT is platform-aware);
  `templates/nginx/nginx.conf` is portable (epoll/`user www-data`/`/var`+`/run`
  on Linux, kqueue/homebrew/`user _www` on macOS). Per-service host-nginx vhosts
  stay macOS-only — **Traefik is the edge proxy on Linux**.
- **Docker.** `docker_bin` rebinds to `/usr/bin/docker`; a final `docker info`
  readiness probe (`nos_docker_ready`) gates the whole compose layer so a
  Docker-less host (e.g. a GitHub macOS runner that dropped Docker Desktop) skips
  the stacks gracefully instead of erroring; the compose-`ps` display tolerates a
  missing compose file on runners that never brought stacks up.
- **CI wet-test.** A standing `Integration (ubuntu-24.04)` job runs
  `ansible-playbook main.yml` once on a GitHub Linux runner against the minimal
  `tests/config.yml` (`install_traefik: false`, most services off — it exercises
  the base playbook, not the Docker stacks). The job has **no idempotence
  second-run** (unlike the macOS `Integration` matrix); it was iterated toward
  green when first added, with a chain of `fix(linux)` / `fix(ci)` commits closing
  the initial gaps (systemd timer-start tolerance, missing-compose-file `ps`,
  `~/.local` ownership, docker-readiness gating, macOS `python3` + ubuntu
  `/run/sshd` env gaps). Windows/WSL deferred.

### Gov / GDPR compliance

Four structural P0 controls + the data-subject-rights surface, all **default-OFF**,
opt-in via `profiles/gov-local.yml` (Tailscale off, FreePBX pinned off,
`enforce_mfa` / `require_disk_encryption` / `wing_audit_chain_enabled`). Flag-off
renders byte-identical. LIVE-validated on a `+all +gov` reconverge (`failed=0`):
`gdpr_consent` migrated on the real `wing.db` (ledger + CLI only — capture is
unwired, see Residual gaps) and the 31 previously auto-generated boilerplate
purposes ingested as authored purposes.

**Structural P0 controls:**

- **Enforced MFA + at-rest gate.** Dedicated `nos-tier1-mfa-flow` (TOTP +
  WebAuthn, `not_configured_action=configure` for inline self-enrol, passkey
  resident-key `preferred` — relaxed from `required` to cut enrollment friction
  from ~3 tries to first-try). The blueprint routes **every** Tier-1 provider
  (`authentik.tier == 1`) through this flow when `enforce_mfa=true` — currently
  the **9** Tier-1 OIDC/proxy providers (`portainer`, `infisical`, `grafana`,
  `spacetimedb`, `wing`, `influxdb`, `mailpit`, `openclaw`, `qdrant`). At-rest:
  `tasks/preflight-at-rest.yml` hard-fails on FileVault-off (macOS) / no-LUKS
  (Linux) before any personal-data service starts (`require_disk_encryption`). A
  post-validation fix (commit 76906f13) drops a brittle bootstrap trap — the
  original `50-mfa-policy` blueprint was atomically rejected over a
  `policybinding.target` referencing a non-existent `nos-enrollment-prompts` stage
  + an invalid `default-password-change-prompt`; the policy bindings are dropped
  (policy object retained for future manual/UI binding) and blueprint apply
  reordered so `50-mfa-policy` lands **before** `10-oidc-apps`, so Tier-1 provider
  `authentication_flow` resolves `nos-tier1-mfa-flow` on first apply. The
  `nos-password-policy` object (length-15 + zxcvbn) is created but **not**
  blueprint-bound to enrollment/password-change prompts for the same brittleness
  reason.
- **Backup encryption.** `backup.sh` AES-256-CBC/pbkdf2 stream filter client-side
  before `aws s3 cp` to RustFS (`resolve_openssl` locates the binary to survive
  the launchd PATH constraint + macOS LibreSSL compat gaps); `.enc` objects
  auto-decrypt on restore via matching passphrase in `tasks/restore.yml` (legacy
  plaintext restores unchanged; fails loud on passphrase mismatch).
- **Tamper-evident audit chain.** HMAC-SHA256 per-event hash-chain (Bone Python +
  Wing PHP writers, byte-parity proven by CI); WORM triggers block edits on signed
  rows; daily Pulse verify with cached verdict in the Wing header badge
  (off-by-default, `wing_audit_chain_enabled`). An `audit_chain_meta` singleton
  (k/v) anchors the cached verdict + purge boundary; `AuditChainRepository` caches
  so each render is one SELECT, not a full chain walk; `backfill-event-chain.php`
  (anchored in `wing post.yml`) records the OFF→ON toggle boundary. Verifier
  detects offline tampering segment-aware (legacy-compatible).
- **Breach-notification engine.** `BreachDeadlines` pure-math (Art-33 72h, NIS2
  24h/72h/1-month clamp, timezone-normalized); hourly Pulse scan (registered by
  the new `gdpr-breach-base` plugin, owner of the scheduled job) escalates overdue
  stages as CRITICAL notifications (dedup'd via deterministic UUID);
  `bin/breach-{file,scan,report}.php` CLIs + read-only Tier-1 `/breaches` view;
  operator runbook in `docs/incident-response-plan.md`; provably inert (empty
  register → no-op).

**GDPR data-subject rights:**

- **Art-7 consent registry.** `gdpr_consent` ledger (grant→withdraw) +
  `bin/record-consent.php`, decoupled from SSO naming (the `gate_sso_required`
  proxy is named via a never-called `consent_capture_satisfied` predicate). The
  ledger and CLI exist and were migrated; **consent capture is not wired into any
  onboarding flow** — all 3 seeded activities ship `capture_wired:false`. Ledger ≠
  operational consent enforcement (documented gap).
- **Art-15 right-of-access export.** `tasks/gdpr-export.yml` (opt-in
  `[gdpr-export,never]`, dry-run-first, `-e export_confirm=true`), audited
  `state/gdpr-export-map.yml`, single-exact-email Authentik auto-capture,
  `0700/0600` bundle. Strict RFC-5322 email-regex validation blocks
  shell-metacharacters in the one-liner (host-RCE guard).
- **Art-17 erasure.** Honest DSAR terminal status — `record-dsar.php --update`
  records `completed` only when zero manual/failed steps remain (the `--update`
  path was a no-op bug, now fixed: commits 3b9504b7, 39c74180). Erasure-map reach
  documented for backend stores (Redis/Qdrant/RustFS/wing.db/Loki/Tempo) + 22
  per-service deletes; a new Qdrant delete seam (commits ff032d53, 9f3716bd);
  **exact-email** Authentik match guards against cross-subject erasure; strict
  email-regex validation on the erasure one-liner (host-RCE guard); status-enum
  validation prevents invalid transitions being written. A CI erasure-coverage
  gate (commit 8d214817) requires every gdpr plugin to carry an Art-17 entry,
  closing the silent-green new-service loophole.
- **Art-30 records.** The 31 plugin `gdpr` blocks that previously shipped
  auto-generated boilerplate purposes now carry author-provided purposes
  (`purpose_generated` 31→0); the CI gate `test_gdpr_register_coverage.py`
  requires an author-provided purpose for every `end_users`-PII service (33 such
  services across the 65 plugin records, each with an authored purpose).
  Controller/DPO block (Art-30(1)(a)) added to the DPA register (commit 35119192)
  but **ships placeholder-unset** (operator must fill it).
- **Access control.** `GdprPresenter` is gated `minAccessTier=1` — tier-4 guests
  can no longer view all subjects' PII in `/gdpr`.

**Baseline-claim corrections.** Three doc-vs-code falsehoods resolved in code:
encrypted-backup claim now true (commit 877da0e7), Bone embeddings redaction
implemented, the non-existent `audit_retention` role claim corrected to describe
the real manual-only `tasks/audit-retention.yml`. `docs/compliance/gov-readiness-audit-2026q2.md`
carries a reconciled 2026-06-01 scorecard that supersedes the original audit
snapshot.

**Residual gaps (honest).** The code is present but key controls remain
inert/manual in the deployed config: retention enforcement is metadata-only (no
scheduled per-`retention_days` purge beyond `wing.db` events); consent capture is
unwired (never-called predicate); erasure automation depth is 3/29 (26 remain
manual); DSAR bundles are unencrypted on disk; at-rest is a host-disk gate, not
per-service TDE/KMS; Czech ISDS (datové schránky) + NIA/eIDAS federation is
greenfield (needs external endpoints). Per the reconciliation, the platform moved
from "four structural §32/§21 absences" to "those present + opt-in; enforcement +
Czech-integration still absent."

### Security & CVE remediation

- **Bone embeddings email redaction.** `redaction.py` strips RFC-5322 email
  addresses from upsert payloads before Qdrant (recursive dict/list walk; scope is
  addresses only — non-email PII passes through); default-on,
  `BONE_EMBED_REDACT=false` disables; 5 unit tests pin behaviour.
- **CVE batch (7 commits, `origin/master..HEAD`).** n8n 2.14.1→2.20.7 (RCE trio
  CVE-2026-44789/90/91 + vm2/convict/handlebars, REM-086); Tempo 2.10.0→2.10.3
  (S3 `encryption_key` exposure via `/status/config`, CVE-2026-28377, REM-036);
  ntfy v2.21.0→v2.22.0 (CVE-2026-39087, REM-087); FreeScout pinned
  `php8.3-1.17.159` (bundles 1.8.219; CVE-2026-32752/35584/39384 — CRITICAL
  broken-access-control / missing auth / authorization bypass, REM-069/070/071);
  `symfony/yaml` 7.4.10→7.4.13 (3 low alerts — Billion Laughs ReDoS,
  untrusted-input; composer.lock only).
- **Version-pin unshadow (commit cdfe43e4).** n8n / Tempo / FreeScout pins synced
  from role defaults to `default.config.yml` (vars_file outranks role defaults —
  the pins were dead on render).
- **REM verifications.** socket-proxy (REM-001) resolved by architecture —
  Portainer already routes through `docker-socket-proxy` (verified, commit
  2b8fb950); pyodide (REM-054) pinned in Open WebUI, marked resolved (it's
  browser-sandboxed, not server-side jupyter).
- **dnsmasq token leak (commit 935b1eb4).** Jinja template fix (string literal vs
  concatenation) stops the `dnsmasq_dev_domain` token leaking into the
  `systems.description` API + a Grafana table.
- **Trivy rescan** of 61 images conducted (585 CRITICAL / 5002 HIGH fixable,
  overwhelmingly stale base-image OS packages).

### Observability

- **cAdvisor + Gitea + Woodpecker metrics.** cAdvisor now stores per-container
  labels (`--store_container_labels=true`) for per-container CPU/memory metrics;
  Gitea (`GITEA__metrics__ENABLED` + bearer `GITEA__metrics__TOKEN`) and Woodpecker
  (`woodpecker_prom_token`) metrics endpoints enabled and scraped by Alloy with
  bearer-token auth (new scrape jobs).
- **MTTR recording rule.** `woodpecker_pipeline_mttr_seconds` derives mean time to
  recovery from failed pipeline-run durations (`03-apps.yml`).
- **Dashboard PromQL fixes** across 4 dashboards: `gitea_repos` →
  `gitea_repositories`, corrected Woodpecker MTTR query, broadened
  `container_cpu` regex patterns, BookStack/Firefly/ERPNext metric-name prefixes.
- **No new Loki panels** — the gitea-push / outline-edit / hedgedoc-ops log panels
  reuse the **existing** `loki.source.docker` logs. Business-metrics exporters
  (sql_exporter for Outline/BookStack/Firefly/ERPNext/RBAC, nextcloud_exporter,
  per-user login label) deferred pending new observability infrastructure.

### macOS — idempotence

- **Idempotence fixes across macOS tasks.** PECL extensions detect by `.so` file
  existence (immune to registry emptiness on the macOS runner — iterated `pecl
  info` → `pecl list | grep` → `.so` check); `dotnet tool install` checks
  stdout+stderr for "already installed"; nginx/PHP-FPM/backup probe `launchctl`
  state first so service-start reports changed only on a real load; dnsmasq
  restart is notify-driven. `~/.zshrc` uses `copy force:false` instead of `touch`.
  Docker login-item addition now gates on `/Applications/Docker.app` existing (no
  phantom re-add on Docker-less Macs).
- **Stateless secrets persisted for idempotence.** `wing_api_token` regenerated
  every run, re-rendering Pulse's launchd plist → churning agents' bearer; now
  persisted in `~/.nos/secrets.yml` alongside `authentik_secret_key`. Four more
  service tokens (`vaultwarden_admin_token`, `paperclip_auth_secret`,
  `outline_utils_secret`, `hedgedoc_session_secret`) moved from regen-every-run to
  persisted. Stateless (rotatable session/auth tokens, not data-encrypting); one
  one-time churn on first run after upgrade, `changed=0` thereafter.
- **Volatile timestamps eliminated.** `service-registry.json`, the Grafana
  dashboard, `hub-cards.json`, and `notification-routing.json` dropped per-run
  `generated_at` / `ansible_date_time.iso8601` footers (no consumer reads them;
  dropping them makes renders idempotent). Wing launchd bootstrap (`changed_when`
  now keys on `bootstrapped` in stdout, not unconditional true), heartbeat, and
  coexistence cutover/cleanup/provision nginx-reload handlers corrected to gate
  `changed_when` on actual module changes.
- **nos_state refresh tasks** (introspect/persist/state-report/upgrade-engine)
  marked `changed_when: false` — they stamp a fresh `generated_at` but represent
  runtime housekeeping, not config drift.

### Pre-release hardening

- **CodeQL alert clears.** ReDoS guards on the email regex (`_EMAIL_RE` bounded to
  RFC limits — dot-free labels + explicit separators; `py/redos` cleared, commits
  1059a079 / 19192c39); url-substring assertion converted to exact list membership
  in `test_parser`; path-containment hardening (realpath + is_relative_to) on
  patches/upgrades; `index.html` tab allowlist clamped (commit 317ae077).
- **Portainer fail-closed.** admin-init gate reverted from fail-open (`!=204`) to a
  fail-closed allowlist `[404, 303]` (commit 530d8b3a); retry loop (6×5s) on
  health-check flakes; container restart on cold-blank window timeout (commit
  bec68f3b).
- **Probe fixes.** FreeScout verify adds the trusted-host `Host` header (commit
  b980014b); all service HTTP probes stop following redirects
  (`follow_redirects: none` — 3xx/SSL mismatches no longer burn retries, commit
  e3f928bf, fixes GitLab and others).
- **E2E tester identity.** Tester email domain now derived from `TENANT_DOMAIN`,
  not `NOS_HOST` (fixes Authentik 400 on IP domains, commit f4fd5573); SEC-6 edge
  token added to the playwright browser context (commit 6d462f85).
- **Contracts regenerated.** `wing.db-schema.sql` + `wing.openapi.yml` synced for
  drift (`gdpr_consent` table/indexes + `/api/v1/audit/verify` route, commit
  b8ee023a).
- **Doc hygiene.** Closed-bug docblocks trimmed (genealogy dropped, present-tense
  invariants kept); "until C5 lands" headers retired (C5 shipped 2026-05-12);
  CLAUDE.md / TLDR / main.yml / framework-docs freshness pass.

### Deferred / still-open

- **Gov:** Czech ISDS (datové schránky) + NIA/eIDAS federation greenfield;
  retention enforcement metadata-only; consent capture unwired; erasure automation
  3/29; DSAR bundles unencrypted on disk; at-rest is host-disk gate not
  per-service TDE/KMS.
- **Linux:** ubuntu CI Integration runs once (no idempotence second-run); Wing
  FrankenPHP path carries `NEEDS-VM-VALIDATION` markers (CI-exercised, not
  full-VM-validated); OpenClaw (Ollama/CUDA), Hermes, host-nginx per-service vhost
  templates on Linux (Traefik covers routing), and fleet provisioning
  (p2p/server-client/mesh) remain macOS-only / greenfield. Windows/WSL deferred.
- **Observability:** business-metrics exporters (sql_exporter, nextcloud_exporter,
  per-user login label) pending new observability infrastructure.

---

## v0.3-beta (2026-05-30)

> 116 commits since `v0.2-beta`. Headline: the **upgrade/coexistence engine now
> applies for real**, **tiered RBAC** reaches Wing, the **observability veins**
> are wired end-to-end (Grafana SQLite dashboards finally populate), and the
> **hub autowiring** epic (P1/P2) lands. Validated on the operator's host: a full
> all-on run (`ok=1201 failed=0`, 33/33 smoke), e2e 3 core journeys green, and
> CI-equivalent `pytest` 1398 passed / ansible-lint 0 / lockfile in sync. Draft
> notes — the `dev → master` PR + `v0.3-beta` tag are the operator's to cut
> (admin bypass; outward-facing).

### Upgrade & coexistence engine — first real apply

- **Apply path exercised end-to-end** (`daf6a2b..23609c8`). The `--tags upgrade`
  flow had never run for real — dry-run short-circuited before handlers, masking
  a multi-defect apply path. Now: `nos_migrate.py` renders recipe step strings via
  Jinja2 against play-vars + engine tokens; the upgrade-table `exec.shell` wrapper
  aliases recipe `command:`→`cmd`; `compose.set_image_tag` gained `override` +
  `--force-recreate` + converge-on-drift; recipes aligned to live container names
  (`<stack>-<service>-1`, base `docker-compose.yml`); `upgrade_exclude` carve-out.
- **CRITICAL fix** — `lookup('vars', …)` needs `wantlist=true`; without it the
  play-var list collapsed to first characters (a big-review catch before a real
  PG run; no live damage). authentik major upgrades are forward-only (rollback
  `noop`; restoring a dump under new code half-migrates the schema).
- **Coexistence apply** — track now derived from the legacy `{service}.yml`
  override (inherits env/networks/healthcheck) so stateful tracks boot (pg17
  verified beside pg16); major-version data via logical dump/restore at cutover.
- **Advisor stale-recipe gaps closed** — gitlab `from_regex` fixed to match
  18.10+ (was `^18\.(0|[1-9])\.`, blind to two-digit minors); 5 at-target
  forward-coverage tracks (grafana/mariadb/infisical/authentik/redis) so the
  advisor matches the installed line instead of reporting stale. Re-validated:
  architect GREEN, all 12 services with a known version match a recipe.

### RBAC & SSO

- **Wing tiered RBAC via Nette identity** — `ForwardAuthUserStorage` builds a
  stateless `Nette\Security` identity from the `X-Authentik-*` forward-auth
  headers each request (roles = Authentik groups). `BasePresenter` gained a
  declarative `$minAccessTier` enforced by default in `startup()`.
- **SSO admin propagation** — Authentik group → service admin for GitLab,
  Gitea (OIDC groups), Open-WebUI; **pure-SSO onboarding** (public signup closed,
  external-only registration) so a blank run needs zero manual registration.

### Observability veins (data → Grafana / Wing)

- **Grafana SQLite dashboards finally populate** — the `wing_sqlite` datasource
  was orphaned by the P1 datasource split (declared only in an unrendered
  `all.yml.j2`), so every playbook-timeline / AI-agent SQLite panel was dark
  against a full `wing.db`. New **`grafana-wing` composition plugin** renders it
  (gated on `install_observability` + `wing-base`); plugin pinned `4.0.6`. New CI
  gate pins the dashboard→datasource→provisioning chain. *Verified live: the
  datasource registers, health OK, panels query `wing.db`.*
- **Stub panels → real queries** — `22-ai-agents` (token / success-rate / latency /
  model-distribution from `agent_sessions`) and `90-security` (CVE bargauge
  repointed off a non-existent table to `remediation_items`); every SQL
  live-verified.
- **Idempotent re-sync** — `bin/ingest-remediation.php` + `bin/ingest-pentest.php`
  UPSERT `/remediation` + `/pentest` from the authoritative JSON every run
  (migrate.php was one-shot and drifted); WHERE-guarded so a steady-state run is
  `changed=0`.
- **gitleaks scan fixed** — 8.x dropped `--source` (positional repo now); every
  nightly scan had been exiting 2, leaving the Wing Inbox + Secret Findings empty.

### Hub autowiring (P1/P2)

- `ui-extension.hub_card` harvested into `/hub` (icons via self-hosted lucide,
  tier overlay, RBAC `viewerTier`); Uptime-Kuma probes `hub_card.health_check`;
  Nextcloud↔OnlyOffice auto-wired; non-clickable backends filtered + a post-run
  URL-audit gate.

### Agent runtime

- **Sequential run lock** — `pulse-run-agent.sh` (the single chokepoint) now takes
  an atomic `mkdir` mutex; concurrent claude-CLI agents had crashed all
  participants. Stale lock reclaimed by PID liveness; released on any exit.
- claude-CLI session tokens captured; agent exit verdict (REVIEW vs GREEN)
  propagated; agent reports shown in the session transcript.

### Fleet (review only)

- `docs/archive/fleet-review-2026q2.md` reconciles the aspirational fleet design with
  reality (built vs greenfield), confirms the naming (fleet mode / Track F), maps
  the p2p / server-client / mesh topologies, and tees up the push-vs-pull
  control-plane decision. No live config changed.

---

## v0.2-beta (2026-05-23)

Bundle **A19** — plugin-wiring unification, orchestration health-wait, single-run autowiring — on top of the A1–A18 anatomy + security hardening that landed since v0.1-beta.

### Security

- **A1–A18 hardening** carried forward: ANSSI/GDPR baseline, per-service recovery posture catalog (SEC-15), Pulse stdout/stderr scrub before forwarding to Wing (SEC-9).
- **CSRF** — Wing Latte templates now emit a CSRF token on every browser POST form (SEC-14).
- **HMAC** — Bone event ingestion validates Standard-Webhooks-shaped HMAC; bash-built JSON bodies are canonicalized (`jq --sort-keys -c`) so signatures verify.
- **Secret lifecycle** — `agent_credentials.secret_ref` stays a pointer (`env:` / `infisical:`), resolved only in function-local memory; per-user invite credentials provisioned into Infisical + Stalwart (A18).

### Plugin wiring

- **Notification unification** — every service plugin now carries the canonical A9 severity-routing block (`on_critical` / `on_high` / `on_medium` / `on_low` / `on_info` → channels `wing-inbox` | `ntfy` | `mail`). **55/55 plugins** conform.
- **Wiring contract** — new CI gate `tests/anatomy/test_plugin_wiring_contract.py` pins the shape; `tools/plugin-wiring-report.py` measures coverage; `files/anatomy/docs/plugin-wiring-capabilities.md` documents which manifest blocks have a live consumer vs. forward-ready metadata.
- **Conformance fixes** — qdrant-base gained a `feature_flag`; gitleaks gdpr/schema blocks conformed.

### Orchestration

- **In-stream health-wait heartbeat** — stack bring-up changed from blocking `docker compose up --wait` to `docker compose up -d` plus a non-blocking health-wait (`tasks/stacks/wait-stacks-healthy.yml`, `tasks/stacks/health-tick.yml`, `files/anatomy/scripts/stack-health-probe.py`). Each ~15s tick prints a per-stack readiness line into the main `ansible.log` (e.g. `iiab: 17/18 ready (waiting: jellyfin[starting])`), so a long bring-up no longer freezes the log. Applied across core-up, stack-up, and apps-up. The wait is **STRICT** — every container must reach healthy, no tolerance escape hatch.
- **Sequential cold-blank** — new `default.config.yml` vars: `stack_up_parallel` (default `true`; set `false` to bring stacks up one at a time and avoid Docker-daemon saturation when enabling everything on a cold blank), `stack_up_wait_timeout` (default 540s; per-stack health budget), `stack_wait_tick_interval` (default 15s). Slow services (GitLab cold init ~12 min) just need a generous timeout.
- **All-on test profile** — `profiles/all-on.yml` enables every known-good service (excludes `erpnext` / `freepbx` / `spacetimedb`), forces sequential bring-up and a 1200s timeout: `ansible-playbook main.yml -e @profiles/all-on.yml [-e blank=true]`.
- **Sudo-free stack runner** — `tools/nos-stacks.sh [tag]` runs the Docker stack layer autonomously, without sudo and without the interactive prompt (compose-up tasks carry zero `become:`; `-e nos_sudo_password=''` skips the vars_prompt). For agent / CI-driven dev; refuses `blank=true`.

### Autowiring

- **Single-run bootstrap** — `authentik_bootstrap_token` is now playbook-generated and pinned as the Authentik blueprint token key, so Wing /users + invitations work on a single blank run (no fetch-tool second pass).
- **Woodpecker OAuth2** — the Woodpecker↔Gitea OAuth2 client is auto-created during provisioning.

### Blank-run hardening (2026-05-24)

End-to-end fixes surfaced while validating the STRICT all-on blank — each pins a tendon the heartbeat / strict-wait exposed:

- **Health-wait early-exit** — a `when:` on a *looped* `include_tasks` does not short-circuit, so the heartbeat ran the full time budget every time (and a flap on the final tick could false-timeout). Each tick task is now gated on `not _wait_done` so the loop genuinely stops at first all-ready.
- **Core-up ordering** — DB setup (MariaDB / PostgreSQL roles) now runs *before* the infra health-wait, so Authentik's Postgres role exists on a cold blank (was a deadlock: the strict wait blocked on a DB user that hadn't been created yet).
- **Blank-safe autowiring** — gitea repo + Woodpecker wiring uses Gitea **admin Basic auth over 127.0.0.1** (a pre-provisioned `gitea_api_token` is wiped by `blank=true` → 401); Woodpecker activation skips gracefully when its OAuth-derived PAT cannot yet exist. Post-config container checks resolve the running container by compose **label** — the old `-f <base> ps -q <svc>` returned "no such service" (base composes are `services: {}`), silently skipping every admin/OIDC task on a blank, so gitea had no admin user → 401.
- **Bone telemetry** — `app.deployed` HMAC timestamp uses the current epoch (`date +%s`), not `ansible_date_time.epoch` (frozen at gather_facts → >300 s stale on an hour-long blank → "timestamp out of window" 401). The play-level Bone restart handler now `bootout`+`bootstrap`s (env reload) instead of `kickstart -k`.
- **Uptime Kuma** — monitor setup tolerates Socket.IO event-delivery starvation under peak load: a larger per-event timeout, fail-fast after 3 consecutive timeouts (was a ~30-min hang), and a role-level retry until the load settles. A heavily-loaded blank may still defer monitor creation to a host-idle `--tags uptime_kuma` re-run (non-fatal — monitors/events are never lost).
- **Traefik** — Tier-1 routing resolves upstreams by container name on the shared network (the IPv6 host-gateway path produced 502s).

### Security review + hardening (2026-05-24)

A 5-agent audit (`docs/llm/security/2026-05-24-multiagent-review.md`) against the SEC-1..15 baseline — solid, no true CRITICALs after reconciliation. New hardening:

- **SEC-16** — weak-prefix gate: refuse `global_password_prefix` in {`changeme`, '', <12 chars} on a public tenant (it seeds DB roots, OIDC/agent secrets, admin pws). Lenient on `dev.local`; `-e allow_weak_prefix=true` bypass. Dead prefix-derived `NOS_DEPLOY_HMAC_SECRET` fallback + retired `BONE_SECRET` dropped from the launchd plists.
- **SEC-17** — Pulse execution-boundary command allowlist: the SEC-8 allowlist now enforces in the runner that spawns the process (not just the PHP create path), so *any* `pulse_jobs` row is gated. Child env scoped — secrets stripped (`WING_API_TOKEN`, …), job-supplied loader/PATH overrides (`DYLD_*`/`LD_*`) refused; `max_runtime_s` clamped.
- **SEC-18** — 83 `no_log: true` across 30 task files (admin pws/tokens were persisting in Wing's SQLite via the telemetry callback, which redacted by key-name only); the callback now scrubs by value too; every shell pipe gets `set -o pipefail`; the Bluesky bridge `| quote`s the Authentik-sourced email (injection).
- **portainer** — `--http-enabled` (2.19+ 303-redirects plain HTTP → HTTPS, which silently skipped admin-init + OAuth setup).

Deferred (tracked in the review): the OIDC/agent-secret compartmentalization refactor (mitigated now by SEC-16), deploy-trigger edge-gating, askpass-on-failure cleanup.

### Validated by

- STRICT all-on blank (`-e @profiles/all-on.yml -e blank=true`): **`failed=0`, zero fatal**, with the hardening live (M-SEC1 gate passes on a ≥12 prefix; `no_log`/pipefail post-config unaffected), **Kuma creating all 48 monitors in-context**, and **Bone `app.deployed` returning HTTP 200** (the timestamp fix).
- Gate suite green: `pytest` (1120 passed, 4 skipped — incl. the SEC-17 Pulse-allowlist tests), plugin-loader smoke (63 ok / 0 failed / 0 schema), wiring contract (DAG / gate-parity / notification), ansible-lint (`risky-shell-pipe` fixed, not skipped), `composer validate`, `--syntax-check`. `tests/e2e` runs in CI with a live tester identity.
