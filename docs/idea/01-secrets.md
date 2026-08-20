# 01 — Secrets: kill the blast radius

**Status: P1 SHIPPED-INERT 2026-08-20** (P0/P2/P4 shipped 2026-08-02; P3/P5
queued). The estate stays on scheme v1 (byte-identical concatenation) until a
confirmed blank flips it to v2 (HKDF of a never-rendered master). Spec + the
adversarial-review record: [`docs/secrets-p1-hkdf.md`](../secrets-p1-hkdf.md).
Ask the estate, don't infer: `tools/nos-secret.py --status`.
**Detail:** [`docs/archive/secret-blast-radius.md`](../archive/secret-blast-radius.md) ·
**Workflow:** `.claude/workflows/p1-hkdf-derivation.js`

## The defect, in one line

`{prefix}_pw_{service}` is not a derivation, it is **concatenation** — the
rendered credential contains the master in clear:

```
kloFASek!1990_pw_face_edge
└──────┬─────┘
   the master, readable, inside the credential
```

So one leaked value reveals the master by inspection, and the master yields the
rest by construction. REM-144 leaked exactly that, from an unauthenticated
Traefik API, **on a local install** — which is why the "local is not exposed"
carve-out is gone.

## Measured, and re-measured

| | at discovery | after P0+P2 |
|---|---|---|
| declared derived | 103 | 101 |
| **truly derived at runtime** | 88 | **86** |
| crown-jewel keys derived | 2 | **0** |

The gap between "declared" and "runtime" is `main.yml`'s lazy-regenerate group,
which randomises 17 of them on first run. **The first version of the gate missed
that and reported the Infisical vault key as compromised. It is not.** Reading
the declaration instead of the effect is the defect v0.10-beta is named after,
and the gate committed it before it caught it.

## What shipped

- **P4 — the number is measured.** `tests/anatomy/test_secret_blast_radius.py`,
  ratchets not targets. The crown-jewel test asserts on the *declaration*
  deliberately: a first version subtracted the lazy-regenerate rescue and was
  **vacuous** — restoring the derived default left it green.
- **P0 — the weak-prefix gate covers every tenant.** The local carve-out rested
  on a premise REM-144 disproved.
- **P2 — the archive key stopped deriving.** The chain was
  `prefix → archive key → the archive → ~/.nos/secrets.yml inside it → every
  randomised secret`. Broken with a **key ring, not a swap**: a swap would have
  orphaned every existing archive, and "we closed a leak and lost the backups"
  is the worse outcome.

## What is next, and why it is dangerous

**P1 — HKDF derivation.** A leaked credential becomes 32 random bytes. It also
changes all 86 passwords at once, so on a converged host without a blank it
breaks every login. The workflow encodes that as a **gate**, not a hope: with
scheme v1 recorded, every credential must resolve byte-identical to today.

**P1b — the scope split, built now while it is free.**

```
master
├── estate:  HKDF(master, "estate|"+service, purpose)
└── user:    user_master(uid) = HKDF(master, "user|"+uid, "user-root")
```

Without it, per-user containers would need estate credentials and **every user
container would be a full-estate compromise waiting to happen** — isolation
worse than today's shared model. There is one user, so the subtree has one
member and the shape costs nothing to get right.

## Open

- **P3 canary** — a credential no service uses, rendered where real ones are.
  If presented, a rendered artifact was read by someone who should not have.
- **P5 keychain** — shrinks from 86 items to 1 *after* P1. Verified live: a
  launchd agent reads the login keychain non-interactively.
- **Commit signing** — required by the master ruleset, satisfied zero times; the
  v0.10 push logged `Found 188 violations` and admin-bypassed.
