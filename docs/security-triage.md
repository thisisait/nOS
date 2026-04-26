# GitHub Code Scanning — triage notes

Snapshot date: 2026-04-26 • Repo: `thisisait/nOS`

This doc is the maintainer's standing reply to CodeQL alerts. Each entry
states whether the alert is a **real bug** (fixed in code), a **false
positive** (CodeQL can't see the validator that mitigates it), or a
**known-acceptable risk** (threat model says it doesn't matter for the
deployment shape).

When dismissing an alert in the GitHub UI, link to the matching section
below + use the standard rationale ("won't fix", "false positive", or
"used in tests").

## Resolved (commit-level fix)

### `actions/missing-workflow-permissions` × 3 — `.github/workflows/ci.yml`
**Status:** **fixed** • Commit: this batch.
Added top-level `permissions: contents: read` so every job inherits
read-only repo access. Per-job overrides can add write capabilities
later when we ship a release job.

### `py/command-line-injection` #14 — `files/bone/main.py:130`
**Status:** **fix-and-document** • Commit: this batch.
The endpoint shells out to `ansible-playbook --tags <tag>` via
`subprocess.Popen` with `shell=False` and list-form `cmd`. So shell
metacharacters can't reach a shell. CodeQL flags it because user input
flows into `argv[3]`.

Tightened the validator: tag must now match `^[A-Za-z][A-Za-z0-9_,-]{0,99}$`
(must start with a letter, then alphanumeric + `_-,`). This rejects
values that could parse as an ansible-playbook flag (`-something`,
`--my-tag`). Even though the value sits behind `--tags`, this is
defense in depth.

## False positive (validator hidden from CodeQL)

### `py/path-injection` #15-#18 — `files/bone/{patches,upgrades}.py`
**Status:** **dismiss as false positive.**
All four call sites construct paths like `{DIR} / f"{user_id}.yml"`
**after** the user input has been validated by a strict regex
(`_ID_RE = ^PATCH-\d{3,5}$`, `_SERVICE_RE`, `_RECIPE_RE`). The user
can never escape the parent directory. CodeQL cannot reason about
`re.match(...) is None → return None` as a sufficient sanitizer.

### `js/unvalidated-dynamic-method-call` #19 — `files/project-wing/index.html:306`
**Status:** **dismiss as false positive.**
```js
const renderers = { overview: ..., timeline: ..., components: ..., ... };
el.appendChild((renderers[activeTab] || buildOverview)());
```
Dispatch is gated by an explicit object literal — `renderers[activeTab]`
returns `undefined` for any value that isn't one of the literal keys, and
the `|| buildOverview` fallback handles that. No prototype chain access,
no global function lookup. CodeQL flags any `obj[userInput]()` pattern as
a precaution but the actual surface is closed.

### `py/command-line-injection` #13 — `files/bone/migrations.py:117`
**Status:** **dismiss as false positive (with comment).**
`subprocess.Popen` with `shell=False`, list-form `cmd`, AND extra-vars
already validated by a stricter regex than the one in main.py
(`^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$`, must start alphanumeric).
Same class as #14 but tighter validator already.

## Known-acceptable risk

### `js/insufficient-password-hash` #5 — `files/jsos/adapters/provision.js:103`
**Status:** **acknowledge, do not fix.**
```js
const userPw = crypto.createHash('sha256')
  .update(`${prefix}_${safe}`)
  .digest('hex')
  .substring(0, 32);
```
This is **not** a user password. It's a deterministic Postgres role
password derived from the project's `global_password_prefix` (already a
secret) + the safe service name. Threat model:
- Attacker with shell access already has the prefix from `~/.nos/secrets.yml`.
- Attacker with DB access already has the role password from
  `pg_authid` (or doesn't need it).
- The "weak hash" rule applies to user passwords being verified by
  hash-comparison. This is a one-way derivation for service plumbing.

Adding bcrypt/scrypt/argon2 here would block deterministic
re-derivation (the whole point of the pattern — `blank=true` + same
prefix → same role passwords → no DB migration needed). Real cost,
zero benefit.

If a future audit insists, the right answer is to switch from
`createHash('sha256').update(...)` to `crypto.hkdfSync('sha256', ...)`
which is a proper KDF without changing the deterministic property.
That keeps CodeQL happy without breaking the model.

## Maintenance protocol

When a new CodeQL alert arrives:
1. Triage with this checklist:
   - Real bug → fix + commit reference here.
   - Validator hidden from CodeQL → dismiss as **false positive** + add entry here.
   - Acknowledged risk → dismiss as **won't fix** + add entry here with
     threat model reasoning.
2. **Never silently dismiss** — every dismissal must point to a section
   in this file. Auditors / downstream contributors see the rationale.
3. **Re-triage on every release** — if the threat model changes (e.g.,
   we expose Bone to the public internet), revisit acknowledged risks.
