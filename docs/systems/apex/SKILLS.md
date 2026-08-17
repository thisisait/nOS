# Apex Site — Skills

> The apex site has NO callable surface and NO nOS-provisioned agent skill
> surface: static files behind a pinned nginx, no API, no accounts, no
> credential. This file states that plainly rather than inventing endpoints.

## Authentication

- **Method:** N/A — no credential exists. The surface is anonymous by design
  (the one routed service whose purpose is to be read by strangers), and there
  is no write path a credential could unlock.
- **Where the credential comes from:** nothing in the repo mints one.
- **Base URL:** `https://{tenant_domain}` (the ROOT domain, default
  `https://dev.local`), or `http://127.0.0.1:8061` from the host (loopback
  publish; peer containers cannot reach it — apex sits on `gated_net` only).

## Endpoints verified against repo source

nOS itself calls nothing on this service. The only automated touch points are:

- the converge build (`files/anatomy/apex/build.py --require-signed --out`),
  which WRITES the web root before the container ever starts — it is not an
  endpoint of the running service;
- the container healthcheck (`GET /` on loopback inside the container);
- the manifest-derived smoke probe (anonymous `GET /` expecting `200`).

Everything the service serves is static: `index.html`, `public-anatomy.json`
(the signed projection as machine-readable data), and `assets/`. There are no
skills to declare — no section below carries a `**Trigger:**` line, so the
recall gate correctly learns zero capabilities from this file.

## Notes

Stateless by construction: the web root is derived content rebuilt at converge
from the repo (`state/anatomy-graph.json` + the SIGNED
`files/anatomy/apex/ruling.yml`), the root filesystem is read-only, and every
bind mount is `:ro`. If the page is wrong, the fix is a re-ruled projection and
a converge — never an edit on the host.
