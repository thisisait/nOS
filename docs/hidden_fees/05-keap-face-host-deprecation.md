# 05 — `KEAP_FACE_HOST` is emitted for a pin we will leave behind

## The fee

`roles/pazny.keap/templates/compose.yml.j2` emits **two** CSP variables:

- `KEAP_EMBED_ORIGINS` — the real one: a list of origins, scheme explicit.
- `KEAP_FACE_HOST` — deprecated, kept only because the current pin (`v1.18.1`)
  predates the new variable and would otherwise fall back to `face.<tld>`, a host
  that no longer exists.

Emitting both is correct **today** and correct through the pin bump. It stops
being correct the moment nothing on the estate runs a KEAP older than the tag
that carries `KEAP_EMBED_ORIGINS` — at which point `KEAP_FACE_HOST` is a dead
variable propagating a name that a product deployable without nOS should not
carry in its interface at all.

Dead compatibility shims are the cheapest thing in the world to leave in place,
which is exactly why they survive for years.

## When the bill comes due

Not with a failure — that is the point. It is charged as **interface debt**: the
next person reading KEAP's env contract sees a variable named after nOS's UI and
reasonably concludes KEAP is coupled to nOS. The false conclusion is the cost.

Concretely due when `keap_repo_ref` moves past `v1.20.0`.

## How it was found

Written down at the moment the shim was added, rather than discovered later —
the one case in this folder that was not found sideways. That is deliberate: a
deprecation window with no recorded end is just a permanent feature with an
apologetic comment.

## What closes it

Delete the `KEAP_FACE_HOST` line from the compose template once `keap_repo_ref`
is past `v1.20.0`. One line, no migration, no coordination — the newer KEAP
already prefers `KEAP_EMBED_ORIGINS` and ignores the old variable.

Worth pairing with a quick grep for the same shape elsewhere: a variable kept
"for the old pin" outlives its reason silently, because nothing fails when it
becomes redundant.
