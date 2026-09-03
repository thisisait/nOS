# 49 — An OIDC env that ships under a forward_auth claim

**Found** 2026-09-02; **closed** 2026-09-03.

## What it looked like

FreeScout flipped to `mode: forward_auth` under REM-192 (2026-08-11) — the
honest close of a native-OIDC path that NEVER worked (both module sources HTTP
404, moved to the paid marketplace). But the flip left four surfaces telling
the old story: the compose-extension still rendered the full `FREESCOUT_OIDC_*`
block — a client secret in flight for a module that cannot exist; post.yml
still ran the (honest, effect-checked, and pointless) clone; the role README
still prescribed `authentik_oidc_apps` entries; the forward-auth gate's
docstring still cited `mode: native_oidc` at a line number that no longer says
that.

## Why it hid

The edge flip looked like the whole close. Dead env still looks wired; a
README nobody re-reads after a flip keeps selling the old mode.

## The close

Deleted: the OIDC env block, the module clone/enable/persist section (~180
lines — git history keeps them for the day a reachable source exists).
Rewritten: README, CLAUDE.md paragraph, gate docstring — all say
forward_auth-since-REM-192. The forward-auth gate now covers FreeScout like
any other gated service instead of exempting it.
