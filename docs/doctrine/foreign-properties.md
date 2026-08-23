# Foreign properties — upstream facts our work cannot remove

> Canonical. This document owns the rules that are true about **someone else's**
> software: images, binaries and protocols this estate consumes but does not
> build. Cited from code; every `§` is resolved by `tools/doctrine-cite.py`.

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

`openclaw gateway install` writes `~/Library/LaunchAgents/ai.openclaw.gateway.plist`
with:

```xml
<key>StandardOutPath</key>  <string>~/Library/Logs/openclaw/gateway.log</string>
<key>StandardErrorPath</key><string>/dev/null</string>
```

There is no flag to change it — `gateway install` accepts `--force --port
--runtime --token --wrapper` and nothing else — and the plist is regenerated on
every reinstall, so an edit does not survive.

**What that costs.** On 2026-08-11 the gateway had been failing with exit **78**
(`EX_CONFIG`) with `KeepAlive: true`, so launchd restarted it in a loop. Every
one of those runs printed the reason and every one of them wrote it to
`/dev/null`. `launchctl list` showed the number; nothing on the machine showed
the sentence. It became readable only by running the plist's own
`ProgramArguments` by hand:

```
Your OpenClaw config was written by version 2026.7.1-2, but this command is
running 2026.6.11. Refusing to run automatic gateway startup migrations…
```

**The rule.** When `ai.openclaw.gateway` reports a non-zero status, do not look
for a log — there is not one. Extract `ProgramArguments` from the plist and run
them directly; that is the only place the refusal is legible. The cause is
usually the one `roles/pazny.openclaw/tasks/main.yml` now reconciles: `npm
install -g` follows the current node, so every nvm bump strands the install the
plist still points at.

**Not ours to fix.** A wrapper of our own could tee stderr, but the plist is
regenerated by `gateway install --force` — the command we deliberately rely on,
because the service file's shape is theirs to change. Interposing would mean
owning a file upstream rewrites, which is the trade §1 says not to make.

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

**What that cost.** REM-217, measured 2026-08-22 against a PostgreSQL with
`ssl=on`: 23 of 42 backends in cleartext. The encrypted ones were paperclip,
metabase, miniflux and the Authentik worker — all libpq-family. The cleartext
ones were Outline, HedgeDoc and **Infisical, the secrets vault** — all
node-postgres. Nothing was misconfigured relative to the intent; the intent was
expressed in a word that does not mean one thing.

### 5.1 There is a third contract: the application's own

Learned by restart-looping Outline on 2026-08-23, one day after §5 was written.
Outline was classified `no-verify` because it runs on Node. It refused to start:

```
Environment configuration is invalid, please check the following:
- PGSSLMODE must be one of the following values:
  disable, allow, require, prefer, verify-ca, verify-full
```

**Outline owns that string, not node-postgres.** It validates against the
**libpq** enum — so `no-verify`, which is the only correct value for raw
node-postgres, is rejected outright — and then maps it itself
(`server/storage/database.ts`, v1.9.2):

```ts
const isSSLDisabled = env.PGSSLMODE === "disable";
ssl: env.isProduction && !isSSLDisabled ? { rejectUnauthorized: false } : false
```

Every value except `disable` means the same thing there: encrypt, do not
verify. So `require` is correct — arrived at by the libpq rule, for a Node
application, which is exactly why the shortcut fails.

**The rule that generalises: the contract belongs to whoever PARSES the string,
not to the driver underneath it.** A connection URL handed straight to the
driver takes the driver's contract; an env var the application reads first
takes the application's. `PGSSLMODE` is an application variable and reads
nothing like one.

**How to settle it without guessing.** The enum in the error message is the
application's own validator; the mapping is one grep in its source. Both were
available before the change and neither was consulted — the classification was
made from the runtime, which is the one fact that does not decide it.

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

Learned by HedgeDoc, the same afternoon, and it is the one that breaks the
pattern of the three above. Those are all about the value being *misread*.
This one was never read at all.

HedgeDoc's URL rendered `?sslmode=no-verify` — correct by §5, resolvable by
scope, present in the container's environment. `pg_stat_ssl` still reported its
backend `ssl=f`: the one plaintext PostgreSQL backend of forty.

The path from that URL to the driver has a filter in it. Sequelize parses the
query string into `dialectOptions` verbatim, and the postgres dialect then
copies `dialectOptions` into the pg client through an **allow-list**
(`sequelize/lib/dialects/postgres/connection-manager.js:96`):

```js
_.merge(connectionConfig, _.pick(config.dialectOptions, [
  'application_name', 'ssl', 'client_encoding', /* … */
]))
```

`sslmode` is not on that list. The value was picked out and dropped, in
silence, and no layer had a reason to complain: the URL was well-formed, the
parameter was well-spelled, and the driver simply never saw it.

`ssl` **is** on the list — but it must be an object, because pg does
`Object.assign(options, this.ssl)` for any value that is not literally `true`,
so a string spreads into character keys and leaves `rejectUnauthorized` at
Node's default. **A query string cannot express an object.** The setting is
therefore not expressible in the connection URL at all, at any spelling.

**The accommodation.** Where the URL cannot carry the setting, the URL must not
appear to. HedgeDoc's is now clean and the control is a mounted `config.json`
(`db.dialectOptions.ssl`) whose header carries this derivation; the gate class
is `test_postgresql_ssl.py::OUT_OF_BAND`, which requires the URL to *stay*
clean. An inert pin that reads as a control is the failure of
`docs/hidden_fees/23`, and this line had by then been wrong three times in a
row — each correction confident, each from a different layer of the stack.

**How to settle it without guessing.** Read the layer that *consumes* the
option, not the one that accepts it. Two greps in `node_modules` answered in
under a minute what two rounds of reasoning about driver families got wrong.

**Not ours to fix.** A defensive allow-list is a reasonable thing for an ORM to
have. What is ours is not to keep writing configuration into a channel we have
not checked is connected.

### 5.3 A third allow-list, and the one that resolves

HedgeDoc's `sslmode` was dropped by an ORM's allow-list (§5.2). FreeScout's CA
was dropped by two more, and the second is the instructive one.

**The container image's.** `nfrastack/freescout` builds the application's `.env`
from a fixed set of variables. `DB_MYSQL_ATTR_SSL_CA` is not among them, so the
value never reached the file. The image does support arbitrary passthrough —
any `ENV_*` variable is written into `.env`
(`/container/functions/30-laravel:212`, README line 326) — but only under that
prefix.

**And the framework's own cache.** This is the part worth carrying:

```
env("DB_MYSQL_ATTR_SSL_CA")                  '/nos-certs/mariadb-ca.crt'
config("database.connections.mysql.options") {"1013": true}
```

Both measured in the running container, seconds apart. Laravel caches its
resolved configuration (`bootstrap/cache/config.php`); once cached, `env()` is
never consulted for a config value again. So the variable **resolves** — it is
present, correctly spelled, and returned by the function whose name suggests it
is the answer — and the application has never seen it.

**Why this one is worse than §5.2.** A dropped parameter leaves no trace to
find. A *resolving* one hands you a confirmation. Reading `env(...)` in the
container returns the path; the container's environment shows the path; a probe
built from either says `encrypted`. FreeScout ran plaintext behind all three,
and behind a healthcheck that reported healthy, while a reader written that same
afternoon called it green.

**The accommodation, and it is a rule about probes rather than about upstreams:**
`env()` and `config()` are two different questions and only the second is the
application's contract. A probe must boot the application's own kernel and read
what it **resolves** — `tools/tls-uptake.py`'s `_LARAVEL_PROBE` does — because a
configuration value has as many plausible readings as there are layers above it,
and only the last one is true.

**Not ours to fix.** A config cache is a correct optimisation, and an image
curating its `.env` is a defensible boundary with a documented door. What is
ours is to stop asking the layer that is easy to reach.
