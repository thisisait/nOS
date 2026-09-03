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

**The class is not closed.** Surveyed on the other Postgres-backed services —
and RESOLVED for four of them on 2026-08-18, by reading the handler out of the
running image rather than reasoning about the endpoint's name:

| service | probe | DB-aware? | evidence |
|---|---|---|---|
| outline | `/_health` | **yes** | `await sequelize.query("SELECT 1")` **and** a Redis ping, 500 on either — read from `/opt/outline/build/server/index.js` |
| hedgedoc | ~~`/dev/tcp`~~ → `/status` | **yes, as of today** | see below |
| superset | `/health` | **NO — static** | `/app/superset/views/health.py` is four lines: bump a stats counter, `return "OK"`. Touches nothing |
| infisical | `/api/status` | **partly** | handler calls `getServerCfg()`, which is `withCache({… ttlSeconds …})` over `serverCfgDAL.findById`. Redis every call, Postgres only on a cache MISS — so it stays 200 for the whole TTL after the database dies |
| metabase | `/api/health` | **still unverified** | the jar is AOT-compiled and carries no `metabase/api/health*` entry; the monitoring docs do not mention the endpoint. Recorded so the next reader does not repeat the search |
| paperclip | `/` | likely yes | unchanged |

**hedgedoc closed the same day, and its old comment is the lesson.** It read
"HedgeDoc image has no curl/wget; bash is present" — true, and measured again
today: `curl`, `wget`, `nc`, `psql` are all missing. The conclusion drawn from
it was wrong, because `node` is present; HedgeDoc *is* node. The probe is now a
node one-liner against `/status`, which returns `notesCount` and
`registeredUsers` — SELECT counts that cannot be answered without Postgres.
`/_health` returns a static `{"ready":true}` and would have been the tempting
choice: the same trap one layer up.

**superset is now the open instance, and it cannot be fixed the miniflux way.**
`/health` is static by design and Superset publishes no unauthenticated
DB-touching endpoint, so pointing the probe elsewhere means either authenticating
inside a healthcheck or asserting on a login page's HTML. Both are worse than
the honest statement: superset's container health means the web process is up
and says nothing about its metadata database.

"Unverified" was the fee. Two of the six are now verified GOOD, one verified
BAD, one verified PARTIAL, one fixed, one still unknown — which is a different
and much smaller fee than the one this entry was filed with.

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

---

## A second sub-class, named 2026-09-03: TCP-connect-only probes

The audit sweep found three services this file never surveyed, each probing
`:>/dev/tcp/…` — port-open, not service-alive:

| service | probe | honest ceiling? |
| --- | --- | --- |
| smtp_stalwart | `/dev/tcp/127.0.0.1/8080` | no — the image ships curl; a `/healthz`-class HTTP probe is feasible |
| mcp_gateway (mcpo) | `/dev/tcp/127.0.0.1/8000` | maybe — every HTTP route is API-key-gated, TCP may be the honest ceiling; say so in the template if kept |
| qgis_server | `/dev/tcp/127.0.0.1/80` | no — a WMS GetCapabilities GET exists |

The coverage gate only asserts a `healthcheck:` block EXISTS, so this class is
invisible to it by construction. Recorded here rather than fixed blind: each
probe upgrade needs the image's own toolset measured first (the fee's original
lesson).
