# Foreign properties — upstream facts our work cannot remove

> Canonical. This document owns the rules that are true about **someone else's**
> software: images, binaries and protocols this estate consumes but does not
> build. Cited from code; every `§` is resolved by `tools/doctrine-cite.py`.
> Section numbers are stable (gaps included). The full measured stories live in
> [`docs/foreign-properties-companion.md`](../foreign-properties-companion.md),
> under the same numbers — this file keeps the rule, the refusal and the
> accommodation; the companion keeps the derivation.

## 1. What belongs here

A rule earns a section only when all three hold:

1. it is a property of an artifact we do not build (an upstream image, binary
   or protocol);
2. **no change on our side removes it** — we can only route around it;
3. getting it wrong produces a *confident wrong reading* — a red that is not a
   fault, or a green that is not health — rather than an obvious crash.

Everything failing (2) belongs elsewhere: ours-and-fixable is a fix,
ours-and-remembered is a gate (`docs/doctrine/gates.md`), and a rule about the
operator's own machine is a runbook step (`docs/nos-cli.md`). A section here is
a **permanent accommodation**, so it names both the accommodation and the code
that performs it; a paragraph with no performing code is a claim, not doctrine.

## 2. A healthcheck in a minimal image may be unable to RUN

`scratch`, distroless and rust-slim images ship the service binary and little
else — no `wget`, no `curl`, no `python`, sometimes no shell at all. A
`CMD wget --spider …` healthcheck in such an image does not *fail*; it never
starts:

```
OCI runtime exec failed: exec failed: unable to start container process:
exec: "wget": executable file not found in $PATH
```

Docker records that as `(unhealthy)`, and at `docker ps` it is indistinguishable
from a service that is genuinely down. Two measured instances: `qdrant/qdrant:v1.13`
logged `wget: not found` 955× and gated off the apps post-hooks (2026-05-03);
the 2026-08-06 `redis_exporter` bump moved upstream's default image to `scratch`
and failed a converge after 1200 s while the exporter served metrics on `:9121`
the entire time.

### 2.1 The accommodation, in order of preference

1. **Pin a tag that still carries a shell**, where upstream publishes one —
   the `-alpine` suffix on `redis_exporter_version` (`default.config.yml`) is
   what keeps the existing `wget --spider` probe in
   `roles/pazny.grafana/templates/compose.yml.j2` executable. The numeric part
   moves with the pin sweep (this doctrine quoted `v1.88.0` and was stale
   within four days); the suffix is the doctrine. Dropping `-alpine` re-opens
   the 2026-08-06 failure exactly.
2. **Probe with what the image HAS** — bash-only: `["CMD", "bash", "-c",
   ":>/dev/tcp/127.0.0.1/<port>"]`, TCP liveness via bash's built-in
   pseudo-device (`apps/qdrant.yml`).
3. **No shell at all: declare no healthcheck** and rely on
   `restart: unless-stopped`. A check that cannot execute is worse than no
   check, because it manufactures a verdict.

### 2.2 A check that could not run is reported, never excused

`files/anatomy/scripts/stack-health-probe.py` inspects the health log of each
container it has already classified `failed` and annotates the ones whose check
could not execute (`blob_says_check_could_not_run`). The container **stays
failed** — a container whose health cannot be established is not a container
known to be well. What changes is that the line says which of the two broke.

## 3. `lscr.io/linuxserver/code-server` speaks plain HTTP on 8443

The port number says TLS; the listener does not. The LSIO image serves plain
HTTP on container port 8443 unless started with `--cert`, which nOS does not
pass. Traefik configured to speak HTTPS to it answered with
`tls_get_more_records: packet length too long` and a user-visible 502/404
(2026-05-04, `code.pazny.eu`).

### 3.1 The accommodation — an upstream is HTTP until measured otherwise

`traefik_https_upstream_ids` (`roles/pazny.traefik/vars/main.yml`) names only
services whose **own container listener** is TLS. It is `[]` today, and empty is
the current correct answer rather than a gap: every routed upstream in this
estate terminates TLS at the edge and speaks HTTP behind it. An id may be added
only with measured evidence of an internal TLS listener — **a port number is not
evidence**. Gate: `tests/anatomy/test_traefik_https_upstream_binds_tls.py`,
which exists to refuse a careless addition, not to assert a population.

## 4. OpenClaw's gateway service discards its own stderr

`openclaw gateway install` hardwires `StandardErrorPath: /dev/null` into the
launchd plist, offers no flag to change it, and regenerates the plist on every
reinstall — so an edit does not survive, and interposing a wrapper would mean
owning a file upstream rewrites (the trade §1 says not to make).

**The rule.** When `ai.openclaw.gateway` reports a non-zero status, do not look
for a log — there is not one. Extract `ProgramArguments` from the plist and run
them directly; that is the only place the refusal is legible. The cause is
usually the one `roles/pazny.openclaw/tasks/main.yml` now reconciles: `npm
install -g` follows the current node, so every nvm bump strands the install the
plist still points at. (The exit-78 loop this cost: companion §4.)

## 5. `sslmode=require` means opposite things in libpq and node-postgres

Both accept the word. They disagree about what it promises.

| library | `require` | encrypting mode against a self-signed cert |
| --- | --- | --- |
| libpq — psycopg, Ruby `pg`, Go `lib/pq`/`pgx`, JDBC | encrypt, do **not** verify the certificate | `require` |
| node-postgres — via `pg-connection-string` | encrypt **and** verify; `rejectUnauthorized` is left at Node's default of `true` | `no-verify` |

Only `no-verify` sets `rejectUnauthorized: false` on the Node side. So the same
connection string that gives a Django service transport encryption gives a
Node service `SELF_SIGNED_CERT_IN_CHAIN` and a container that will not start.

There is a second half, and it is the one that stayed invisible here: under
`sslmode=prefer`, **libpq upgrades opportunistically and node-postgres does
not.** node-postgres treats anything short of an explicit ssl configuration as
no SSL at all. A server with `ssl=on` therefore serves TLS to some of its
clients and cleartext to others, with every client configured identically.
(REM-217, 23 of 42 backends cleartext — the vault among them: companion §5.)

### 5.1 There is a third contract: the application's own

Outline validates `PGSSLMODE` against the **libpq** enum — rejecting
`no-verify`, the only correct value for raw node-postgres — and then maps every
value except `disable` to encrypt-without-verify itself. So `require` is
correct for a Node application, arrived at by the libpq rule, which is exactly
why the runtime shortcut fails. (Full derivation: companion §5.1.)

**The rule that generalises: the contract belongs to whoever PARSES the string,
not to the driver underneath it.** A connection URL handed straight to the
driver takes the driver's contract; an env var the application reads first
takes the application's. `PGSSLMODE` is an application variable and reads
nothing like one.

**The accommodation.** Client sslmode is chosen per PARSER, not per runtime and
not per estate policy, and the choice is recorded with its reason in
`tests/anatomy/test_postgresql_ssl.py::CLIENTS`. `prefer` is not an acceptable
value on the server-TLS branch for any client, because it is precisely the mode
whose meaning splits.

**And it is settled empirically where it can be.** A client observed
negotiating TLS while set to `prefer` is libpq-family — a node-postgres client
never does. `tools/tls-uptake.py` reads `pg_stat_ssl` per backend, so the
question is answerable in one command rather than from an image's language.

**Not ours to fix.** The deviation is `pg-connection-string`'s, deliberate and
years old. We can only spell each client's mode correctly.

### 5.2 And a fourth: an ORM in between that discards what it does not know

Sequelize's postgres dialect copies `dialectOptions` into the pg client through
an **allow-list** (`sequelize/lib/dialects/postgres/connection-manager.js:96`).
`sslmode` is not on it — HedgeDoc's well-formed `?sslmode=no-verify` was picked
out and dropped in silence, and no layer had a reason to complain. `ssl` **is**
on the list, but pg requires an object there, and **a query string cannot
express an object** — the setting is not expressible in the connection URL at
all, at any spelling. (Full derivation: companion §5.2.)

**The accommodation.** Where the URL cannot carry the setting, the URL must not
appear to. HedgeDoc's is now clean and the control is a mounted `config.json`
(`db.dialectOptions.ssl`) whose header carries this derivation; the gate class
is `test_postgresql_ssl.py::OUT_OF_BAND`, which requires the URL to *stay*
clean. An inert pin that reads as a control is the failure of
`docs/hidden_fees/23`, and this line had by then been wrong three times in a
row — each correction confident, each from a different layer of the stack.

### 5.3 A third allow-list, and the one that resolves

FreeScout's CA was dropped twice more: the image builds `.env` from a fixed
variable set, and Laravel's config cache means `env()` keeps returning a value
the application has never seen — a *resolving* variable hands you a false
confirmation. (Both measurements: companion §5.3.)

**The accommodation, and it is a rule about probes rather than about upstreams:**
`env()` and `config()` are two different questions and only the second is the
application's contract. A probe must boot the application's own kernel and read
what it **resolves** — `tools/tls-uptake.py`'s `_LARAVEL_PROBE` does — because a
configuration value has as many plausible readings as there are layers above it,
and only the last one is true.

## 7. VirtioFS answers `statfs` from the wrong volume

MEASURED 2026-08-31. `observability-loki-1` bind-mounts
`/Volumes/SSD1TB/nOS/data/platform/services/loki/storage` at `/loki`. The SSD
is 931 GiB, 53% used, 434 GiB free. A container at that same mount is told:

    460.4G total   394.3G used   66.1G avail   86%   /loki

`460.4G` is the size of the **internal** volume. Docker Desktop's VirtioFS
answers `statfs()` for a bind-mounted host path with the figures of the disk
Docker itself lives on, not the disk the path is on. (What this cost Loki —
fifty days of HTTP 500 over a 66 MB WAL: companion §7.)

**Not ours to fix, and the shape generalises.** Any container that decides
something from free space on an external bind mount is reading about Docker's
disk instead. Loki is the one that happens to have a guard; a database that
refuses to start below a free-space floor would do the same thing.

What IS ours: never diagnose one of these from the host's `df`. Ask the
container — `docker run --rm -v <host path>:/x alpine df -h /x` — because the
number the service acts on is the one it is told, not the one that is true.

Two recovery facts, both learned the slow way: the Loki ingester does not
re-read the disk after it latches, and Alloy's `loki.write` client backs off
permanently once refused. Freeing space changes nothing until **both** are
restarted, in that order.

## 8. A single-FILE bind mount does not survive an atomic replace

MEASURED 2026-09-01, with a throwaway container rather than inferred:

    docker run -d --name p -v "$T/f.txt:/f.txt:ro" alpine:3 sleep 600

| what the host does | what the container sees |
|---|---|
| in-place write (`echo v2 > f.txt`) | `v2` — immediately |
| atomic rename (`echo v3 > .tmp; mv .tmp f.txt`) | **`No such file or directory`** |
| `docker restart p` | `v3` |

A bind mount of a single file binds the **inode**. A rename puts a new inode at
the path, and the container is left pointing at the old one — which is now
unlinked, so the path answers ENOENT. Not stale content. **Gone.**

This is not an edge case for us, it is the normal path: Ansible's `template:`
and `copy:` write a temp file and rename it. So **every converge that changes
the content of a bind-mounted config file breaks that mount** until the
container is restarted. A directory mount is unaffected — the directory inode
does not change — which is why this is invisible in most of the estate and why
the config files rendered as single files are exactly where it bites.

### 8.1 What it cost, and the shape worth carrying

**Generalises to any ordering: a step that repairs a condition must not sit
behind the gate that condition fails.** The reconciler that re-binds these
mounts (`tools/reload-stale-config.py`) now runs inside
`tasks/stacks/wait-stacks-healthy.yml` before the poll loop — every bring-up
flow routes through that file. Gate:
`tests/anatomy/test_the_repair_runs_before_the_health_gate.py`. (The Loki
converge deadlock that taught it: companion §8.1.)

## 9. A libSQL store reads as EMPTY through stock `sqlite3`

MEASURED 2026-09-01: stock `sqlite3` answers `count(*) = 0` on KEAP's libSQL
`embeddings` table — no error, no warning — while
`GET /agent/v1/embeddings/pending` shows the corpus fully embedded.

**The rule is the estate's own, and it generalises past libSQL:** a count of
zero from a tool that cannot parse the schema is not a measurement. Ask the
process that owns the store. Same shape as §7 — never diagnose from the host's
`df` when the container is told a different number. (The near-miss false
data-loss record, and the ANN-leg corollary: companion §9.)
