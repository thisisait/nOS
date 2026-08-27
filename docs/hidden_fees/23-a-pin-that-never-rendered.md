# 23 — A pin that never rendered

**Found 2026-08-23, while working REM-217's cheapest rung.**

On 2026-06-14 a commit closed the PostgreSQL client half of REM-009:

```
fix(postgresql): require-pin hedgedoc+paperclip SSL
- conditional require/prefer: fails closed on Darwin server-TLS
- gate test_hedgedoc_paperclip_require_pin pins both connection strings
```

Two months and nine days later, REM-217 measured the estate: 23 of 42
PostgreSQL backends in cleartext, including **Infisical — the secrets vault**
— and 22 of Authentik's.

## The mechanism

Every client decides with the same conditional:

```jinja
sslmode={{ 'require' if (postgresql_ssl_enabled | default(false)) else 'prefer' }}
```

`postgresql_ssl_enabled` is declared in **`roles/pazny.postgresql/defaults/
main.yml`** as `{{ ansible_os_family == 'Darwin' }}`. The five roles that read
it — authentik (×2), hedgedoc, infisical, paperclip — are **different roles**,
and a role default is not in scope for another role's render. So in every one
of them the name resolved to nothing, `| default(false)` answered, and the
template took the `prefer` branch.

Not inferred. Read out of the rendered artifacts on a macOS host:

```
~/stacks/b2b/overrides/hedgedoc.yml       sslmode=prefer     (rendered 18 Aug)
~/stacks/devops/overrides/paperclip.yml   sslmode=prefer
~/stacks/infra/overrides/authentik.yml    SSLMODE: "prefer"  ×2
docker inspect devops-paperclip-1         sslmode=prefer     (live)

~/stacks/infra/overrides/postgresql.yml   ssl=on             ← the server, two dirs away
```

The **server** got its TLS, because the postgresql role can see its own
default. Every client silently did not.

## Why it survived a gate

`tests/anatomy/test_postgresql_ssl.py` asserted the exact string
`sslmode={{ 'require' if (postgresql_ssl_enabled | default(false)) else
'prefer' }}` in the templates. The string was there. It was there the whole
time. **A shape gate cannot see a variable that does not resolve** — it reads
the template, and the template was correct.

This is CLAUDE.md's own division of labour failing in the exact direction it
warns about: *pytest owns the shape, `--tags verify` owns the effect, and none
may claim another's job.* Nothing owned the effect, so nothing checked it.

## The part that is worse than the plaintext

`require` was the WRONG spelling for three of the five clients anyway.
HedgeDoc, Outline and Infisical are node-postgres, where `require` leaves
`rejectUnauthorized` at Node's default of **true** — so it verifies, rejects
the role's self-signed certificate, and the service does not start. In libpq
`require` means the opposite: encrypt, do not verify.

So the dead pin was also a **latent outage**. Had the variable ever resolved,
the June commit would have taken HedgeDoc down. Two defects cancelled each
other for nine weeks and the estate read as green.

## Fixed

- `postgresql_ssl_enabled` moved to **play scope** in `default.config.yml`.
  The role default stays as a fallback so the role remains usable alone.
- Per-client spelling by driver family, each with its reason in the template:
  `require` for libpq (authentik, paperclip, miniflux, postgres_exporter),
  `no-verify` for node-postgres (hedgedoc, outline, infisical).
  Driver family established **empirically** where possible — a client that
  negotiated TLS under `prefer` is libpq-family, because a node-postgres
  client never upgrades opportunistically.
- Outline's `PGSSLMODE: "disable"` — upstream `.env.sample` boilerplate carried
  in with the role extraction, never a decision — now encrypts.
- `prefer` is no longer an acceptable value on the server-TLS branch anywhere.
  It PERMITS plaintext, and measured on this estate the permission was taken by
  every client whose driver does not upgrade on its own.

## Gated, twice, and neither is the old shape gate

- `test_a_role_default_is_not_read_across_roles.py` — a **constant** fallback
  may not stand in for another role's **computed** declaration. Narrow on
  purpose: `hedgedoc_db_name | default('hedgedoc')` is harmless because the
  fallback IS the declaration; `postgresql_ssl_enabled | default(false)`
  against `{{ ansible_os_family == 'Darwin' }}` is not.
- `test_postgresql_ssl.py`, rewritten to pin the PROPERTY — every client
  declares an sslmode explicitly, the server-TLS branch must encrypt, and the
  variable it keys on must be at play scope.
- `tools/tls-uptake.py` is the effect half and it existed before any of these
  fixes, so no rung of this verifies itself.

Both gates proven in the failing direction: remove the `default.config.yml`
line and they name the four templates.

## What is still owed

- ~~**None of this is verified live.**~~ PAID 2026-08-27: `tools/tls-uptake.py
  --window 20` reads `postgresql GREEN — 34 of 34 backends on the fabric =
  100.0%` (one more on the unix socket, not counted). The number moved from
  38.5%.
- ~~**The 22 cleartext Authentik backends are still not explained.**~~ Closed
  by the same read: `authentik x20 seen 80/80` and `authentik x5 seen 80/80`,
  no plaintext row. The second client path honours `require`, so the "different
  finding" branch did not happen.
- ~~**HedgeDoc's `no-verify` may be inert.**~~ Not inert: `postgres self-test
  ok hedgedoc` — the reader asked HedgeDoc's own session, because its Sequelize
  pool drops the connection between queries and never appears in a sample.
  Fee 28 replaced the URL parameter with `config.json`'s `dialectOptions.ssl`.
- **Linux still has no PostgreSQL TLS at all.** `postgresql_ssl_enabled` is
  false there because PG refuses a host-user-owned key. That leg is undone, not
  unset, and on Linux every one of these clients is cleartext by design.
- **Twelve more cross-role reads exist** (`stalwart_*` in wing, `cortex_port`,
  `ollama_models_dir`, `backup_verify_script_path`). All are currently benign —
  the fallback matches the declaration, or the value is a path spelled two ways
  — except `backup_verify_script_path`, where wing guesses `~/.nos/` against
  `{{ backup_home_dir }}/`. The gate deliberately does not fire on those, so
  they stay owed rather than fixed.
