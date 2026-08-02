# Secrets — killing the blast radius

> Opened 2026-08-02, after the TechNosIdeas audit round produced a verified
> finding that changes the priority of everything else in the security queue.
> Operator direction the same day: **security topics have the highest priority,
> and the answer must be robust rather than incremental.**

---

## 0. The finding, stated once

Three facts, each verified verbatim in the repo:

```
backup_encryption_passphrase: "{{ global_password_prefix }}_pw_backup_encryption"
restic_password:              "{{ global_password_prefix }}_pw_restic"
backup_nos_state: true        # backs up ~/.nos/{secrets,state}.yml
```

`~/.nos/secrets.yml` holds **29 keys, 27 of them credential-shaped** — including
`bone_secret`, `authentik_secret_key`, `authentik_bootstrap_token` and
`authentik_recovery_break_glass_secret`. These are the secrets that are
*randomly generated* precisely because deriving them was judged unsafe.

So the chain is:

> **prefix → backup key → the backup → the file holding every non-derived secret.**

One leaked string yields the entire estate. REM-144 leaked exactly that string.
The gov batch's "AES-256 backup encryption" is, today, as strong as `changeme`.

**Measured, not estimated** (2026-08-02, over `default.credentials.yml`,
`default.config.yml` and every `roles/*/defaults/main.yml`):

- **103 credential names are DECLARED** as `{{ prefix }}_pw_x`, across 157 sites.
- **15 of them are rescued at runtime** by `main.yml`'s lazy-regenerate group,
  which replaces the template with `openssl rand` output on first run and
  persists it. So the **true runtime blast radius is 88**.
- **Two crown-jewel keys remain truly derived** — what they protect *contains*
  other credentials:

  | credential | what it protects | runtime |
  |---|---|---|
  | `backup_encryption_passphrase` | the nightly archive | **derived** |
  | `restic_password` | the off-site repo | **derived** |
  | `infisical_encryption_key` | the vault itself | randomised — safe |

> **A correction, recorded rather than quietly fixed.** The first draft of this
> document listed `infisical_encryption_key` as derived and called the vault
> "inside its own blast radius". That was wrong: it is in the lazy-regenerate
> group, and the live value is 32 hex with no `_pw_`. The error came from
> counting *declaration sites* instead of *runtime values* — reading the shape
> instead of the effect, which is the exact defect v0.10-beta is named after.
> The gate now parses the lazy-regenerate list out of `main.yml` rather than
> trusting the defaults.

## 1. The defect is NOT where secrets are stored

This is the part worth getting right, because the obvious response — "move
secrets into the OS keychain" — does not fix it, and the audit of that idea said
so honestly.

The actual defect is that **every derived secret is a plaintext copy of the
master**:

```
kloFASek!1990_pw_face_edge
└──────┬─────┘
   the master, in clear, inside the credential
```

`{prefix}_pw_{service}` is not a derivation. It is *concatenation*. Any single
leaked credential reveals the master by inspection, and the master yields the
other 102 by construction. That is why REM-144 was not "an edge token leaked" but
"the estate leaked".

Encrypting the store does nothing about this: the credential still has to be
*rendered* to be used, and rendering is where it leaks — into a Traefik
middleware, a compose env block, a container's `/proc/1/environ`, a debug line.

**Rule: a credential must not contain, imply, or reveal any other credential.**

## 2. What a robust answer has to satisfy

| | requirement | today |
|---|---|---|
| R1 | knowing one credential yields exactly one credential | **fails — yields 88** |
| R2 | rotating one credential does not require a blank | fails |
| R3 | the backup key is not derivable from anything inside the estate | **fails** |
| R4 | the operator does not hand-manage N secrets | holds |
| R5 | a launchd/systemd daemon can read what it needs, non-interactively | holds |
| R6 | survives `nos --remove=data` and re-provisions coherently | holds |

R4/R5/R6 are why the current design exists — they are real and must be kept.
The fix has to buy R1–R3 **without** losing them.

## 3. The proposal

### P1 — derivation becomes one-way (the structural fix, ~0.5 day)

Replace concatenation with an HKDF:

```
secret(service, purpose) = HKDF-SHA256(
    ikm  = master,                       # 32 random bytes, never rendered
    salt = tenant_slug || service_id,
    info = purpose                       # "db", "admin", "edge", …
)  → 32 bytes → base64url
```

What this changes, concretely:

- A leaked credential is **32 random bytes**. It reveals nothing about the master
  and nothing about any sibling. R1 holds by construction, not by care.
- The master is **never rendered into any artifact** — not into compose env, not
  into a Traefik middleware, not into a vhost. Only its outputs are.
- A REM-144-shaped leak becomes what it should always have been: *one* token
  disclosed, rotatable in isolation.

It keeps R4 (still one operator-held secret), R5 (derivation is pure computation,
no prompt), and R6 (same master ⇒ same outputs ⇒ a converge is idempotent).

**The honest cost:** rotating the *master* still means every derived credential
changes, which means every service must be told its new password. The estate
already has reconcile paths for several (metabase, freescout, portainer,
nextcloud). This does not make master-rotation free — it makes *per-credential*
rotation possible, which is the case that actually occurs.

**And on this estate the cost is near zero, today.** There is exactly ONE user
(`akadmin`), and the operator has already recorded that nobody depends on the
system yet, so no migration has to be written: P1 can land as a **blank-time
change**. That window closes the moment a second person has data. It is the
cheapest this fix will ever be.

#### P1b — the scope dimension, so per-user VMs are correct by construction

Adding this later would mean re-deriving every user's secrets. Adding it now
costs one extra HKDF step, so it goes in with P1 even though nothing consumes it
yet.

```
master                                        # 32 bytes, host-only, never rendered
├── estate secrets
│     secret(service, purpose)
│       = HKDF(master, salt="estate|"+service_id, info=purpose)
│
└── per-user subtree
      user_master(uid)
        = HKDF(master, salt="user|"+uid, info="user-root")
      secret(uid, service, purpose)
        = HKDF(user_master(uid), salt=service_id, info=purpose)
```

Why this shape matters for the per-user-container roadmap
(`per-user-container-roadmap.md`):

- **A compromised user container yields that user and nothing else.** It holds
  `user_master(uid)` at most. HKDF is one-way, so it cannot walk back to
  `master`, and it cannot reach a sibling `user_master` or any estate secret.
  Without the scope split, a per-user VM would need estate-derived credentials
  and every user container would be a full-estate compromise waiting to happen —
  which would make per-user *isolation* actively worse than today's shared model.
- **Per-user rotation becomes real.** Rotating one user = re-derive one subtree.
  That is R2 at the granularity where it is actually needed (a person leaves, a
  laptop is lost) rather than at estate granularity where it is impractical.
- **`uid` is already settled.** The canonical id is `slugifyUid(username)`
  (`face/src/lib/security/uid.ts`), chosen precisely because Authentik's own uid
  regenerates on every blank. The S-0 work made Nextcloud agree with it. Salting
  on a value that churns would silently orphan every user secret on a blank, so
  this depends on S-0 having been done — it has.
- **The container never gets `master`.** The host derives, and hands the
  container only the leaves it needs. `user_master` enters a container only if
  that container must derive at runtime; prefer leaves.

**One user today is the reason to do this now, not the reason to skip it.** The
whole subtree currently has one member, so getting the shape wrong costs nothing
to fix — and getting it right costs one function.

### P2 — the backup key leaves the estate's derivation entirely (~2 h)

The backup is the crown jewel: it contains the file holding every non-derived
secret. It must not be derivable from anything an attacker can reach.

- `backup_encryption_passphrase` and `restic_password` become **operator-held
  recovery secrets**, generated once, shown once, stored by the human (or in the
  OS keychain — see P5).
- The playbook may *use* them; it may never *derive* them.
- If absent, backup encryption **fails loudly** rather than silently falling back
  to a derived key. A backup that cannot be encrypted is not a backup.

This is the single highest-value hour in the whole plan, because it breaks the
chain at its most damaging link even if nothing else ships.

**HAZARD — do not ship P2 as a straight key swap.** `backup.sh:78` uses one
`ENC_PASSPHRASE` for `openssl enc -aes-256-cbc`, and `backup-verify.sh:34` reads
the same single value to decrypt. Minting a new key therefore makes **every
existing archive undecryptable**. The restore drill would go red — correctly —
but "we closed a leak and lost every backup" is a worse outcome than the leak.

So P2 is a **key ring**, not a key swap:

- `backup_encryption_key` — current, random, persisted. Used for **writing**.
- `backup_encryption_keys_previous[]` — every superseded key, kept forever.
  Used for **reading** only.
- `backup-verify.sh` tries the current key, then each previous key in turn, and
  reports **which** key opened the archive. An archive that only opens with a
  previous key is a signal, not a failure — it means it predates the rotation.
- The drill fails only when **no** key opens it.

That also makes future rotation a normal operation rather than a one-off, which
is R2 for the one credential where rotation currently means "abandon the past".

Sequencing note: seed `previous[0]` with the *derived* value on the same run
that mints the new key — computed once, from the prefix, before anything stops
deriving it. Miss that and the existing archives are orphaned silently.

### P3 — a canary that makes a leak observable (~2 h)

Everything above reduces blast radius. Nothing above tells you a leak *happened*.

Mint one credential, `nos_canary_token`, that **no service ever uses**. Register
it as an accepted-but-alarming credential on one loopback endpoint in Bone. It is
rendered into exactly the same places real credentials are — a Traefik
middleware, a compose env block — so anything that harvests credentials harvests
it too.

If it is ever *presented*, that is not a policy violation to be argued about: it
is proof that a rendered artifact was read by someone who should not have read
it. Fire an A9 CRITICAL.

This is deliberately in the spirit of the v0.10 theme — it observes an **effect**
instead of trusting that the guards held.

### P4 — blast radius becomes a measured number, not a claim (~2 h)

A pytest that answers, statically: *"if an attacker learns string X, how many
credentials do they now hold?"*

- Build the credential inventory from `default.credentials.yml` +
  `default.config.yml`.
- For each, compute its derivation inputs.
- Assert **max blast radius == 1**, with an explicit, justified allowlist for any
  exception.

Run it against today's tree first: it must report **88** and hold the ratchet. A gate that
cannot fail against the defect it names is not a gate — the estate has paid for
that lesson twice this release.

### P5 — *then* the OS keychain, and now it is small (~1 day, not 4–5)

Here is the pleasant inversion. The keychain audit found that storing ~103
secrets in the macOS keychain is awkward: a dedicated keychain is a non-starter
(locked ⇒ `rc=128`, and its unlock password would itself need a file), and the
reader must shell out to `/usr/bin/security` because a non-trusted binary blocks
on a GUI prompt.

**After P1 there is only ONE secret to protect** — the master — plus the P2
recovery keys. One item in the login keychain, read by `/usr/bin/security` from a
launchd agent, which was **verified live to work non-interactively** (rc=0, no
TTY, no `SECURITYSESSIONID`).

So the sequencing is not "keychain first because security". It is:

> **Fix derivation and the keychain problem shrinks from 88 items to 1.**

Linux equivalent: `systemd-creds` (LGPL-2.1+) with the same single-item shape.

## 4. Sequencing, and what to do if only one thing ships

1. **P2 — backup key out of derivation (~2 h).** Highest value per hour. Breaks
   the chain at the point where a prefix leak becomes a total compromise.
2. **P0 — random prefix on first run + drop the `tenant_domain_is_local` assert
   carve-out (~1 h).** Closes REM-151. Independent of everything else.
3. **P1 — HKDF derivation (~0.5 day).** The structural fix.
4. **P4 — the blast-radius gate.** Written to go red against the pre-P1 tree.
5. **P3 — canary.**
6. **P5 — keychain for the master.**

## 4b. Then test the flow that mints a user

Once P1b exists, the user-creation path is the thing that proves it, and it is
currently the least-exercised flow in the estate: exactly one user has ever gone
through it, and that user is the bootstrap admin — which is not the same path a
real invitee takes.

What to exercise end-to-end (A18 "Cesta B", `docs/invite-provisioning.md`):

1. Wing `/users` mints an Authentik invitation.
2. Per-user credentials are provisioned into Infisical under `/users/<name>/`.
3. A Stalwart mailbox is created via JMAP.
4. The user logs in through Authentik and lands in each `header_oidc` service.
5. Their VFS tree appears at `users/<slugifyUid(username)>/`.
6. **New, and the point of the test:** their secrets derive from
   `user_master(uid)` and from nothing else.

The assertion that matters is negative and is the one to write first: **given
user A's leaves, nothing about user B or the estate is derivable.** With one user
that is untestable by inspection — so the test needs a *second, disposable* user,
which is also the only honest way to find out whether the invite flow works at
all for someone who is not the admin.

Worth stating as a risk: S-0 fixed Nextcloud's uid *going forward*, and the
legacy hashed account is still present, unmigrated. A second user is what will
reveal whether that fix actually holds for a fresh person, rather than only in
the provider config.

## 5. What this does not fix, stated plainly

- **Already-disclosed material.** If the current prefix reached anyone, every
  credential derived from it must be considered known, and P1 does not
  retroactively protect them. That is a rotation event, and on this estate
  rotation of the master still means a blank.
- **Secrets in container environments.** `docker inspect` and `/proc/1/environ`
  still show a service its own credential. P1 narrows that to one credential per
  container instead of a master; it does not eliminate it. Fixing that needs
  file-mounted secrets or a runtime fetch, and is out of scope here.
- **n8n.** Its credentials live in its own database, invisible to the playbook.
  Nothing in this plan reaches them.
