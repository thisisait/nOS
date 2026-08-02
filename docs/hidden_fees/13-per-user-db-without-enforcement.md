# 13 — A per-user database chosen by an unauthenticated parameter

## The fee

Bone's user-state API gives each user their own SQLite file
(`files/anatomy/bone/userstate.py`): `_db_path(uid)` resolves to
`{data_root}/tenants/<slug>/users/<uid>/.face/state.db`, `chmod 0700`, WAL. The
layout is right and it matches doctrine class 3 — the filesystem is the boundary.

**Which user's file gets opened is decided by a `uid` parameter**, behind
`require_face_token`, a **static shared bearer** (`BONE_VFS_TOKEN`).
`_validate_uid` rejects `/`, `.`, `..` and leading dots — path traversal, not
authorization. So any holder of the face token can name any uid and read or write
that user's state.

The author knew the ground it stands on: `# macOS single-user: structural only`
sits beside the `chmod`. On a single-operator machine the separation is
organisational and the token is the only real control, which is coherent.

## When the bill comes due

**The second real user.** Not a second uid — `nos-docs` and `akadmin` already
coexist — but the first person who is not supposed to read the other's data. At
that moment every holder of one shared token is every user at once.

It compounds with the cortex plan (`docs/archive/cortex-self-core.md` §6b), which
adopts this same per-user-store pattern for the knowledge corpus. Per-user stores
move the access decision **from a `WHERE` clause into a file path**: get a filter
wrong and one row leaks; get a path wrong and a whole store does. The pattern is
worth copying. The enforcement must not be.

## How it was found

While answering whether cortex should be a user with its own identity — looking
for an estate precedent for per-user databases, and finding one that had solved
the storage half and deferred the identity half.

## What closes it

An identity the request carries rather than asserts, and the uid derived **from
it** instead of from a parameter. Two shapes, and the cortex plan needs the same
answer:

- **The OS is the identity provider.** A process running as the Unix user opens
  only what the kernel permits. No token is involved in reading one's own data.
  Strongest, and it costs a process per active user.
- **On-behalf-of tokens.** A bearer whose subject is the user, verified against
  Authentik's JWKS — which Bone's `auth.py` can already do for
  `client_credentials`. But *"I am the face acting for akadmin"* is token
  exchange, and nothing in the estate issues that today. **That is the piece with
  no existing answer**, and it is research, not assembly.
