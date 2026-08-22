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

## Why this is not an afternoon

Step 1 is a new piece of estate infrastructure — a CA whose key has to live
somewhere, be backed up, and be rotated. Steps 3 is five services with five
different configuration contracts, each a compose change plus a converge, each
capable of leaving a service unable to reach its database. Step 4 is a cliff.

What makes it worth doing anyway is the number at the top: the root password
crosses three networks 612,542 times, and 81 of those were encrypted.

## What was NOT done

No compose file was touched. The proof above was run inside a container and
changed nothing. Turning on TLS for one client without step 1 would mean editing
Laravel's vendored config, which is neither supported nor survivable across an
image update.
