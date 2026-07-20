# 02 — Healthchecks that answer without touching their database

## The fee

The STRICT bring-up gate believes container health. A healthcheck that answers
from the HTTP layer alone therefore certifies a container whose every real
request is failing.

miniflux proved it: the canonical upstream probe
(`miniflux -healthcheck auto` → `/healthcheck`) never touches Postgres, so the
container reported **healthy for 19 hours** while `/` returned 500 to every
caller, and the STRICT health-wait passed it. Fixed 2026-07-20 by probing `/`
instead, pinned by `test_miniflux_healthcheck_is_db_aware`.

**The class is not closed.** Surveyed on the other Postgres-backed services:

| service | probe | DB-aware? |
|---|---|---|
| hedgedoc | `:>/dev/tcp/127.0.0.1/3000` | **no** — pure TCP liveness |
| outline | `/_health` | unverified |
| superset | `/health` | unverified |
| infisical | `/api/status` | unverified |
| metabase | `/api/health` | unverified |
| paperclip | `/` | likely yes |

"Unverified" is the fee. A dedicated `/health` endpoint *may* check the database
or may be a static 200 — and which one it is decides whether the STRICT gate
means anything for that service.

## When the bill comes due

Whenever a database is reinitialised, migrated, or replaced under a container
that is not restarted afterwards. That is not exotic: it is what happened here —
Postgres was recreated at 05:25, every service restarted after it re-migrated,
and miniflux (up since 22:08 the previous day) alone missed the window.

The bill is always the same shape: **green everywhere, broken in production**,
and the operator finds out from a user rather than a gate.

## How it was found

Sideways. Running the anatomy suite before a release surfaced one failing live
test (`test_hub_url_audit`), which turned out to be a single 500 on
`rss.pazny.eu`. The healthcheck gap was the second-order finding.

## What closes it

Per service, verify what the probe endpoint actually touches, and move it to a
DB-rendering route where it does not. Cheap per service, and the pattern is
already established by the miniflux fix.

Worth pairing with the wider rule the healthcheck-coverage gate started
(`c1698d9e`): coverage answered *"does a probe exist?"*, this answers *"does the
probe prove anything?"* — and only the second one makes "green" mean "working".
