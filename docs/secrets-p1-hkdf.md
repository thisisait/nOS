# Secrets P1 — one-way HKDF derivation (the committed spec)

> Implements `docs/archive/secret-blast-radius.md` §P1 + §P1b, roadmap row
> `sec-p1`, via the `p1-hkdf-derivation` workflow. Written 2026-08-20, BEFORE
> any code, as the workflow's Design phase requires. Every decision below is a
> decision; §9 lists what was deliberately NOT decided.

## 0. The defect and the shape of the fix

`{prefix}_pw_{service}` is concatenation, not derivation: every rendered
credential contains the master in clear. Measured 2026-08-20 (Scout phase):
**103 names declared as prefix-derived across 157 vars-file sites, 86 truly
derived at runtime** — plus a surface the old gate never scanned: **~43 OIDC
client secrets concatenated inline in `files/anatomy/plugins/*/plugin.yml`**
and their compose extensions, the gitlab compose template, two
`authentik_service_post.yml` sites, ten agent client secrets in
`templates/secrets.yml.j2`, and a per-user password in
`tasks/stacks/bluesky_pds_bridge.yml`.

The fix: all of those resolve from **one derived map**, computed once per run
by a custom module, under a **scheme version**:

- **scheme v1** (every already-converged host): the map reproduces
  `{prefix}_pw_{key}` **byte-identical**. The change is inert.
- **scheme v2** (first reached at a blank, or on a genuinely fresh host): the
  map is HKDF-SHA256 leaves of a random 32-byte master that is never rendered.

## 1. Decision A — where the derivation runs

**A custom Ansible module, `nos_secret_map` (`files/anatomy/library/`), invoked
ONCE in `main.yml`, its result exposed by a single `set_fact` as
`nos_derived_secrets` (a flat `{key: value}` dict), `nos_secret_scheme` and
`nos_secret_master`.** Both tasks are `no_log: true`.

- Why not a Jinja filter: constraint 1 — `default.config.yml` /
  `default.credentials.yml` are eagerly resolved by the plugin loader via
  `template_vars: "{{ vars }}"` in a context where ansible filter plugins are
  NOT loaded. A filter in a vars file aborts the run
  (`test_config_stock_jinja_only.py`). References like
  `{{ nos_derived_secrets.oidc_gitea }}` are stock Jinja attribute access and
  survive that resolver.
- Why not a lookup plugin: it would recompute per reference, cannot own the
  scheme decision (which is stateful and must fail loudly exactly once), and
  values must exist as real vars before core-up anyway (constraint 2) — so a
  single set_fact is required regardless.
- Why not an action plugin: nothing here needs controller-side execution;
  the module follows the `nos_state.py` / `nos_migrate.py` precedent and the
  `ansible.cfg` `library` path already covers it.
- Placement: **after** `tasks/run-mode.yml`, the prefix prompt and the
  prefix-change detection (the prefix can still change there), **before**
  `tasks/pre-wipe-backup.yml` / `blank-reset` / `restore.yml` (the earliest
  consumers — `restore.yml` reads `mariadb_root_password`). That satisfies
  constraint 2: the values exist long before any `{{ vars }}` eager resolve.

The pure logic lives in `files/anatomy/module_utils/nos_secret_derive.py` so
unit tests and the operator reader tool import the same functions the module
runs. HKDF is RFC-5869 over `hashlib`/`hmac` — **stdlib only**, no new
dependency for a mechanism the whole estate boots through.

## 2. Decision B — the scheme-version switch

The marker is **`nos_secret_scheme` in `~/.nos/secrets.yml`** — the runtime
side-car that already survives converges, is loaded by the existing early
`include_vars`, and is deleted by a confirmed blank (`blank-reset.yml` removes
the file). The master is **`nos_secret_master`** in the same file (§4).

Resolution, in the module, in this order:

| state | result |
|---|---|
| recorded `v2` | v2. Master missing/malformed → **FAIL** (corrupt store). |
| recorded `v1`, not blanking | v1 — byte-identical concatenation. |
| blanking (`blank\|bool`, i.e. a CONFIRMED `remove=data\|deep\|all`; dry runs ended the play in run-mode) | v2 — mint a fresh master. |
| no record, store file exists | v1 — this is every pre-P1 converged host. **This row is the inertness guarantee.** |
| no record, no store, estate markers present (non-empty `stacks_dir`) | **FAIL LOUD** — a wiped side-car on a converged estate is ambiguous; re-deriving would rotate 86 live passwords. The message names the two exits: restore `~/.nos/secrets.yml`, or run a confirmed blank. |
| no record, no store, no estate | v2 — genuinely fresh host / CI runner. Mint. |

Illegal transitions (both **FAIL LOUD**, message naming
`nos --remove=data --confirm`):

- `-e nos_secret_scheme=v2` (or any requested v2) while resolution says v1.
- requested `v1` while the store records `v2` (silent downgrade back to
  concatenation).

A blank flips the scheme as a *consequence*, never silently: run-mode's
confirmation gates already ran, blank-reset deletes the store, and the persist
step writes `nos_secret_scheme: v2` + the new master.

## 3. Decision C — HKDF parameters (§P1 + §P1b)

```
master                = 32 random bytes (secrets.token_bytes), stored hex
estate leaf           = HKDF-SHA256(ikm=master,
                                    salt=b"nos/estate|" + service,
                                    info=purpose) → 32 bytes → base64url, no padding (43 chars)
user_master(uid)      = HKDF-SHA256(ikm=master, salt=b"nos/user|" + uid, info=b"user-root")
user leaf             = HKDF-SHA256(ikm=user_master(uid), salt=service, info=purpose)
```

- `(service, purpose)` per credential comes from the committed registry
  `files/anatomy/secrets/registry.yml` — **one file**, consumed by the module,
  the gates and the reader tool, so there is no second allow-list to drift
  (the Pulse catalog lesson).
- `uid` is `slugifyUid(username)` per `face/src/lib/security/uid.ts` (NFKD,
  strip combining marks, lowercase, non-alnum runs → `-`, trim, cap 64). The
  rule is reproduced in `nos_secret_derive.slugify_uid` and pinned by unit
  fixtures (`Pázny → pazny`). If the rule ever changes, every user leaf
  changes — the same orphaning S-0 fixed for the VFS — so the fixture failing
  is the alarm, not an inconvenience.
- First real user-scope consumer: the Bluesky PDS bridge's per-user account
  password (`_pw_bsky_<username>` today). v1 keeps the literal concatenation
  byte-identical; v2 derives `user(uid, service="bsky", purpose="password")`.
- v1 compatibility rule: `leaf_v1(key) = prefix + "_pw_" + key`
  (`nos_tester` uses `tester_password_prefix`, preserving the operator's
  documented decoupling override in v1).

Shared leaves stay shared: `freescout_db_password` and
`freescout_admin_password` both resolve `_pw_freescout` today, so both map to
the key `freescout` — v1 byte-identity outranks the (real, and deferred)
wish to split them at v2.

## 4. Decision D — where the master lives on a v2 host

`~/.nos/secrets.yml`, mode 0600, alongside every other minted secret. It is
inside the nightly archive — acceptable **because P2 already took the archive
key out of derivation**; the chain "prefix → archive → master" no longer
exists. P5 (keychain) is not designed out: the module *receives* the master as
an input var, so moving custody to the login keychain later changes only who
supplies the value, not one line of derivation.

## 5. Decision E — what rotation means

Honestly: **for most of these credentials, only a blank rotates them.** A
Postgres role password set at container init, an OIDC secret baked into a
service's own DB — the reconcile paths that exist (gitlab rails runner, ntfy
change-pass, superset/metabase/portainer/nextcloud/jellyfin/uptime-kuma post
tasks, the Authentik blueprint/tofu reconverge for OIDC pairs) cover a
minority. P1 does not pretend otherwise and builds no per-leaf rotation
mechanism (§9). What P1 buys is that a *leak* of one leaf no longer forces
rotating the other 123.

## 6. What moves, what stays

**Moves to the map** (124 registry keys): the 86 runtime-derived vars-file
names, the ~43 plugin-manifest/compose-extension OIDC client secrets, the 14
agent OIDC client secrets (inline in `authentik_agent_clients` and named in
`secrets.yml.j2`), `jellyfin` + `calibreweb` (admin passwords that existed
only as `default(prefix + …)` fallbacks in role tasks), `nos_tester`.

**Stays, with its reason stated:**

- `restic_password` — BLOCKED crown jewel; a restic key is per-repository and
  the live repo was created under the derived key. Unblock command in the
  blast-radius gate. In v2 the prefix therefore still yields restic until the
  operator runs `restic key add`.
- `ntfy_admin_password` — operator decision 2026-08-08: a human types it on a
  phone; reconstructable-from-prefix is the feature. The explicit, justified
  allowlist entry the plan's P4 anticipated.
- `tester_password_prefix` — an alias of the prefix, not a credential; kept as
  the v1 decoupling override input.
- The 27 lazy-minted names — **coexist, deliberately** (see §8).
- The backup key-ring seed in `main.yml` — it reconstructs the *historical*
  derived archive key so pre-P2 archives still open. It reads the past; it
  must keep concatenating forever.
- `previous_password_prefix` reconcile candidates (jellyfin, uptime-kuma) —
  v1 old-password guesses; harmless wrong guesses on a v2 host.

## 7. Inertness — how a reader confirms it

1. `tests/anatomy/test_secret_scheme_inert_until_blank.py` — with scheme v1,
   every registry key resolves byte-identical to `{prefix}_pw_{key}` (built
   from the RULE, not a snapshot), and both illegal transitions raise naming
   the blank.
2. On the live host: `tools/nos-secret.py --status` prints the resolved scheme
   (values never). A pre-P1 store answers `v1 (implicit — no marker recorded)`.
3. Determinism argument, stated rather than hand-waved: in v1 the map is a
   pure function of the prefix, so every render input is unchanged; the only
   file that changes on the next converge is `~/.nos/secrets.yml` gaining the
   explicit `nos_secret_scheme: v1` line.

## 8. Relation to the lazy-regenerate group — COEXIST

The minted group and the derived map answer different requirements and neither
subsumes the other:

- **Minted** (openssl rand, persisted): individually rotatable (regenerate one,
  persist), NOT reproducible from the master — correct for HMAC pairs, APP_KEYs
  that encrypt data, tokens captured from a service that shows them once.
  Their persistence gate (`test_minted_secrets_are_persisted`) stays load-bearing.
- **Derived** (HKDF): reproducible from one operator-held master (R4/R6),
  NOT individually rotatable without a generation mechanism (§9).

Folding the minted set into the map would re-couple 27 deliberately decoupled
secrets to a single root for zero gain (they already persist); folding the map
into minting would put 124 values into `~/.nos/secrets.yml` and make R6's
"same master ⇒ same estate" false. So: coexist, boundary pinned by the
blast-radius gate's rescue-list parser.

## 8b. What the adversarial review changed (Verify/Fix phase, 2026-08-20)

Four lenses ran against the first implementation; the confirmed findings and
their fixes, recorded because each is a class, not a typo:

- **The `no_log` scrubber corrupts what it protects.** `prefix` as a `no_log`
  module PARAMETER made `AnsibleModule.exit_json()` rewrite every v1 value to
  `********_pw_<key>` (substring scrub of the whole result) — inertness
  inverted, invisible to every pure-function test. Fix: confidentiality moved
  to the TASK (`no_log: true` on the map call); the parameter is
  scrubber-invisible. Gate crosses the boundary now:
  `test_module_boundary_keeps_v1_values_byte_identical` executes the module
  as a subprocess the way Ansible does.
- **One censored task also censored its own remediation text.** Split into
  `mode=resolve` (secret-free result, loud failures) + `mode=map` (censored).
  Pinned by `test_resolve_mode_returns_no_secret_material`.
- **A committed GENERATED file kept the old rule.** `state/
  tofu-authentik-services.yml` still carried 18 concatenated OIDC client
  secrets — the sole Authentik-side source under the live
  `authentik_engine: tofu` (the 10-oidc-apps blueprint is dropped under tofu),
  so a blank would have broken all 18 SSO logins silently. Regenerated via
  `tools/tofu-authentik-gen-registry.py`; the widened concatenation gate now
  scans `state/` (and `apps/`, `files/observability/`).
- **The persisted store outranks the declarations.** 16 map-backed names
  (mariadb root, cortex/keap tokens, nine Wing bearers) load from
  `~/.nos/secrets.yml` at include_vars precedence — across a blank they would
  have silently kept their stale pre-P1 literals forever. Fix: the
  "[Secrets] Reconcile store-shadowed derived names" set_fact (guard: a
  `_pw_`-shaped value differing from the current derivation is a stale copy,
  never an operator override); cross-checked against `secrets.yml.j2` by
  `test_store_persisted_map_names_are_reconciled_after_derivation`.
- **`destroy_state` auto-promote is v1 logic.** On v2 a prefix edit rotates
  nothing, so destroying Infisical's KMS key / APP_KEYs in exchange is data
  loss. The promote now fires only when `nos_secret_scheme == 'v1'`.
- **The uid rule must be the ts rule, not "strip combining".** uid.ts strips
  exactly U+0300–U+036F; `unicodedata.combining()` diverged on 522 BMP code
  points and collided e.g. `pa่zny` with `pazny` — a cross-user subtree
  collision. Fixed to the regex; fixtures pin the divergent code points. The
  PDS bridge additionally REFUSES a run in which two usernames slugify to the
  same uid (a shared uid is a shared `user_master`).

## 9. Deliberately NOT decided / not built, and NAMED limitations

- **Per-leaf generation counters** (rotate one derived leaf without a blank).
  Designed trivially (`info = purpose + "#gN"`) but NOT built: persisted-store
  shadowing (`~/.nos/secrets.yml` names outrank the vars-file declaration)
  would silently pin the old value for every persisted name, making the
  mechanism a lie for exactly the credentials it matters for. Build it only
  together with a persistence-reconcile step.
- **P5 keychain custody** of the master (explicitly out of scope, §4).
- **Splitting shared v1 leaves** (freescout db/admin, superset db) into
  distinct v2 leaves — deferred to keep v1 byte-identity trivially provable.
- **The invite-flow second-user test** (plan §4b) — needs a live blank first.
- ~~Retiring the dead `| default(global_password_prefix + '_pw_…')` fallbacks~~
  — DONE in the Fix phase after the review showed they are latent v1 re-entry
  points (a fallback that ever fired on a v2 host would inject a wrong,
  prefix-bearing password): all now read `default(nos_derived_secrets.<key>)`,
  including the Infisical-seed block whose fallbacks used suffixes that were
  wrong even under v1 (`_pw_gitea_admin` for a `_pw_gitea` credential).
- **The `{{ vars }}` channel at `-vvv`.** `nos_derived_secrets` and
  `nos_secret_master` are play facts, so they ride `template_vars: "{{ vars }}"`
  into the plugin-loader invocations and are echoed in
  `invocation.module_args` at `-vvv` (and `~/.nos/ansible.log`). This is the
  SAME channel every credential — and the prefix itself — rode before P1, so
  P1 does not widen it; the registered duplicate `_nos_secret_map` is dropped
  right after the set_fact, and the Wing telemetry callback's key-name
  redaction covers all three names. A structural fix (filtered template_vars)
  is follow-up work, not P1.
- **`wing_telemetry`'s value-shaped redaction is v1-shaped.** Its
  `\w+_pw_\w+` backstop — the rule that catches a credential appearing BARE
  in stdout/cmd — cannot match a 43-char random leaf, so on v2 the flag- and
  auth-context rules carry that load alone. Named here rather than "fixed":
  there is no honest pattern for random strings.
- **`AKADMIN_PASSWORD` seeded into Infisical was never the akadmin password**
  (`_pw_akadmin` vs the real `_pw_authentik_admin`) — a pre-existing fiction
  P1 preserves byte-identically rather than silently changing a live seeded
  value. Fixing it is a one-line key change **at the blank**, queued in
  `docs/roadmap.md` terms rather than smuggled into an inert change.

## 10. Operator UX at v2, named plainly

After the blank that flips to v2, `<prefix>_pw_akadmin` stops being the
Authentik login: credentials are 43-char random strings. The operator reads
their own credential with `tools/nos-secret.py <key>` (local, master-holding
host only; the tool REFUSES to print under v1, where the value would contain
the prefix). A literal in `credentials.yml` still overrides any derived value,
same as always.
