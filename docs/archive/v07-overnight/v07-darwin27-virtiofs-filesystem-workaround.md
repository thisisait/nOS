# v0.7 — Darwin 27 VirtioFS filesystem-workaround doctrine (consolidate + gate the scattered hacks)

Status: PLAN (do not implement from this doc without operator review)
Branch: `feat/v0.7-overnight`
Related: P0.1 (ERPNext named-volume migration), MariaDB VirtIOFS InnoDB crash fix, A19
stack-up retry loop, `docker/for-mac#4936` (nested file-bind), Stalwart cert-path hack.

---

## 1. Problem / why

nOS targets Apple Silicon Docker Desktop, whose host↔VM file bridge is **VirtioFS**
(gRPC-FUSE on older Desktop builds). Over v0.1→v0.6 the playbook accumulated **at least
six independent, ad-hoc VirtioFS workarounds**, each invented in isolation when a service
broke, each with its own prose comment, none sharing a name, a variable, a doctrine doc,
or a test gate. They are scattered across roles, base stack templates, and orchestrator
tasks:

| # | Site | Symptom that forced it | Shape of the workaround |
|---|------|------------------------|--------------------------|
| 1 | `roles/pazny.mariadb/templates/compose.yml.j2:23-37` | InnoDB crash mid-FK-ALTER, OS error 71 (EPROTO) on `.ibd` (BookStack migration #10 reproducer) | data → **Docker named volume** `mariadb_data` (inside VM ext4), not host bind |
| 2 | `roles/pazny.erpnext/templates/compose.yml.j2` + `defaults` + `tasks/*` | `OSError [Errno 5] I/O error in filelock.__exit__` | sites → **named volume** `b2b_erpnext_sites`; `erpnext_data_dir` deprecated |
| 3 | `roles/pazny.wordpress/templates/compose.yml.j2:14-25` | nested **single-FILE** bind on SSD-backed `wordpress_dir` → "mountpoint outside of rootfs", iiab stack-up dies | mount mu-plugins as a **directory**, not per-file |
| 4 | `roles/pazny.smtp_stalwart/templates/compose.yml.j2:43-52` | nested cert file-bind inside `/etc/stalwart` → "mountpoint outside of rootfs" | cert mounted at **top-level `/certs/`**, outside the parent dir bind |
| 5 | `tasks/stacks/core-up.yml:289` | Loki crashes config phase when Docker auto-creates a missing bind source as a **directory** | imperative **scratch-dir cleanup** (`state: absent`) before bring-up |
| 6 | `tasks/stacks/stack-up.yml:266` | nested single-file binds intermittently fail `up -d` (rc=1, container stuck "Created") | A19 **retry loop** (`until rc==0`, retries 2) absorbs the transient |

Two structural problems with this state:

1. **No invariant.** Nothing stops the *next* stateful-DB role from shipping a raw host
   bind-mount of its data dir straight back into the exact InnoDB/filelock crash class.
   The knowledge lives only in six unconnected prose comments — invisible to a contributor
   adding a 7th service. This is precisely the failure mode the C1 image-pin gate and the
   socket-proxy gate were built to prevent for *their* domains; the VirtioFS class has no
   equivalent.

2. **A forward hazard: Darwin 27.** macOS major bumps have repeatedly changed Docker
   Desktop's file-sharing backend behaviour (`osxfs` → gRPC-FUSE → VirtioFS; nested-bind
   semantics tightened more than once — `docker/for-mac#4936`). `default.config.yml` and
   `CLAUDE.md` already reference "macOS 27" / `arm64_sequoia` as the live floor. A macOS 27
   Docker Desktop that tightens nested-file-bind handling further (or changes VirtioFS error
   codes) would silently re-break workarounds #3/#4/#6 — and the only signal today is a
   blank run dying deep in stack-up. We want the workaround surface **named, centralized,
   and test-pinned** *before* the OS bump, not rediscovered the hard way during it.

**Scope (honest).** This item does **NOT** invent a new runtime mechanism, change any
live service's storage backend, or claim to "fix VirtioFS" (it is an upstream Docker
Desktop property we cannot patch). The deliverable is **doctrine + an enforced invariant
+ consolidation of the prose into one referenceable home**:

1. A single doctrine doc (`docs/darwin-virtiofs-doctrine.md`) that names the failure
   classes, the canonical workaround per class, and the decision rule ("stateful DB / heavy
   random-write / filelock → named volume; nested single-file bind → directory mount or
   top-level relocation").
2. A pytest anatomy gate (`tests/anatomy/test_virtiofs_doctrine.py`) that **inventories the
   six known workaround sites** (allowlist-with-reasons, exactly like
   `test_image_pin_hygiene.EXCEPTIONS` / `test_docker_socket_proxy.SANCTIONED_*`) AND
   asserts the **forward invariant**: no *known-stateful* service may bind-mount its DB
   data dir from the host (it must use a named volume). A 7th MariaDB-class regression
   fails the gate.
3. A small **central marker** (a single Jinja comment token + the doctrine link) added at
   each existing workaround site so all six are greppable by one string and cross-reference
   the doc — turning six orphan comments into one documented family.

This converts an implicit, six-times-rediscovered tribal practice into an explicit,
test-pinned doctrine — and gives the Darwin 27 upgrade a green/red signal instead of a
blank-run autopsy.

---

## 2. Exact files / roles to touch

### New doctrine doc (the consolidation home)
- `docs/darwin-virtiofs-doctrine.md` — NEW. Names the 4 failure classes (InnoDB
  EPROTO/FK-ALTER, Frappe filelock I/O error, nested single-file bind "outside rootfs",
  Docker auto-creates-missing-source-as-dir), the canonical fix per class, the decision
  rule for new services, and a table linking to all six current sites. Cross-references
  `docker/for-mac#4936` and the A19 retry loop. This is where future readers land.

### New gate (mandatory — the load-bearing deliverable)
- `tests/anatomy/test_virtiofs_doctrine.py` — NEW. Allowlist-with-reasons + forward
  invariant (see §4).

### Central marker at each existing site (comment-only, zero behaviour change)
Add one greppable token `# VFS-DOCTRINE:` + a `docs/darwin-virtiofs-doctrine.md#<anchor>`
link above each workaround. NO logic change — these are documentation edits the gate keys
off:
- `roles/pazny.mariadb/templates/compose.yml.j2` — above the named-volume comment block.
- `roles/pazny.erpnext/templates/compose.yml.j2` — above the named-volume header.
- `roles/pazny.wordpress/templates/compose.yml.j2` — above the directory-mount comment.
- `roles/pazny.smtp_stalwart/templates/compose.yml.j2` — above the `/certs/` relocation.
- `tasks/stacks/core-up.yml` — above the Loki scratch-dir cleanup task.
- `tasks/stacks/stack-up.yml` — above the A19 retry loop.
- (Audit during implementation for stragglers: `roles/pazny.nodered/tasks/main.yml:17`
  references osxfs/virtiofs UID mapping — classify as benign-mention or add a marker;
  `roles/pazny.bookstack/tasks/post_migration_attempt.yml:32` references the now-fixed
  named-volume case — marker as historical/closed.)

### Forward-invariant data: the stateful-DB inventory the gate enforces
- The gate needs a list of "DB-class services whose data MUST be a named volume." Source it
  from the role compose templates themselves (services whose image is a known DB engine:
  `mariadb`, `mysql`, `postgres`, `redis` is durable-write, plus the filelock-class
  ERPNext). Encode as `NAMED_VOLUME_REQUIRED` in the test with a one-line reason each.
  **Do not** add a new `default.config.yml` var for this — keep the inventory in the gate
  (it is test fixture data, not runtime config), dodging the stock-Jinja eager-resolve trap
  entirely (see §5).

### Docs / pointers
- `CLAUDE.md` — add a one-line pointer under "Apple Silicon Constraints" → the new doctrine
  doc (this is the natural home; do not bloat the Known-Tech-Debt section).
- `RELEASE.md` (v0.7 section) — one-line pointer once shipped.

**Explicitly NOT touched:** PostgreSQL's storage backend (verify in §3 whether PG already
uses a named volume or a host bind — if host-bind and stable, document *why* it survives
where MariaDB didn't, rather than churning it). No live `docker volume` mutation. No
blank. No service restart.

---

## 3. Approach (step order)

1. **Inventory + classify first (read-only).** Grep the full
   `virtiofs|VirtioFS|outside of rootfs|filelock|named volume|EPROTO|error 71` surface
   (the §1 table is the starting set — confirm completeness, catch the Node-RED/BookStack
   stragglers). For each: failure class, current fix, whether it is load-bearing or a
   historical/closed mention. Record in the doctrine doc.
2. **Resolve the PostgreSQL question.** Read `roles/pazny.postgresql/templates/compose.yml.j2`:
   does PG data sit on a host bind or a named volume? If host-bind and demonstrably stable,
   the doctrine must explain the asymmetry (PG's write pattern vs InnoDB's FK-ALTER /
   Frappe's filelock) so the gate's `NAMED_VOLUME_REQUIRED` list is *principled*, not
   cargo-culted. If PG is *also* a named volume, the rule is simply "all DB engines."
3. **Write the doctrine doc** (`docs/darwin-virtiofs-doctrine.md`) — the four classes, the
   decision rule, the site table, the Darwin-27 forward note.
4. **Write the gate (red→green ratchet).** Author `test_virtiofs_doctrine.py`:
   - `KNOWN_WORKAROUND_SITES` allowlist (six entries + any straggler), each `(file,
     match-token): "reason"`. Prove green against today's tree.
   - `NAMED_VOLUME_REQUIRED` forward invariant. Prove green (mariadb/erpnext already comply).
   - A **negative-control** assertion: a synthetic raw `- {{ x_data_dir }}:/var/lib/mysql`
     style bind in a known-DB service must be the thing that trips it — encode the
     detection so a real regression (not just a renamed file) fails.
5. **Add the `# VFS-DOCTRINE:` markers** at each site (comment-only). Re-run the gate — the
   allowlist now keys off the marker token, so a removed/renamed site forces an allowlist
   update (keeps it honest, same as `test_image_pin_hygiene.test_exceptions_still_apply`).
6. **Run the full anatomy suite + `--syntax-check`** (§6). The marker edits are inside Jinja
   templates → confirm they don't break a render (comments are safe, but
   `--syntax-check` + a `--check` render of one affected stack proves it).
7. **Commit** to `feat/v0.7-overnight` (Conventional Commit, surgeon tone). No push.

Every change is **doc + comment + a new test** — zero live mutation, zero render-behaviour
change. Per machinery doctrine the markers take effect only on the next operator run, and
they are comments, so even then nothing changes at runtime.

---

## 4. Gates it needs (`tests/anatomy/test_virtiofs_doctrine.py`)

All offline, fast, pure file-scan — no Docker, no live system. Mirrors the
allowlist-with-reasons pattern of `test_image_pin_hygiene.py` +
`test_backup_restore_contract.py`.

**`test_known_workaround_sites_present()`**
- For each `(path, token): reason` in `KNOWN_WORKAROUND_SITES`, assert the file still
  contains the `# VFS-DOCTRINE:` marker (or the canonical anchor). A workaround silently
  deleted/refactored away forces the allowlist to be updated — catches drift in both
  directions (same contract as `test_exceptions_still_apply`).

**`test_doctrine_doc_links_every_site()`**
- Parse `docs/darwin-virtiofs-doctrine.md`'s site table; assert every
  `KNOWN_WORKAROUND_SITES` path appears in it (doc can't silently fall behind the code).

**`test_stateful_db_services_use_named_volumes()`** — the forward invariant.
- Scan `roles/pazny.*/templates/compose.yml.j2` + `templates/stacks/*/docker-compose.yml.j2`.
- For each service whose `image:` matches a known DB engine in `NAMED_VOLUME_REQUIRED`
  (`mariadb`/`mysql`/`postgres`/…), assert its data path (`/var/lib/mysql`,
  `/var/lib/postgresql/data`, …) is bound to a **named volume token**, NOT a host path
  (`{{ *_dir }}` / `/Volumes/` / `~` / an absolute host path).
- A 7th DB-class role that ships a host bind-mount of its datadir fails here. **This is the
  Darwin-27 regression guard.**

**`test_no_nested_single_file_bind_in_external_dir()`** (best-effort, class-3 guard)
- Heuristic scan for a volume line binding a single **file** (no trailing `/`, has an
  extension) whose host source is nested under another bound directory or under
  `{{ *_dir }}` / `external_storage_root`. Flag unless the site is in
  `KNOWN_WORKAROUND_SITES` (wordpress/stalwart are the sanctioned relocations). This one is
  necessarily fuzzy — keep it conservative (low false-positive), document its limits in the
  test docstring, and treat it as a tripwire not a proof. If it proves too noisy in
  implementation, **demote it to a warning-only collect/print and keep the three hard
  assertions** — the named-volume invariant is the must-have.

Also keep green: `test_image_pin_hygiene` (no new image introduced, but the doctrine doc
must not add a floating tag in an example), `test_backup_restore_contract` (see §5 risk 1 —
named-volume changes touch backup semantics; this plan adds no new named volume, so it
should stay green, but re-run it).

---

## 5. Risks

1. **Named-volume ↔ backup coupling (the load-bearing risk).** A host-bind data dir is
   covered by `backup_dirs_to_dump`; a **named volume is NOT** — it needs either a logical
   DB dump (mariadb/PG already have one, and `backup_volumes_to_dump` deliberately *excludes*
   `mariadb_data` as redundant) or a `backup_volumes_to_dump` entry. **This plan introduces
   no new named volume**, so it changes no backup contract — but the doctrine doc and the
   gate MUST state the rule loudly: *"flipping a service to a named volume = you have just
   removed it from the host-bind backup set; add a logical dump or a `backup_volumes_to_dump`
   entry, verified by `test_backup_restore_contract.py`."* If a future operator acts on the
   doctrine and converts a service, that gate is the safety net. Cross-link the two docs.
2. **PostgreSQL asymmetry.** If PG turns out to be a stable host-bind, the `NAMED_VOLUME_REQUIRED`
   list must be *principled* (exclude PG with a documented "PG's WAL/write pattern does not
   hit the InnoDB FK-ALTER EPROTO path") — otherwise the gate either false-fails PG today or
   cargo-cults a rule it can't defend. Resolve in §3 step 2 before encoding the list. **If
   unsure, scope the gate to the two PROVEN classes (mariadb-engine + erpnext-filelock) and
   leave PG documented-but-unenforced** rather than guessing.
3. **The nested-file-bind heuristic is fuzzy.** Class-3 detection (single-file bind nested
   in an external dir) has no clean syntactic signature — over-strict = false fails on
   legitimate config-file mounts (every service mounts e.g. a `*.yml` config). **Mitigation:**
   make this the *soft* assertion (warn/collect, demotable), keep the three structural
   assertions hard. Do not block the deliverable on a perfect class-3 detector.
4. **Stock-Jinja vars trap — avoided by design.** The inventory lists live in the **test
   file**, not `default.config.yml`. No new runtime var is introduced, so the eager-resolve
   `{{ vars }}` trap (`test_config_stock_jinja_only.py`) cannot bite. If implementation ever
   reaches for a config var, it must use stock filters + a real default — but the plan's
   intent is zero new vars.
5. **Marker comments inside Jinja must not break rendering.** `# VFS-DOCTRINE:` lines are
   plain comments in YAML/Jinja templates — safe. Still, run `--syntax-check` + a `--check`
   render of one marked stack (e.g. `--tags mariadb --check`) to prove no `{# #}`-style
   Jinja-comment accident (recall the `jinja-rendered-shell-brace-hash-trap` memory: a stray
   `{#`/`#}` in a `template:`-rendered file is a render bomb). Use `#` line comments, never
   `{# … #}` inside a value, and never `${#...}`-style tokens.
6. **Over-claiming.** Do NOT mark any service "VirtioFS-immune" or claim the OS bug is
   fixed. The doctrine documents *mitigations*; VirtioFS remains an upstream Docker Desktop
   property. The Darwin-27 angle is "early-warning gate," not "guaranteed forward-compat."
7. **Linux portability.** The whole class is macOS-Docker-Desktop-specific; on Linux there
   is no VirtioFS host bridge (bind mounts are native). The named-volume choice is harmless
   on Linux (works identically), and the gate is a static file scan (platform-independent).
   The doctrine doc should note Linux is unaffected so a Linux operator isn't alarmed.

---

## 6. Verification recipe (all read-only / offline)

```bash
cd /Users/pazny/projects/nOS

# 1. New gate + full anatomy suite green
python3 -m pytest tests/anatomy/test_virtiofs_doctrine.py -q
python3 -m pytest tests/anatomy/ -q

# 2. Backup-contract gate still green (named-volume ↔ backup coupling untouched)
python3 -m pytest tests/anatomy/test_backup_restore_contract.py -q

# 3. Image-pin + stock-Jinja gates green (no new image, no new var)
python3 -m pytest tests/anatomy/test_image_pin_hygiene.py tests/anatomy/test_config_stock_jinja_only.py -q

# 4. Playbook still parses (marker comments inside templates must not break render)
ansible-playbook main.yml --syntax-check

# 5. Render sanity — one marked stack renders clean (comments don't bomb Jinja):
ansible-playbook main.yml --tags mariadb --check 2>&1 | tail -5

# 6. Inventory proof — every workaround site is now greppable by ONE token:
grep -rn "VFS-DOCTRINE:" roles/ tasks/ templates/   # expect ≥6 hits, all in the allowlist

# 7. Forward-invariant proof — no DB-class service host-binds its datadir:
grep -rnE "(/var/lib/mysql|/var/lib/postgresql/data)" roles/*/templates/compose.yml.j2 \
  | grep -vE "named volume|mariadb_data|postgres.*_data:" || echo "OK: all DB datadirs on named volumes"

# 8. (Operator, optional, READ-ONLY live) confirm the named volumes exist as claimed —
#    inspect only, never create/remove:
docker volume ls --filter name=mariadb_data --filter name=b2b_erpnext_sites
```

Expected end state: new gate green, full suite green, `--syntax-check` clean, all six (+
any straggler) workaround sites carry the `# VFS-DOCTRINE:` marker and are listed in
`docs/darwin-virtiofs-doctrine.md`, the named-volume forward invariant pins the DB-class
services so a Darwin-27-induced (or contributor-induced) regression fails red instead of
dying in a blank run.

---

## 7. Definition of done

- [ ] `docs/darwin-virtiofs-doctrine.md` lands — four failure classes, decision rule, site
      table, Darwin-27 forward note, backup-coupling warning, Linux note.
- [ ] `tests/anatomy/test_virtiofs_doctrine.py` lands; allowlist + named-volume forward
      invariant; suite green.
- [ ] All six workaround sites (+ any straggler found in §3 inventory) carry the
      `# VFS-DOCTRINE:` marker linking the doc.
- [ ] PostgreSQL asymmetry resolved & documented (named volume, or principled exclusion).
- [ ] `test_backup_restore_contract.py` re-run green (coupling untouched; no new named vol).
- [ ] `ansible-playbook main.yml --syntax-check` clean + one marked-stack `--check` render OK.
- [ ] CLAUDE.md + RELEASE.md one-line pointers added.
- [ ] Commit on `feat/v0.7-overnight`, Conventional Commit, surgeon-tone body, no push.
- [ ] No new `default.config.yml`/`default.credentials.yml` var introduced (inventory lives
      in the gate); zero live mutation.
