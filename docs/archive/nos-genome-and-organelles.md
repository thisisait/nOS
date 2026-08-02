# nOS genome — organ boundaries, organelles, and a denser corpus

Authored 2026-07-30, out of the morning review of the 07-30 pulse night. Companion to
`docs/archive/cortex-self-core.md` (doctrine) and `docs/archive/cortex-s3-s4-workflow-set.md`
(the v0.10 release lane). Where those disagree with this file, they win and this is
stale.

**Status (revised 2026-08-02).** Part 0 code LANDED (`67792f0c`) and has converged.
**Part 1 B1 + B3 also shipped** in `4e5e10fc` (the entity/organ schemas + generator)
and `6123c2b8` (L1 field concepts) — the "have not started" line below was written
by the same commits that landed the code and was wrong for three days.

Scope correction while here: B1's table lists **four** codegen targets;
`tools/genome-codegen.py` emits **two** (the Python module_utils mirror and the face
TypeScript contract). The Wing `Entity.php` and the cortex zod contract do not exist.
Parts of B2/B4/B5 and Threads C/D remain unstarted — nothing in them begins without
a separate go.

---


## Part 0 — today, outside the workflow

Two holes, both found by the 2026-07-30 night. Neither waits for the roadmap.

### 0.1 REM-144 — anonymous Traefik API leaks the global password prefix

`vulnerability-scan` (cycle-17 batch-38) found it; I reproduced it by hand from this
session. Unauthenticated `GET`, Host header only:

```
/api/version          → 200   {"Version":"3.6.23","startDate":"2026-07-24T20:34:14Z"}
/api/rawdata          → 200   35 670 bytes — the entire edge topology
/api/http/middlewares → 200   13 middlewares, of which:
      face-edge@file : X-Face-Edge-Token = len 26, begins "kloF"
      wing-edge@file : X-Wing-Edge-Token = len 64, begins "7c62"
```

`X-Face-Edge-Token` is `{{ global_password_prefix }}_pw_face_edge`
(`default.credentials.yml:421`). **It does not leak an edge token — it leaks the
password prefix**, from which every `{prefix}_pw_*` credential in the estate is derived
by construction. `X-Wing-Edge-Token` is 64-hex because `main.yml:1327` regenerates it
away from the prefix template; `face_edge_token` is simply missing from that list,
alongside `bone_secret` and `nos_deploy_hmac_secret` which are both there.

Both tokens exist solely on the premise, written in `middlewares.yml.j2` itself, that
"only Traefik holds this". `X-Face-Edge-Token` is the exact condition under which the
face BFF (`src/hooks.server.ts`) trusts caller-supplied `X-Authentik-*` identity
headers.

**Fixes, in order:**

1. **Take the dashboard off the edge.** Add `traefik` to `traefik_skip_ids`
   (`roles/pazny.traefik/vars/main.yml:119`). `state/manifest.yml:145-153` gives the
   entry both `domain_var` and `port_var`, so `services.yml.j2` auto-derives a
   websecure router with no `authentik@file`, pointed at the Docker host-gateway —
   Traefik proxying around the `127.0.0.1:8082` bind it was meant to be protected by.
   Both gates (`services.yml.j2:35` and `:116`) test `s.id not in traefik_skip_ids`,
   so the id disappears from router *and* service. Fix `vars/main.yml:44`'s comment
   too — "LAN-only via 127.0.0.1 bind" has been false since batch-21.

2. **Stop deriving `face_edge_token` from the prefix.** Added to the `main.yml`
   regeneration group, same guard as its three neighbours.

   **Second half, found while doing it:** `face_edge_token` was also absent from
   `templates/secrets.yml.j2`, so the regeneration alone would have minted a fresh
   token *every run* — churning the middleware render and the face's own env, and
   breaking face auth between renders. Its sibling `wing_edge_token` was in both
   places; this one was in neither. Added to the persistence template too. The
   lesson generalises: "generate it" and "persist it" are two lists, and nothing
   asserts they agree — a Thread D / genome item.

3. **REM-145 rides along.** GHSA-3ccp-42pg-hgv6 (CVSS 4.0 = 7.0, CWE-444 response
   smuggling via proxied CONNECT on the shared keep-alive pool), published 07-27.
   Our `v3.6.23` is the **top of the affected range**; fix is `v3.6.24`. Bump both
   halves — `default.config.yml:1869` and `roles/pazny.traefik/defaults/main.yml:16` —
   per the version-pin-shadow rule.

4. **A gate, so it cannot come back.** SHIPPED as
   `tests/anatomy/test_traefik_exposure_justified.py` (5 assertions). Every routed
   service (`domain_var` + `port_var`, not in `traefik_skip_ids`) that resolves to
   `auth_mode: none` must appear in the new `traefik_auth_none_justification` map —
   a **field**, not a comment. Four entries today (authentik, onlyoffice, rustfs,
   offline_maps), each with a real reason. Three further assertions: the
   fall-through default in `services.yml.j2` must stay `proxy`; justifications for
   services that are no longer routed-and-ungated are rejected as stale; and
   `traefik` must stay in `traefik_skip_ids`.

   **Retro-tested:** removing `traefik` from `traefik_skip_ids` fails two of the
   five — the named regression test *and* the missing-justification test. So the
   gate does catch the exact pre-fix state, which is the only thing that makes it
   worth having. Regenerated from the genome later (§B3).

**Do NOT also set `api.insecure: false`.** `traefik.yml.j2:11` is what creates the
built-in entrypoint on container `:8080`, and `ping: {}` (line 69) rides on it — which
is what `compose.yml.j2:49`'s healthcheck wgets. Turning it off without first
declaring a real ping entrypoint makes the container unhealthy and the STRICT gate
then fails the whole converge. Routing is the correct lever here; a declared ping
entrypoint plus `insecure: false` is a follow-up, not part of this.

**Rotation.** Both edge tokens regenerate in place. The **global password prefix
cannot rotate without a blank** — every service DB password derives from it.

### 0.1a The open question got answered: yes, it was public

Measured 2026-07-30 ~22:40, while the remediation converge was still in its host
phase — i.e. against the pre-fix estate.

Public DNS puts every estate hostname on Cloudflare (`188.114.96.9` / `.97.9`).
Requesting the API **through the Cloudflare edge**, from nothing but the hostname:

```
--resolve traefik.pazny.eu:443:188.114.96.9   /api/version          → 200
--resolve traefik.pazny.eu:443:188.114.97.9   /api/version          → 200
--resolve traefik.pazny.eu:443:188.114.96.9   /api/http/middlewares → 200, 4971 B
      face-edge@file → X-Face-Edge-Token  (len 26)   PUBLICLY READABLE
      wing-edge@file → X-Wing-Edge-Token  (len 64)   PUBLICLY READABLE
```

A first attempt without `--resolve` returned `200` from `192.168.1.64` — the host's
own dnsmasq override answering for `pazny.eu`. That was not the internet test, but it
established a second fact worth keeping: the API was also readable by **any device on
the LAN**, not merely from loopback.

So the disposition is settled. **Treat the global password prefix as disclosed.** The
blank is not optional, and it is the only way to rotate the prefix.

**Exposure windows, from `git log -S`:**

| since | what was public | ends |
|---|---|---|
| **2026-04-27** (`553a2587`, Traefik cutover) | `/api/rawdata` — full edge topology: every router rule, internal backend URL and port | this converge |
| **2026-05-23** (`5f919db0`, SEC-6) | `X-Wing-Edge-Token` — random 64-hex, but forging it makes Wing trust attacker-supplied `X-Authentik-*` headers | this converge; rotate |
| **2026-07-18** (`430e94ce`, face) | `X-Face-Edge-Token` = `{prefix}_pw_face_edge` → **the global password prefix** | this converge; needs the blank |

The prefix leg is therefore **12 days**, not three months — the face landed the
prefix-derived token into an API that had already been open for three months. Neither
half is a defect on its own; the composition is.

**Stated plainly: exposure is proven, exploitation is not.**

### 0.1c The access log says nobody else came

`~/stacks/infra/traefik/log/access.log` — 50 960 lines, JSON. Filtering
`RequestHost` to `traefik.*` returns **32 requests, and every one is accounted for**:

| when (UTC) | what | who |
|---|---|---|
| 07-24 21:16, 22:11 · 07-27 07:42, 08:45, 10:58, 15:46 | `/` → `/dashboard/` | operator, browsing |
| **07-30 02:07** | `/api/version`, `/dashboard/`, `/api/overview`, `/api/rawdata`, `/api/http/middlewares` ×2 | the nightly `vulnerability-scan` — this is REM-144 being found |
| 07-30 18:15 | `/api/version`, `/api/http/middlewares` → **404** | my first probe, against `dev.local` |
| 07-30 18:16 · 20:32–20:33 | `/api/version`, `/api/rawdata`, `/api/http/middlewares` | my probes, loopback then via Cloudflare |

No scan patterns, no unknown paths, no bursts, nothing at an odd hour. **Zero
unexplained requests.**

Two honest limits on that:

1. **The log covers 6 days** — first entry `2026-07-24T20:37Z`, no rotated copies; it
   begins with the current container and everything older died with the previous one.
   The prefix leg opened 07-18, so **6 of its 12 days are observable and clean; the
   first 6 are unobservable.** The topology leg (since 04-27) is almost entirely dark.
2. **`ClientHost` is not usable for attribution here.** One address accounts for
   46 549 of ~51 000 entries across the whole log — a NAT/proxy artifact, not a
   client. The evidence above is the *timeline*, not the source address.

### 0.1d Recalibration — what this actually is

The operator's context changes the grading, and it should: **this is a test machine,
it holds no real personal data, and the password prefix is not reused anywhere else.**

So the correct reading is: a real and publicly-reachable credential exposure, in a
system where those credentials protect nothing of third-party value, with no evidence
of access in the window we can see. It is a **hygiene and process failure**, not an
incident. Concretely:

- **Not** grounds for treating this as a compromise. Nothing suggests one.
- **Still** grounds for the blank — but as planned rotation, not emergency response.
  It was already scheduled for tomorrow; nothing needs to move.
- The lasting value is the *class*: five declarations of "how is this exposed", none
  compared, and a comment that was false for three months. That is Part 1's case, and
  it does not depend on how bad this particular instance turned out to be.

### 0.1e File it as non-reportable, for the exercise

`files/anatomy/wing/bin/breach-file.php` writes `gdpr_breaches` (Art 33/34 + NIS2),
`BreachDeadlines` runs the 24h/72h/1-month clocks, and `breach-deadline-scan` fires
hourly. **No personal data was exposed, so the honest status is `non-reportable`** —
but filing it puts the first real record through a compliance path that has never held
one, which is worth more than the record itself.

**Operator runs it** (a `wing.db` write is not an agent's to make):

```
php files/anatomy/wing/bin/breach-file.php --json=- <<'JSON'
{
  "detected_at": "2026-07-30T02:07:15Z",
  "aware_at": "2026-07-30T02:07:15Z",
  "nature": "Traefik dashboard/API anonymously reachable from the public internet; SEC-6 edge-trust tokens and the global password prefix readable",
  "status": "non-reportable",
  "risk_level": "low",
  "affected_subjects": 0,
  "affected_records": 0,
  "data_categories": "No personal data. Authentication secrets only: X-Wing-Edge-Token, X-Face-Edge-Token (= global password prefix), plus the full edge topology.",
  "likely_consequences": "Had it been exploited: forging X-Face-Edge-Token makes the face BFF trust attacker-supplied X-Authentik-* identity headers; the prefix derives every {prefix}_pw_* credential. Test estate, no real personal data, prefix not reused elsewhere.",
  "measures_taken": "2026-07-30: route removed (traefik_skip_ids), face_edge_token moved off the prefix and persisted, traefik v3.6.24, exposure-justification gate (67792f0c). Prefix rotation via the scheduled blank.",
  "notes": "Non-reportable: no personal data in scope. Exposure proven through the Cloudflare edge; access log shows 32 requests to the host over 6 days, ALL attributable (operator browsing, the nightly scan, remediation probes) — no evidence of third-party access. Log covers 6 of the 12 prefix-exposure days; earlier is unobservable. Windows: topology 2026-04-27, wing token 2026-05-23, prefix 2026-07-18."
}
JSON
```

### 0.1b File it — the estate has the machinery

`files/anatomy/wing/bin/breach-file.php` writes `gdpr_breaches` (Art 33/34 + NIS2),
`BreachDeadlines` runs the 24h/72h/1-month clocks, and `breach-deadline-scan` already
fires hourly. This is exactly the event that machinery exists for, and using it also
exercises a compliance path that has never had a real record in it.

**Operator runs it** (a `wing.db` write is not an agent's to make):

```
php files/anatomy/wing/bin/breach-file.php --json=- <<'JSON'
{
  "detected_at": "2026-07-30T02:00:50Z",
  "aware_at": "2026-07-30T02:00:50Z",
  "nature": "Traefik dashboard/API anonymously reachable from the public internet; SEC-6 edge-trust tokens and the global password prefix disclosed",
  "status": "detected",
  "risk_level": "high",
  "data_categories": "No personal data read directly. Authentication secrets: X-Wing-Edge-Token, X-Face-Edge-Token (= global password prefix), plus full edge topology.",
  "likely_consequences": "Forging X-Face-Edge-Token makes the face BFF trust attacker-supplied X-Authentik-* identity headers, i.e. impersonation of any user; X-Wing-Edge-Token gives the same against Wing. The prefix derives every {prefix}_pw_* credential in the estate.",
  "measures_taken": "2026-07-30: route removed (traefik_skip_ids), face_edge_token moved off the prefix and persisted, traefik v3.6.24, exposure-justification gate added (67792f0c). PENDING: prefix rotation via blank; both edge tokens regenerate on the same run.",
  "notes": "Exposure proven by request through the Cloudflare edge; exploitation NOT evidenced. Windows: topology since 2026-04-27, wing token since 2026-05-23, prefix since 2026-07-18."
}
JSON
```

`affected_subjects` / `affected_records` are deliberately omitted rather than guessed —
fill them from the Authentik user count if the record is ever escalated.

### 0.2 The converge

Seven image pins are ahead of the estate, including REM-137 (CRITICAL, the 36-CVE
Gitea 1.27.0 cluster). Order, per the release lane:

```
ansible-playbook main.yml --tags upgrade -e upgrade_service=gitea    # sqlite backup first
ansible-playbook main.yml                                            # the rest
```

Both need the interactive sudo prompt, so they are operator-run — `! <command>` in
this session puts the output here. Run them from Terminal.app or tmux, not the IDE's
integrated terminal (CLAUDE.md run-hardening: RAM pressure from ~50 containers can
kill a GUI app and take the controlling session with it).

**Verify after:** the three anonymous GETs return `404` from the edge;
`127.0.0.1:8082/ping` still `200` and the container healthy; `traefik.pazny.eu` absent
from `/api/rawdata`'s router list (fetched from loopback); `face_edge_token` in
`~/.nos/secrets.yml` no longer matches `_pw_` and is ≥ 32 chars.

### 0.2a STOP — the brain is not backed up, and a blank is scheduled

Found while checking backup/reload before tomorrow. This outranks REM-144.

**Every backup source on the external disk fails. Every source elsewhere succeeds.
7 / 7 and 7 / 7, no exceptions.**

| result | sources |
|---|---|
| **FAIL** | `dir-gitea`, `dir-gitlab`, `dir-gitlab-config`, `dir-vaultwarden`, `dir-nodered`, `dir-authentik`, **`keap-db`** — all under `/Volumes/SSD1TB/nOS/data/...` |
| ok | `mariadb`, `postgres` (via `docker exec`), `dir-n8n` (`/Users/pazny/n8n`), `wing-db`, `nos-state`, `tofu-state`, `authentik-blueprints` — none on the external disk |

Cause, from `~/.nos/backup.log`, identical every night since at least 07-26:

```
keap-db: sqlite3 .backup of /Volumes/SSD1TB/.../keap/data/keap.db
Error: unable to open database "...": authorization denied
```

**TCC.** Not file permissions — this session's shell reads the same file fine. The
*launchd* context lacks Full Disk Access for `/Volumes`. It is the **same root cause**
as the restic off-site failure already tracked in `active-work.md` under "TCC grant for
/Volumes/SSD1TB", which was filed as a backup-DR-verify nuisance. It is not a nuisance:
`nos_data_root` **is** `/Volumes/SSD1TB/nOS/data`, so "the paths that fail" is very
nearly "the estate".

**The brain, measured** — `/data/keap.db`, **703 MB**, 52 tables:
`relations` 5 084 · `concept_relations` 4 643 · `node_descriptions` 2 500 ·
`node_features` 2 500 · `taxonomy_layout` 2 500 · `taxonomy_nodes_ext` 1 710 ·
`taxonomy_metadata` 1 216 · `knowledge_objects` 322 · `knowledge_imports` 130 ·
`data_tables` 5 · `table_rows` 21 · plus the FTS and vector shadow tables.

Taxonomy and descriptions regenerate from `knowledge/canonical/` via `ingest.mjs`;
embeddings recompute. **The DataTables rows, the import provenance, the review/moderation
history and anything agent-authored since the last KEAP tag do not.** Exact
survives/destroyed classification is being finished separately — do not blank until it
is in hand.

**And the system told us. Six times. At HIGH.**

```
notifications: "Backup FAILED for 7 source(s): dir-gitea, dir-gitlab, ..."
  2026-07-25 · 26 · 27 · 28 · 29 · 30    severity=high
  ntfy_dispatched_at: NULL   mail_dispatched_at: NULL   wing_inbox_read_at: NULL
  total 6, unread 6
```

`backup.sh`'s `notify_result()` works — `notify: HTTP 200` every night. The message
died one hop later, and the reason is exact: it posts `origin_plugin: "backup"`, and
**there is no `backup` entry in the A9 routing table**, so it fell back to
`wing-inbox` alone. All **56** registered plugins route `on_high → [wing-inbox, ntfy]`,
including `backrest-base`, which declares exactly that at `plugin.yml:57`. The host
backup role has no plugin manifest, so its origin string matches nothing, and an
unrouted origin silently loses every channel but the inbox nobody opens.

**Cause confirmed by experiment, not inference.** The backup runs under launchd
(`eu.thisisait.nos.backup.rustfs.plist` → `~/agents/backup-run.sh`). A competing theory
was that host `sqlite3` cannot open a libSQL store at all — KEAP's own
`~/keap/src/knowledge/dump.mjs:11-12` warns *"NEVER host sqlite3, which corrupts the
live libSQL DB"*. **Disproved:** the exact failing operation, run from this session,

```
sqlite3 <keap.db> ".backup /Volumes/SSD1TB/nos-preblank-20260731/keap.db"
   → 704 MB in 2.2 s, no error
```

and `tar` over the failing `dir-authentik` path also succeeds here. Same paths, same
binaries, same file — different execution context. It is **Full Disk Access on the
launchd context**, exactly as the `/Volumes`-vs-not split predicted.

### 0.2b The rescue set — taken 2026-07-31, before any blank

`/Volumes/SSD1TB/nos-preblank-20260731/` — a sibling of `nOS/data`, outside every
entry in `_blank_dirs` *and* outside `_uninstall_source`, so it survives even
`remove=all`. Carries `README.md` + `SHA256SUMS`.

| file | size | why it was at risk |
|---|---|---|
| `keap.db` | 704 MB | destroyed by blank; the `keap-db` source has **never once** succeeded |
| `wing.db` | 91 MB | `~/wing/app` is in `_blank_dirs`; nightly backup works but is 03:00-old |
| `openclaw.tar.gz` | 53 KB | `~/.openclaw` — identity, state, attestations; in **no** backup list at all |
| `nextcloud-data.tar.gz` | 145 MB | `tenants/pazny/shared/nextcloud/data`; destroyed, and deliberately excluded from backup |

**Verified:** all **49** non-vector tables compared live-vs-snapshot, **0 mismatches**
(`relations` 5 084 · `concept_relations` 4 643 · `node_descriptions` 2 500 ·
`knowledge_objects` 322 · `data_tables` 5 · `table_rows` 21 · `promotions` ·
`lint_findings` · `curator_runs` · `curator_visits` · `knowledge_imports`).
`wing.db`: `events` 40 334 · `remediation_items` 143 · `notifications` 25.

**Caveat, stated rather than buried:** `pragma integrity_check` cannot complete under
stock sqlite3 — `unknown function: libsql_vector_idx()`. Full structural validation
needs a libSQL-aware tool. `.backup` copies at page level and every row count matches
exactly, so the data is believed faithful; the vector index regenerates via
`keap-embed-sync` in any case. **The restore path has never been exercised.**

### 0.2c What a blank actually destroys — read before running it

`remove=data` deletes `_blank_dirs` (`tasks/removal-set.yml:74-231`). Five things in
that map are not what one would assume:

1. **`~/.nos` is NOT deleted** — only `secrets.yml` (`blank-reset.yml:290-293`).
   `state.yml`, `events-fallback.db`, `keap-consolidate-state.json` and **the
   `cortex-corpus-diff.json` agreement ledger** all survive. That is the failure mode
   the harness documents against itself at `cortex-corpus-diff.py:1273-1311`: *"the
   store was REBUILT under a surviving ledger"* → `feeder-ledger-ahead-of-store`.
   **Expect the streak to void and a night or two of noisy findings.** Not a defect —
   but decide deliberately whether to reset the ledger with the store.
2. **wing.db is destroyed, audit chain and all.** `blank-reset.yml:69-70` states
   *"Audit-log rows in wing.db are NEVER cleared (regulatory requirement, enforced
   inside the loader)"* — true of the **plugin post_blank hook**, and then
   `wing_app_dir` is deleted wholesale at `removal-set.yml:229`. The guarantee holds
   at the layer that states it and is silently void one layer down. A hash chain
   cannot be recomputed; this contradicts a shipped gov-compliance control and belongs
   in `hidden_fees`.
3. **DataTables come back empty even of demo content.** `deploy/seed-fixtures.mjs` is
   marker-gated on `~/keap/.fixtures-seeded`, which **survives** the blank, so the
   re-seed is skipped.
4. **`tenants/pazny/shared/nextcloud/data` (148 MB) is destroyed.** The "user files
   survive a blank" doctrine covers `tenants/<slug>/users/**`, not `shared/**` —
   `nextcloud`, `kiwix`, `maps` and `jellyfin` are all in `_blank_dirs`.
5. **Changing the password prefix at the prompt auto-promotes `destroy_state: true`**
   (`main.yml:1124-1131`), regenerating APP_KEYs, encryption keys and JWT secrets
   alongside the passwords. The Bluesky PLC rotation key is preserved regardless. This
   is *intended* and announced — and it is precisely what a REM-144 prefix rotation
   wants. Just know that pressing a new prefix does more than change passwords.

And one that makes the whole thing worse: **the pre-wipe backup prints a green banner
whether or not it worked.** `tasks/pre-wipe-backup.yml` runs `~/.nos/backup.sh`, whose
`run_keap_db` returns 0 on failure, so *"✓ copy #1 refreshed"* and *"✓ off-site
snapshot committed"* appear over a bucket containing no KEAP data. Fourth instance of
the class tonight, in the most dangerous possible place.

**Actions, in order, before any blank:**

1. ~~Snapshot the brain~~ — **DONE**, §0.2b.
2. **Fix the routing origin** — `roles/pazny.backup` has no plugin manifest, so its
   `origin_plugin: "backup"` matches nothing and A9 falls back to inbox-only. Give it
   an entry (or emit `backrest-base`) so a failed backup reaches ntfy like all 56.
3. **Fix the launchd context** — grant Full Disk Access to `~/agents/backup-run.sh`'s
   interpreter, or move host-path sources onto the `docker exec` path that is *why*
   `mariadb` and `postgres` are the only DB sources that never failed.
4. **Make `run_keap_db` propagate its failure** so the pre-wipe banner can go red.
5. **Then** blank.

**The pattern, third instance tonight.** The drift hook parsed nothing and exited 0;
its notification 401'd and it exited 0; the backup failed 7/7 and reported success at
the process level while its alarm went to a room with no one in it. Thread D's rule —
*a step that cannot do its job must not exit 0* — now needs a second clause: **and the
alarm must reach somebody.** A HIGH that only ever lands in an unread inbox is not an
alarm, it is a log line.

### 0.3 Also today, no code

- **Reconcile the security queue.** DONE (`4e19d1b2`). The nightly scan writes into
  whichever checkout it runs in, and batch-38 (REM-144…148) existed only as an
  uncommitted working-tree change in the main checkout — one `git checkout` from
  being gone. *(A correction to the first draft of this section, which claimed two
  divergent **uncommitted** copies: the worktree was clean. The files differed
  because the worktree sits on an older commit. The exposure was real; the
  description was not.)* Still open, and now a Thread D item: decide where the
  scan is allowed to write, deterministically, instead of "wherever it ran".
- **Correct the docs that told us we were fine.** `docs/active-work.md:85-87` and
  CLAUDE.md both claim **"0 CRITICAL pending"**; the live queue has two (REM-137,
  REM-144). Also stale: `cortex-self-core.md:388-393` (sparsity figures) and
  `keap-fable-ontology-review.md` ("PREPARED (not applied)" — it was applied).

---

## Part 1 — the genome

### The problem, in your words

> *Není problém to, že je kód v jiném jazyce a u jiného orgánu, ale to, že nemá
> společného jmenovatele.*

That is the correct diagnosis, and it is measurable. Today the estate has no common
denominator, and the same law is restated by hand in every organ that needs it:

| law | restated in | worst symptom |
|---|---|---|
| RBAC tier → group | **7 places, 5 languages** | `superset_config.py.j2:52-55` reads `.admin` as a dict against a list-of-dicts — a live shape mismatch masked by `\| default()` |
| GDPR Art-30 | 4 declarations | `plugin.schema.json` wants `eu_residency`, `app.schema.json` wants `transfers_outside_eu` — inverse spellings of one fact; `nos_gdpr.py` exists only to paper over it |
| tier visibility enum | 4 copies | `state/keap-tables/*.table.yml` consumes it as an unvalidated string; the test checks only that the key exists |
| face ↔ KEAP contracts | hand-mirrored, **no gate at all** | already drifted: face has 11 `ColumnKind`s to KEAP's 12, every constraint dropped |
| **exposure / gating** | **5 places** | **REM-144** |

**Correction to an earlier draft of this section.** It claimed there was "not one
`$ref`, `allOf` or `$defs`" in `state/schema/` — that was wrong, and it was cited as
evidence, so it gets fixed rather than quietly dropped. Measured:

| | count |
|---|---|
| `$ref`, intra-file (`#/definitions/…`) | **18**, across `manifest`, `migration`, `upgrade` |
| `$ref`, **cross-file** | **0** |
| `allOf` | **0** |
| `$defs` | 0 (draft-07 `definitions` is the idiom here) |

The real gap is narrower and the argument is better for it: **the estate already knows
how to factor a shape and `$ref` it — it has simply never done so across a file
boundary.** `migration.schema.json` reuses `predicate` eleven times inside itself and
shares nothing with `upgrade.schema.json`, which defines its own `step`. No schema
composes another; there is no base anything inherits from.

So the genome is not introducing an unfamiliar idiom. It is taking the one already in
use and applying it one level up. The first draft of this plan proposed adding a
`sensitive` boolean instead — a fifth uncoordinated copy of the same law. Rejected,
correctly.

The exposure row is the one that just cost us. "How is service X reached and what
gates it" is declared in `state/manifest.yml` (a router exists), `traefik_auth_modes`
(what attaches), `traefik_skip_ids` (whether to route), the plugin's `authentik:`
block (whether a provider exists to attach), and `authentik_app_tiers` (who may pass).
Nothing compares them. For `traefik` they disagreed, and the only thing tying them
together was a comment that had been wrong for months.

### Corollary: what is not an organelle is not wired — silently

*"backup je taky samozřejmě organella."* Correct, and the reason REM-144's sibling
defect happened at all.

Every wiring channel in the estate is driven by plugin manifests: A9 notification
routing, the GDPR Art-30 register, Loki labels, Traefik exposure, the tier ladder,
Pulse job registration. A component **with** a manifest gets wired. A component
**without** one does not get *wrong* wiring — it gets **no** wiring, and the fallback
looks exactly like a decision somebody made.

`roles/pazny.backup` had no manifest. So `origin_plugin: "backup"` matched nothing,
A9 fell through to inbox-only, and six nights of `Backup FAILED` at severity=high
went unread while all 56 manifest-carrying components routed the same severity to
ntfy. Nobody chose that. It was the shape of the hole.

**Measured coverage: 58 of 75 `pazny.*` roles carry a manifest. Seventeen do not** —
and the list is not the harmless tail one would hope for:

| no manifest | why it matters |
|---|---|
| **`bone`** | the organ that **receives** every notification, and cannot declare its own |
| **`pulse`** | the daemon that **runs** every scheduled job, itself unscheduled and unrouted |
| `state_manager`, `apps_runner`, `acme`, `iiab_terminal`, `opencode` | runtime components with real surface and real failure modes |
| `_common_tasks`, `dotfiles`, `mac.*` (3), `linux.*` (5) | installers — arguably out of scope, but that should be a *declared* exemption, not an absence |

Bone and Pulse being outside the model is the sharpest version of the problem: the
notification bus and the scheduler are the two things everything else reports
*through*, and neither is describable in the language the estate uses to describe
everything else.

This is why the genome's organ layer (§Layer 2) is not optional polish. Until every
runtime component is in the model, "wired correctly" is unfalsifiable — you cannot
audit a set you cannot enumerate. **A gate belongs here too:** a `pazny.*` role with
runtime surface must either carry a manifest or appear on an explicit, justified
exemption list — the same shape as `traefik_auth_none_justification` in Part 0.4,
for the same reason.

`backup-base` is the first one written back (2026-07-31), and it is a good template
precisely because backup has no port, no UI and no OIDC: what it declares is the
irreducible core — an owner, a severity contract, a schedule, and a blast radius.

### What the common denominator has to do

Not "be one language" — the estate is deliberately polyglot and will get more so:
PHP in the wing, TypeScript in the cortex organ and face, Python in Bone and the
Ansible modules, a **Rust brain** and a **Python digestion** on the horizon. The
denominator's job is to make those five agree without any of them being authoritative.

Three things, and they are separable:

1. **What an organ is** — its boundary. Declared once, per organ.
2. **What an entity is** — the base nOS entity and the organelles inherited from it.
   Data facets only.
3. **How organs talk** — the wire contract, versioned and gated on both ends.

And a fourth that cuts across all three: **everything gets a taxonomy anchor**, so an
organ, an entity kind and a service are all addressable from cortex-lang. That is what
turns "plugin-like wiring between all services" from a metaphor into an address space.

### The pattern has a name, and the operator already wrote it down

From the operator's own `TechNosIdeas` table (2026-07-31), before reading any of
this: *"nos-ecs hydrator — Entity-Component-System hydrator … obecně potřebujeme
hydrátory entit z ext. systémů na naše entity."*

That is the design, named better than this document had named it:

| this plan says | ECS says | which is clearer because |
|---|---|---|
| base entity + facets | **entity + components** | components compose; "facets" sounds like views of one object |
| organelle | **archetype** (a fixed component set) | says outright that the kind IS its component set |
| "organelle through a gate" for external systems | **hydrator** | names the missing verb: how foreign data BECOMES an nOS entity |

The third row is the one worth stealing. This plan kept saying "core generated,
edge through a gate" without naming what happens at the gate. It is hydration:
an external record arrives, a hydrator maps it onto the entity's components, and
from that point it is an nOS entity like any other — indexed by the cortex,
governed by the compliance component, gated by the access component.

That also answers the two-languages question more cleanly than "no transpiler"
did. A hydrator is written in the FOREIGN system's language, because that is
where the foreign shape is understood; what crosses the boundary is a hydrated
entity validated against the genome. Nothing needs to be transpiled because
nothing foreign crosses — only entities do.

**No renaming yet.** `ent:` is already scheduled at S5 and the word "organelle"
is the operator's; this records that ECS is the same shape under a
better-established name, so the vocabulary can converge deliberately rather than
by accident. The `hydrator` concept, though, should be adopted now — it is the
name for a piece that currently has none.

### The organ boundary

An organ declares:

| field | meaning | precedent that already exists |
|---|---|---|
| `identity` | name, runtime, where it runs (launchd / docker / systemd) | plugin manifests, `state/manifest.yml` |
| `store` | the store it **exclusively** owns | `assertOwnStore()` + `.cortex-store.json` marker — already enforced for the cortex organ, and its e2e asserts it against the **filesystem**, not the server's own account of itself |
| `surface` | routes exposed, and per route: `route` / `gate` / `justification` | **this is the `access` facet — REM-144 lives here** |
| `consumes` | other organs' contracts, at a declared version | `requires.plugin` in plugin manifests; `contracts.selfmodel: 1` handshake |
| `taxonomy` | its anchor node | `ent:`/`org:` namespaces, per `cortex-self-core.md` §6b |

The point of the table is that **none of these five is greenfield**. Each exists as a
working one-off in exactly one place. The genome generalizes four proven mechanisms
rather than inventing a framework.

### The three layers, and what each is written in

**Layer 1 — entity & organelle shapes: JSON Schema, with composition.**
`state/genome/entity.schema.json` declares the base entity via `$defs`; an organelle
is a schema that `allOf`-composes it and adds its kind. Four facets:

- `access` — reachability *and* gating as one fact (route, gate, provider, tier)
- `compliance` — Art-30, **one** spelling, superseding the two divergent copies
- `cortex` — indexed or not, which fields form the embedded body, sensitivity exclusions
- `face` — render hints, today scattered across `hub_card`, table defs and Wing columns

JSON Schema because it is already the estate's format, already gated by the
`contracts-drift` CI job, language-neutral, and `$ref`/`allOf` *is* the inheritance you
asked for. First organelles: `organelle/data-table`, `organelle/row`,
`organelle/service` (which a plugin manifest already half is).

**Layer 2 — organ boundaries: one manifest per organ**, same directory, validated
against `state/genome/organ.schema.json`. This is the layer JSON Schema alone cannot
express, because it describes *interfaces*, not data.

**Layer 3 — the wire.** Generated from layers 1+2 into each runtime, plus a
conformance gate on **both** ends. Per `docs/doctrine/cross-repo-contracts.md`:
*"Symmetry is the whole design. A gate on one side only makes that side the authority
and the other side the supplicant."*

### L1 shipped first — the research verdict, and what it cost to widen

Ordering research (2026-08-01) asked which of the three layers to build first.
**Verdict: L1**, and the adversarial pass did not shake it — *"I found no evidence L2
or L3 first is better, and the primary rationale survives intact."*

The rationale is asymmetric recoverability. Machine re-processing is automatic and
bounded: `pendingEmbeddings` diffs `contentHash`, so anything embedded re-embeds itself
without a human. **The human declaration of what a column MEANS has no such path** —
nobody re-derives it later, and every row captured before it is captured without it.
Only L1 carries a cost that delay destroys. L2's and L3's proposed first moves both
force a full corpus re-embed and buy nothing that waiting loses.

**What the adversarial pass DID kill was the first commit as scoped, for a reason
neither side had seen: a table's columns were immutable for its lifetime.**
`data_tables.schema_json` had exactly one writer — the INSERT in `createTable` — and no
`UPDATE` of it anywhere; `PATCH /api/tables/:id` handled visibility only, and
`POST /agent/v1/tables` early-returned on an existing slug. The only change path was
DELETE → `dropTable`, which deletes `table_rows` **and** `table_row_history`.

So the originally-scoped commit — add `concept:` to the ~76 columns in
`state/keap-tables/*.table.yml` — would have been a **no-op on every converged
install**. Git changes, the offline gate goes green, the database keeps the
concept-less schema, and nothing anywhere is red. That is the fourth instance in two
days of the same class: a gate that passes while delivering nothing.

The commit was widened accordingly, and the widening is the substance:

- **`updateTableSchema()`** — the reconcile write path that did not exist. Additive and
  relabel only; a dropped column or a changed `kind` is refused, because rows already
  hold those values. Re-renders the card and the projected row objects, so the corpus
  cannot go on describing the old columns.
- **The agent create reconciles** instead of early-returning "exists", and the nOS
  seeder lost its `when: probe.status == 404` gate. A 409 now fails the converge with
  the authoring diagnosis rather than passing silently.
- **The `onto1:` digest change was dropped from this commit.** Adding a `c\t` line kind
  would have put the runtime out of agreement with a normative reference
  implementation, six fixtures and a conformance runner while the digest still read
  `onto1:` — the spec's own §0 calls that failure *"silent, total, and indistinguishable
  from a genuine ontology change."* It is a contract revision, and it will be done as
  one or not at all.

**One honesty correction, stated so it is not quietly inherited.** The row body renders
`Label [concept]: value`, and that does **not** make embeddings concept-aware: one
vector covers the whole body, which is truncated before embedding, so a shared bracket
token among thousands of characters is diluted to nothing. Two rows in different
languages sharing a concept stay as far apart as before. What the token actually buys is
the **lexical** leg — `lifecycle.status` is a literal FTS/BM25 term, so "which rows
anywhere carry a lifecycle status" becomes answerable across tables that label the same
meaning five different ways — plus the membership gate that keeps the vocabulary closed.
The vectorial complaint is **not** addressed here; it is what L2's per-concept slots are
for.

**The ordering trap, confirmed.** L2 adds slots per column and L3 adds
`foreign_field → (slot, concept)` per column — both through the same write-once channel.
Before `updateTableSchema` existed, rows captured between layers would have had to be
**destroyed and re-entered** to be re-declared, not merely re-processed. The reconcile
path is what makes the remaining two layers additive instead.

**The vocabulary earned its keep on first contact.** Mapping the 76 live columns hit two
collisions under the one-concept-per-table rule: `entry_url` vs `repo_url`, and `organs`
vs `data_stores`. Both were real — "where it runs" is not "where its source lives" —
and produced `net.repo` and `graph.stores`. A free-text column would have absorbed both
silently.

### Why not protobuf / an IDL, and why not a transpiler

An IDL would give real cross-language codegen, and it is the obvious answer. It is
still the wrong one here, for two reasons. It cannot carry the facets — compliance,
tier, cortex indexing, taxonomy anchor are the *whole point*, and in protobuf they
become comments. And it puts a toolchain into five runtimes, one of which (Rust)
does not exist yet, to solve a problem we do not have: we are not optimising wire
bytes, we are trying to stop the same sentence being written five times.

What we should steal from it: **additive-only evolution and an explicit version
handshake.** Both already have a precedent — `contracts.selfmodel: 1` on
`/agent/v1/health`.

A transpiler is likewise the wrong shape, and the estate has already answered this
three times without one:

- KEAP (TS) ↔ Wing (PHP) agree on opcodes via a **hash-compared `cx1:` registry** plus
  a boot gate — Wing *refuses to start* if a published opcode lacks a handler
- error shapes are byte-identical, enforced by
  `tests/anatomy/test_cortex_phase2_uniform_error.py` — **a Python test asserting a PHP
  service matches a TypeScript service's JSON shape**
- `shared/contracts/cortex.ts` is lifted **verbatim** with a provenance header and a
  vendoring gate

The pattern underneath all three is **regenerate-and-diff**, which already runs in four
places (`contracts-drift`, `spine-render.mjs --check`, `lift-xrefs` +
`git diff --exit-code`, `gdpr-dpa-register.py --check`). One declaration, N emitted
artifacts, CI red on drift. Not new machinery — existing machinery, new source.

**The design's own test:** adding a fifth runtime must cost *one emitter*, not a
renegotiated contract. If a Rust brain requires reopening the schema, the genome
failed.

### The one thing that may never be inherited

Both `nos-cortex-lang.md` §2 and the Wing executor §2 state that a capability **must
not be addable by data**. So the organelle splits along the line the language already
draws:

- **facts about an entity** → data, declared once, inherited, generated everywhere
- **what may act on an entity** → code, per runtime, hash-compared, never inherited
  from a manifest and never addable by declaring it

That is exactly the shape you chose — *core generated, edge through a gate*. Our organs
consume generated clients; an external system satisfies the same contract at runtime
through the **Wing executor**, already designed as a capability boundary with
three-axis scoped tokens (`verbs` / `namespaces` / `tenants`).

### The strongest objection, stated fairly

*A generator emitting five languages, gated by drift CI, is a lot of machinery for a
repo that has not shipped its first stable release — and the risk is that the generator
becomes the thing we maintain instead of the estate.*

Real, and it does not win. The machinery is not new (`contracts-drift` already
regenerates and diffs three artifacts across Python and PHP), and the alternative is
not "no machinery" — it is seven hand-kept copies of the tier map, four spellings of
Art-30, and the five-way exposure split that produced REM-144. We already pay the
maintenance; we pay it in incidents instead of in CI.

The mitigation is scope discipline: **B3 migrates one facet**, B5 defers cells
outright. If the generator has not paid for itself after `access`, that is a real
signal and we stop.

---

## Part 2 — threads

Sequencing. Nothing here starts without a separate go.

```
Part 0 (today) ──→ v0.10-beta tag
                       ↓
        A hygiene ─────┐
        B genome       │
        C corpus       ├──→ KEAP tag → pin bump → converge → one night
        D pulse audit ─┘
```

One KEAP tag, one pin bump, one converge — required by C2, and it collapses three
converges into one.

**The streak is not a constraint after the tag.** It was a release gate; it is met at
3. Afterwards it is a regression detector, and B2/C may deliberately zero it once with
a ledger note. The earlier draft treated it as sacred; withdrawn.

### Thread A — hygiene

**A1. The KEAP row-upsert `slug` bug.** `server/agent.ts:731-733` — strip `slug` from
`values` before `upsertRow` **only when** the schema declares no `slug` column.
Unconditional stripping breaks the face config tables, whose `slug` is a real readable
cell (`agent.ts:718-719`). Do **not** reserve `slug` in `validateRowValues`
(`shared/contracts/table.ts:131`) — shared with `/api/tables`, the rustfs driver and
the UI. Human path unaffected. While in the file: `rowSlug` uses `validSlug` (allows
`.`) where the human path uses `assertRowId` (does not) — two id charsets, one column.

**A2. Anchor the seeded fixtures.** `keap-lint` gave an honest verdict on our own test
data: of 27 new findings, **26 are `orphan-object` (info)** — an exact 1:1 match to the
26 fixtures — each *"has no `[[taxonomy]]` anchor — invisible in the universe
(panel/search only)"*. The seeder writes only `fixture`/`title`/`date` frontmatter, so
not one fixture links into the taxonomy. They satisfy the corpus-diff clauses (real
`fs:` objects, 317/317) but exercise only the **flat** corpus, never the
taxonomy-linked path — which is the path Thread C densifies. Add `[[anchor]]`s to
`tools/cortex-seed-fixtures.sh`, `--purge` and re-seed on a converge day.

**A3. `keaptable:business-partners` does not resolve** — the 27th new lint finding,
`broken-content-ref`, medium, unrelated to the fixtures. Diagnose whether the table was
renamed, disabled, or never created.

### Thread B — the genome, built

**B1. Layers 1+2 and the generator.** `state/genome/{entity,organ}.schema.json`, plus
`tools/genome-codegen.py` emitting:

| target | artifact | consumer |
|---|---|---|
| zod | `shared/contracts/entity.gen.ts` | KEAP + the vendored organ |
| TS types | `files/anatomy/face/src/lib/contracts/entity.gen.ts` | face — replaces the mirror that is drifted today |
| PHP | `files/anatomy/wing/app/Contracts/Entity.php` | Wing |
| Python | `files/anatomy/module_utils/nos_entity.py` | the loader, apps_runner |

Gated by regenerate-and-diff inside the existing `contracts-drift` job
(`.github/workflows/ci.yml:267-312`) — it already installs Python 3.13 + PHP 8.5 and
does exactly this for three other artifacts. No new CI infrastructure. Cross-repo
symmetry per `cross-repo-contracts.md`: golden fixture in nOS, consumer gate in KEAP,
version handshake via `/agent/v1/health` `contracts.entity: 1`.

**B2 is now the highest-value item in Thread B, and the reason is a live
workflow, not an argument.**

The operator's `TechNosIdeas` table (created 2026-07-31) is the intended capture
surface for exactly the loop this whole estate exists to serve: jot an idea or a
link in the face, have an agent research it, integrate the result. Its `status`
column is a full pipeline — `new → unchecked → checked → planned → solved →
applied → refused` — so it is a workflow, not a scratchpad. *"tuto workflow
budeme využívat dost… k tomu je nos/face/cortex."*

**The first link of that loop is broken today.** The cortex holds ONE object for
that table (`table-d237570c-…`, type `table`) and knows nothing about its six
rows; the table's `graph` metadata is `null`, so nothing materialises. An agent
searching the cortex for "GeoLibre" or "secrets store" finds nothing. I only read
those rows because the operator said the table existed and I opened SQLite
directly — which is the "vibing on the OS, not on nOS" path the estate's own
doctrine forbids, and the exact thing `syncRows()` exists to make unnecessary.

So B2 is not "materialise rows so Grafana looks nicer". It is the difference
between the capture workflow working and not working. It moves ahead of B3's
remaining half.

**B2. `syncRows()` — the first organelle, and it is already designed.**
`table-graph-metadata-spec.md` §3.1 carries ratified decision **D3 = materialised**;
`graphMetaSchema` (`shared/contracts/table.ts:291-337`) already accepts
`mode: 'card' | 'rows'` with a full `superRefine`; `server/graph.ts:196-199` states the
gap outright. The work is one function beside `syncCard` (`server/tables.ts:191-233`),
same triggers: `id = table-<slug>:row-<idColValue|rowUuid>`, `type = node.kind`,
`title = row[labelColumn]`, body = compact cell rendering, `visibility = t.visibility`,
`links` via `extractRefs`, `frontmatter = {table,row}`.

Everything downstream is free: `allSources()` (`server/embeddings.ts:63-85`) already
enumerates `db.getObjects` under kind `object`; `hybridSearch` rebuilds FTS from the
same list; `/explore` renders `getVisibleObjects`, which already applies the tier
ladder. Ratify `ROW_OBJECT_CAP` (spec proposes 500, D5-unratified) and reject at enable
time rather than truncating.

**The nightly diff survives it — verified.** `adjudicate_objects` classifies a
KEAP-only object by `if not oid.startswith("fs:")` → `not-a-mirror-row`, withdrawn from
the fs clause. It does *not* key on `type == 'table'`, so row-objects land in the same
neutral class automatically. One follow-up: fold `table-*` and `table-*:row-*` into a
single counted line (as `organ-docs-corpus` already is), or 500 rows means 500 benign
findings. Harness change — land it after a streak completes, never during one.

**B3. Collapse `access` — the exemplary organelle.** RBAC is the right first
organelle, and its exposure half is what REM-144 proved was ungoverned.

*Exposure half, first:* Part 0.4's hand-written gate is regenerated from the schema
instead — every routed service declares `access.route` and `access.gate`
(`none|forward_auth|oidc|header_oidc`), and `none` requires `access.justification`, a
field rather than a comment. `traefik_auth_modes` and `traefik_skip_ids` become
**generated** from those declarations. The gate additionally asserts that a
`forward_auth`/`header_oidc` declaration has a matching Authentik provider in the tofu
registry — the "auth: proxy without a registered provider returns 404" trap that
`vars/main.yml:147` currently warns about in prose.

*Tier half:* generated artifacts replace copies 1–4 (KEAP `rbac.ts`, the vendored organ
copy, Wing's `BasePresenter` constant, face's mirror); `authentik_rbac_tiers` becomes
the declared source with its shape reconciled, fixing the Superset dict-vs-list
mismatch by construction; `state/keap-tables/*.table.yml` `visibility:` becomes
validated.

Compliance, cortex and face facets follow later. Declaring four and migrating one keeps
this reviewable.

**B4. Rows in Grafana — one composition plugin.** Stated plainly because it changes the
estimate: **`observability:` in plugin manifests is 95 % dead metadata.** 41 manifests
declare it; the only atom with a live consumer is `loki.labels.stack`, read by
`_plugin_stack()` (`load_plugins.py:405-416`). `metrics_of_interest`,
`observability.grafana.dashboards`, `alerts`, `prometheus.scrape` — zero consumers
each. Do not plan against it. The path that works is `grafana-wing`'s: mirror it as
`grafana-keap`, `requires.plugin: [grafana-base, keap-base]`, one
`frser-sqlite-datasource` template, mounted read-only. ~60 lines copied from
`plugins/grafana-wing/plugin.yml:60-74`.

**B5. Cells — deliberately not yet.** There is **no per-cell identity in the store**: a
row is one JSON blob in `table_rows.data` read via `json_extract`; history is a
whole-row snapshot per op. The only cell-level addressing is
`table_row_refs.column_key`, and only for `rowRef`. Cells need a new identity scheme
*and* a new history model, with no ratified design. Rows first.

**B6. Two live defects found while surveying.**

- **The `observability.scrape` DAG edge is dead.** `topological_order`
  (`load_plugins.py:203-206`) adds an implicit `prometheus-base` dependency for any
  plugin declaring `observability.scrape`, but reads a *top-level* `scrape`; the only
  declarer nests it as `observability.prometheus.scrape`. Fires for 0 of 41. Fix the
  path or delete the edge.
- **`plugin-wiring-capabilities.md:27` is stale** — records `ui-extension.hub_card` as
  "(none yet)", but `wing-base/plugin.yml:116-118` harvests it, `:136-139` renders
  `hub-cards.json`, and `HubCardRepository.php:8-11` reads it. The document whose whole
  job is truth about live-vs-forward is wrong on one row.

### Thread C — LLM corpus densification

Yes, and it breaks nothing **if it goes through git and lands after the tag**.

**C1. The two branches you named are the sparsest — measured.**

| branch | nodes | authored (`ext`) |
|---|---:|---:|
| `11.01` **File Formats** | **6** | **0** |
| `11.02`–`11.05` (Compression, Encryption, Backup, Recovery) | 5 each | 4 each |
| `02.02` **Computer Science** | 94 | **10** |
| ↳ AI / Security / Databases | 6 each | 0 |
| ↳ Computer Graphics | **1** | 0 |

`11.01` is pure spine — the 2026-07-26 wave filled `11.02`–`11.05` and skipped it
because it already had five seed children, so it never read as "empty". In a knowledge
base *about preservation*, File Formats is the weakest branch in the corpus. Also
sparse: `01.05` Astronomy (6/0), `02.03` Logic (4/0), `03.01` Engineering (51/0).

**C2. The route — git SoT, not the API. This is the hard constraint.** Adding nodes
only via `/agent/v1/taxonomy/propose` makes KEAP's node-id set diverge from the
organ's → `clauses["taxonomy"]` False → **`agreeStreak = 0`**, every node reads as
`keap-ahead-of-pin`, and 300 proposals means 300 moderation rows. The organ never reads
KEAP (`cortex-store.ts:31-32`). So:

1. author into `knowledge/canonical/<L0-dir>/<L1>.json`
2. `node knowledge/lint.mjs` — `en` 20–2000 chars, `cs` ≤ 2000, no Cyrillic,
   `level == id depth`, global id uniqueness
3. `node knowledge/roundtrip.mjs` — ingest ∘ dump byte-identical
4. commit, tag KEAP (**the same tag as A1 + B2**)
5. bump `keap_repo_ref` + `keap_version` (both halves)
6. **re-vendor** into `files/anatomy/cortex/knowledge/canonical/`
7. converge — rebuilds KEAP via `ingest.mjs`, `store:materialise` re-ingests the organ

Steps 6–7 are not separable: the referee is literally the set of node ids in this
checkout's `canonical/` tree (`cortex-corpus-diff.py:598-624`). Skip the re-vendor →
`both-behind-pin`, parity flips to NOT PINNED. Skip KEAP → `keap-ahead-of-pin`, clock
zeroed.

Two traps: **`ingest.mjs` wipes and re-inserts a whole L1 subtree per file** — a partial
patch deletes every `11.01.*` node not in it, including layout points, so files must be
authored complete. And **never touch `spine/`** — L2+ `ext` nodes append safely
(`appendExtNodeToLayout`); a spine edit re-bakes positions and breaks the pinned
`onto1:76d1f3ad728b382b` gate. `11.01.*` and `02.02.*` children are L3/L4, so safe.

**C3. Scope.** Two files, authored complete, ~100–130 new `ext` nodes: `11.01.json`
(5–8 children under each of Document / Image / Audio / Video / Archive, ≈30–40) and
`02.02.json` (depth on AI, Security, Databases, OS, Networks, SE, Graphics, ≈70–90,
matching the shape `02.02.11` established). Each node needs
`id / level / parentId / name / zone / ordinal / kind: ext / en / cs`. The `en`
description is the real work and the real value — it is what gets embedded and what the
router answers from. House style: `files/anatomy/agents/curator.yml`.

The curator agent does **not** do this — P0 emits `desc`-kind proposals only;
`node-edit`/`node-delete`/`relation` kinds are unbuilt (`promotions.ts` `decide()`
dispatches only `node`, `desc`, `brief`).

### Thread D.0 — the general fix the two audits converged on (2026-08-01)

Both sweeps ended at one sentence: **a step records its own outcome as the fact of
having attempted, and the record is written by the attempting code.** `dispatched_at`
stamped by the sender. `status=scanned` stamped by the scan runner. `status_append`
skipped by the source that vanished. The GREEN verdict printed by the script that
invoked the agent. Backfilling a gate's expected value in the same commit as the code
is the degenerate case, and it cost a converge on 2026-08-01.

**175 sites cannot each grow an assert.** The one change that makes the family
impossible:

1. **Success markers are written by a READER that observes the effect** — the ntfy
   2xx, the provider actually returned by a `GET`, the admin row actually present —
   never by the code that attempted the work.
2. **Absence must be representable.** Nearly every finding is a *missing row* reading
   identically to a *never-configured* row. An expected-set derived from the same
   declaration the work is derived from turns silence into a diff.

**Shape, and the engine already exists.** `files/anatomy/module_utils/load_plugins.py`
carries `_replay_api_sequence`, `_http_call` with `expect_status`, `_docker_exec`,
`_docker_inspect` with `expect_state`, `expect_substring`. That is the whole reader
vocabulary the five hand-written loud verifies use today. What is missing is that it
**cannot fail**: `_replay_api_calls` records ERRORS only on a raised exception and
`_docker_exec` returns `rc` into a dict nothing inspects — so a hook step returning
rc=1 is indistinguishable from success, the same defect one level down.

- `files/anatomy/plugins/<svc>-base/hooks/verify.yml`, same schema as `post_compose`,
  with one added semantic: **every step is an assertion**; a mismatch appends to
  ERRORS and exits non-zero. No `no_log` permitted in this file.
- ~40 LOC in the loader, which also un-swallows the EXISTING hook steps (e.g.
  `nextcloud-base/hooks/post_compose.yml:64`'s `allow_local_idp`).
- `tasks/stacks/verify-effects.yml`, tagged `['verify', 'always']`, so
  `--tags verify` runs against a live host in ~20 s without a converge.
  `-e nos_verify_soft=true` downgrades to warnings for a deliberately-degraded host.

**The expected set comes from declarations that already exist** — `authentik.mode`,
`authentik.post_setup`, `requires.variables` containing `*_admin_user`,
`manifest.oidc` — so nobody maintains a second list; the SSO/admin declarations that
already drive the blueprint render now also drive their own proof.

**Order by consequence, not count:** Gitea first (a missing admin does not stop at
Gitea — `pazny.woodpecker/tasks/post-oauth.yml` authenticates with the same password
and swallows the 401, so CI's OAuth app is silently never created, and the whole
local-first git topology hangs off that account). Then Nextcloud (the only service
holding real user data, and the only one where a green loud verify is *already*
wrong: the provider row is asserted, the discovery unblock that makes it usable is
not). Then Jellyfin — chosen for irreversibility, not frequency.

**The division of labour is the load-bearing part.** `pytest` owns the SHAPE (no
stale namespaces, no self-reporting writers, no unconsumed tolerances, a verify block
wherever an existing declaration demands one — `test_post_wiring_is_not_self_reporting.py`).
`--tags verify` owns the EFFECT. `nos-smoke --strict` with the ephemeral tester
identity owns END-TO-END truth. **Do not lean on the manifest-derived smoke probe for
any of this**: it auto-imports a front-page `GET /` per entry, and a Superset with no
admin and a FreeScout with no owner both return 200 on their login page. It answers
"is the web tier alive", never "is it owned and wired".

### Thread D — pulse and scheduled jobs, a full revision

Documented now, planned now, executed as its own arc. The trigger:

**`security-drift-watch` posts its verdict to the wrong service, and this is the third
instance of one defect.** Not a credential problem — `WING_EVENTS_HMAC_SECRET` is
correctly wired to `{{ bone_secret }}` (`files/anatomy/agents/conductor.yml:123`),
identical to the jobs that work. The URL is wrong: `conductor.yml:122` sets
`BONE_API_URL: "http://127.0.0.1:9000"`. **9000 is Wing** (`default.config.yml:816`);
**Bone is 8099** (`default.config.yml:209`), and Bone is what verifies the HMAC on
`/api/v1/notifications`. The signed POST lands on a service with no verifier → 401.
`drift-watch.sh:28`'s own fallback default hardcodes 9000 too.

The same defect was found and fixed **twice on one day** in two other manifests, whose
comments say so: `plugins/gitleaks/plugin.yml:64-77` — *"9000 is WING… it is Bone that
verifies the HMAC… every other caller in the estate already defaults to 8099; this
manifest was the sole outlier"* — and `plugins/authentik-tofu-drift-base/plugin.yml:68-70`
— *"the gitleaks manifest for the same defect, found the same day"*. `security-drift-watch`
was added later and never got the fix. The comment claiming sole-outlier status was
already false when written, and nothing checked.

So this is not a bug to patch, it is a surface to audit. Scope:

1. **Env wiring** — no manifest may hardcode a Bone/Wing port literal; assert every
   `BONE_API_URL` under `files/anatomy/{agents,plugins}/**` renders through
   `{{ bone_port }}`. Three occurrences and two prose warnings did not stop the third.
2. **Failure semantics** — *a step that cannot do its job must not exit 0.* Three
   instances on the books: the drift hook that parsed nothing (fixed 07-28), its
   notification that delivers nothing (this), and the Linux wet-test passing
   `0/0 ready` on an empty stack (`hidden_fees/08`). One paragraph into
   `docs/hidden_fees/07`, which already owns the "messages that outlive their mode"
   class — same disease, wider blast radius.
3. **Delivery** — for every job, who actually receives its output, and is that path
   tested? Two silent-delivery failures in a row says no.
4. **Ordering** — the nightly feeder chain (`keap-consolidate` → `cortex-fs-sync` →
   `keap-embed-sync` → `keap-features-sync` → `cortex-corpus-diff`) is load-bearing and
   encoded only as cron minutes. Make the dependency explicit or prove the spacing.
5. **Paused inventory** — 9 agent jobs sit paused under the on-demand doctrine. Confirm
   that is still the intent per job, or retire them.
6. **A job is an organelle** — it has an owning organ, a schedule, a delivery target
   and an access facet. Once B1 lands, the pulse catalog is a natural second consumer
   of the genome, which is what would have made item 1 structural instead of a lint.

---

## Verification

- **Part 0** — the three anonymous GETs `404` from the edge; `127.0.0.1:8082/ping`
  still `200`, container healthy; `face_edge_token` ≥ 32 chars and free of `_pw_`; the
  manifest↔auth-mode gate goes red if `traefik` leaves `traefik_skip_ids` without
  gaining a gate.
- **A1** — `e2e/agent-tables.spec.ts` keeps passing for the slug-column table; add a
  case for a table without one.
- **A2** — after re-seed, the next `keap-lint` reports **0 new `orphan-object`** and 26
  resolved.
- **B1** — `contracts-drift` regenerates all four artifacts and fails on drift; plus a
  deliberate-drift test (hand-edit one generated file, prove CI goes red). Cross-repo:
  golden fixture + KEAP consumer gate + `contracts.entity` handshake.
- **B2** — `e2e/table-graph.spec.ts:181-185` ("no per-row node objects") inverts and
  becomes the Stage-2 assertion.
- **B3** — one test asserting all four generated tier artifacts agree (the Superset
  mismatch must fail before the fix and pass after), plus the exposure gate
  **retro-tested against the pre-Part-0 `traefik` declaration** — it must fail on that
  input, or it does not do what it claims.
- **B4** — a Grafana explore query against the new datasource returns table rows.
- **C** — `lint.mjs` + `roundtrip.mjs` green before the tag; after the converge,
  `cortex-corpus-diff.py --no-ledger` reports parity **PINNED**, `taxonomy exact`, six
  clauses AGREE, counts moving together (2500 → ~2600 KEAP, 3588 → ~3690 organ).
- **D** — the env-wiring gate goes red against the current `conductor.yml:122`; forcing
  the notification endpoint to 401 makes the job exit non-zero.
- **Estate** — `tools/ci-local.sh` before any release push.

## Not in scope

Cell-level identity (B5). Migrating the compliance, cortex and face facets (B3 does
`access` only, deliberately). Building the Wing executor — organelles need the
*registry* (data) now and the *gate* (executor) only when an external system first asks
to implement one. A full plugins→organelles rename: ~1 000 occurrences and 8
hard-breaking identifiers including two `wing.db` columns and the `pulse_jobs.id`
composite format — the new word applies to the new layer only, and the old name keeps
living meanwhile.
