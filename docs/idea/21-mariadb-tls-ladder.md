# 21 — MariaDB TLS: why the cheap half does not exist

**Measured 2026-08-22, against the live estate.** Scoping work for REM-217.

## The state, verified first-hand

```
Connections    612 542
Ssl_accepts         81        = 0.013 %
require_secure_transport = 0
have_ssl = YES              ssl_cert = NULL
```

Seven databases (freescout, erpnext, asterisk, wordpress, nextcloud, bookstack,
firefly); five clients running today (wordpress, freescout, firefly, bookstack,
nextcloud). Both live freescout sessions report an empty cipher — plaintext. So
the MariaDB root password and every b2b byte cross `infra_net`, `shared_net` and
`gated_b2b_net` in the clear.

## The transport already works — proven, not assumed

From inside `b2b-bookstack-1`, against `mariadb`, with nothing changed on the
server:

```
PDO::MYSQL_ATTR_SSL_CA => "", MYSQL_ATTR_SSL_VERIFY_SERVER_CERT => false
  -> Ssl_cipher = TLS_AES_256_GCM_SHA384
```

The server negotiates a modern AEAD suite today. Nothing is missing server-side
for *encryption*. The clients simply never ask.

## Why "just turn it on per client" is not available

Laravel — which is freescout, firefly and bookstack, three of the five — reads
exactly one knob, and reads it through a filter:

```php
'options' => extension_loaded('pdo_mysql') ? array_filter([
    Mysql::ATTR_SSL_CA => env('MYSQL_ATTR_SSL_CA'),
```

`array_filter` drops an empty value, so `MYSQL_ATTR_SSL_CA=""` — the exact thing
proven to work above — is filtered out before it reaches PDO. And
`MYSQL_ATTR_SSL_VERIFY_SERVER_CERT` is not exposed by the stock config at all.
The supported path therefore requires a **real CA file path**.

## And there is no CA file to point at

`/var/lib/mysql/*.pem` — nothing. MariaDB 11 generates ephemeral in-memory
material when `ssl_cert` is unset, which is why `have_ssl=YES` and `ssl_cert=NULL`
are true simultaneously. There is no certificate on disk to distribute.

**This is the finding.** An earlier pass of this scoping said the server-side
cert swap "buys nothing on its own, because the name will not match". That was
wrong in the part that matters: it buys the *prerequisite*. Without cert material
on disk there is no CA file, and without a CA file the only supported client knob
cannot be set. Encryption and authentication are not separable here — not because
of security theory, but because of `array_filter`.

The estate's own certs do not help: `tenant_domain` is `pazny.eu`, a public TLD,
so the tree is Let's Encrypt wildcards for `*.pazny.eu`. Clients reach the server
as `mariadb`, the compose service name on a docker network. An LE wildcard has no
such SAN.

## The ladder, in the order it must be climbed

1. **An internal CA and a server certificate with `mariadb` in the SAN.** Not
   mkcert (this is a public-TLD estate, mkcert is not in play), not LE (wrong
   names). A small local CA whose public half can be mounted read-only into
   client containers. This is the step everything else waits on.
2. **`ssl_ca` / `ssl_cert` / `ssl_key` on the server**, replacing the ephemeral
   material. Changes nothing for existing plaintext clients — no outage.
3. **`MYSQL_ATTR_SSL_CA` per Laravel client** (freescout, firefly, bookstack),
   and the equivalents for WordPress (`MYSQL_CLIENT_FLAGS`) and Nextcloud
   (`dbdriveroptions`). One at a time, each verified by watching `Ssl_accepts`
   move.
4. **`require_secure_transport = ON`** — and only here. Today it would refuse
   99.99% of connections; it is the last rung, not the first.

## Correction, 2026-08-23: step 1 is not a new CA, and it is already built

The ladder above called step 1 "a new piece of estate infrastructure — a CA
whose key has to live somewhere, be backed up, and be rotated." That over-
scoped it by reasoning from PKI first principles instead of reading the
sibling role.

**`roles/pazny.postgresql/tasks/main.yml` has done exactly this since June
2026** — `openssl req -new -x509 -days 3650 -nodes -subj "/CN=postgresql"
-addext "subjectAltName=DNS:postgresql,IP:127.0.0.1"`, `creates:`-guarded, plus
a heal step for the dir-mount failure root-caused live on 2026-07-19. No
collection, no key custody problem, no rotation ceremony: rotation is deleting
the pair and re-running.

And a **self-signed certificate is its own CA**. A client handed `server.crt`
as `MYSQL_ATTR_SSL_CA` gets a chain that validates AND a host name that
matches, provided `mariadb` is in the SAN. There was never a second object to
build.

Rungs 1 and 2 are **shipped** as of `mariadb_ssl_enabled` in
`default.config.yml` — the cert exists on disk and the server reads it, with
`require_secure_transport` deliberately absent and gated absent
(`tests/anatomy/test_mariadb_tls_material.py`). What remains is rung 3, the
five clients, and that part of the estimate stands.

The lesson is cheaper than the correction: **look for the pattern in the estate
before designing one.** The scoping pass read the Laravel source and the live
server and did not read the role next door.

## Why rung 3 is still not an afternoon

Rung 3 is five services with five different configuration contracts, each a
compose change plus a converge, each capable of leaving a service unable to
reach its database. Rung 4 is a cliff.

And rung 3 carries a trap the PostgreSQL work has already sprung once: **the
same sslmode word means different things in different client libraries**
(`docs/doctrine/foreign-properties.md` §5). Expect the MySQL side to have its
own version — PDO, WordPress's `MYSQL_CLIENT_FLAGS`, and Nextcloud's
`dbdriveroptions` are three separate contracts, not one spelled three ways.

What makes it worth doing anyway is the number at the top, which has only
grown while this was scoped: 108 encrypted handshakes out of 635,888
connections on 2026-08-23, against 81 of 612,542 the day before.

## What was NOT done

No compose file was touched. The proof above was run inside a container and
changed nothing. Turning on TLS for one client without step 1 would mean editing
Laravel's vendored config, which is neither supported nor survivable across an
image update.

## Correction, 2026-08-23 (second): rung 3 is five contracts, not three plus two

The ladder said *"`MYSQL_ATTR_SSL_CA` per Laravel client (freescout, firefly,
bookstack), and the equivalents for WordPress and Nextcloud"*. Read in the
running images before touching anything, that is true of **one** of the three
Laravel apps:

| client | knob | read at |
| --- | --- | --- |
| bookstack | `MYSQL_ATTR_SSL_CA` | `/app/www/app/Config/database.php:84` |
| freescout | `DB_MYSQL_ATTR_SSL_CA` | `/www/html/config/database.php:56` |
| firefly | `MYSQL_SSL_CA` **and** `MYSQL_USE_SSL` | `…/database.php:43` and `:49` |
| wordpress | `MYSQL_CLIENT_FLAGS` via `WORDPRESS_CONFIG_EXTRA` | `class-wpdb.php:1959` |
| nextcloud | `occ config:system:set dbdriveroptions 1009` | `ConnectionFactory.php:201` |

Three forks of one framework, three names — and firefly gates the entire SSL
block on a **second** variable, which this estate already sets to `false`. A CA
handed to firefly without `MYSQL_USE_SSL=true` would render, resolve, appear in
`docker inspect`, and be skipped: `docs/hidden_fees/28` in advance.

The original claim came from reading one config and generalising. Same shortcut
as `no-verify` in Outline and `?sslmode=` in HedgeDoc; the fix is the same, and
it is cheap: **open the config of the thing you are about to change.**

### What was measured before anything was written

1. **The certificate validates as its own CA and the name matches.**
   `openssl s_client -starttls mysql -CAfile server.crt -verify_hostname mariadb`
   → `Verify return code: 0`, TLSv1.3. And from inside the fabric,
   `mariadb -h mariadb --ssl-ca=… --ssl-verify-server-cert` → TLS_AES_256_GCM_SHA384.
2. **Verification really engages** — pointing `--ssl-ca` at a file that is not a
   CA is *refused* (`TLS/SSL error: no certificate or crl found`). Without that
   control the first result proves nothing.
3. **And `--ssl-verify-server-cert` with NO CA quietly succeeds** — the MariaDB
   client does not verify when it has nothing to verify against. A verification
   flag that is inert unless paired: worth knowing before trusting one.
4. **pdo_mysql fails CLOSED.** A bad CA path gives
   `SQLSTATE[HY000] [2002] Cannot connect to MySQL using SSL`; it never falls
   back to plaintext. So a half-landed rung 3 is a visible outage, not a silent
   downgrade — which is what makes shipping all five at once acceptable.
5. **WordPress can encrypt without a CA.** `MYSQLI_CLIENT_SSL` alone, measured
   in the running container, negotiates TLS_AES_256_GCM_SHA384. It cannot
   *verify*: `wpdb` never calls `mysqli_ssl_set`, so no CA is mounted for it —
   a file nothing reads is the defect, not a precaution.

### What rung 3 does NOT close

- **WordPress is encrypted but unauthenticated.** An active MITM on the docker
  fabric could still impersonate `mariadb` to it. The route is php.ini
  `mysqli.default_ca` plus `MYSQLI_CLIENT_SSL_VERIFY_SERVER_CERT`; untested,
  so not shipped with this rung.
- **Nothing here proves adoption.** The configuration being coherent is
  `tests/anatomy/test_mariadb_client_tls.py`; whether a client negotiated TLS
  is `tools/tls-uptake.py --window N`, which reports the fraction of
  connections opened in the last N seconds that were encrypted. On
  2026-08-23, before the rung: **1 of 9**.
- **Rung 4 stays gated absent.** `require_secure_transport` would refuse every
  client that has not moved, and a gate now fails if it appears.
