# SpacetimeDB — for agents

**What you may assume:** nothing about authorisation from the outside. There is
no trusted-issuer list on the server; a module decides for itself whether a
caller's identity may act. "The token validated" and "the call is permitted"
are separate facts, and only the module knows the second.

**No admin surface.** There is no console, no user table and no password to
rotate. An agent looking for one is looking at the wrong service.

**Publishing needs a WASM artifact.** The post-start hook registers the server
alias in the host CLI config and prints a `spacetime publish` hint — it does
not publish anything. An estate with SpacetimeDB up and no module is a correct
state, not a fault.

**Liveness** is `GET /admin` on `127.0.0.1:3030`.

**Licence.** BSL 1.1: one production instance, internal use. Converts to AGPLv3
on 2031-03-20. Do not propose a second instance.
