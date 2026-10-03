# nos-forum

Chat channels and a minimalist forum on SpacetimeDB, signed in through Authentik.
Source and spec: github.com/pazny/nos-forum (AGPL-3.0). v0.1 = text + forum, no calls.

| | |
|---|---|
| URL | `https://forum.<tld>` (`nos_forum_domain`) |
| Role | `roles/pazny.nos_forum` (iiab stack), plugin `nos-forum-base` |
| Container | `iiab-nos-forum-1`, `127.0.0.1:5091` (`nos_forum_port`) |
| Needs | `install_spacetimedb: true`, `install_authentik: true` (the converge refuses otherwise) |
| Edge | main router → forum-web (native OIDC, no forward-auth); lane `/stdb` → `spacetimedb:3000`, exact paths only (`roles/pazny.traefik/vars/main.yml`) |
| Data | SpacetimeDB database `nos-forum`; owner CLI token in `nos_forum_data_dir/cli` |
| GDPR | `docs/compliance/nos-forum.md` |

## Image

One image carries forum-web and the module wasm. No release is published yet, so set
`nos_forum_src_dir` to a local checkout and the role builds
`{{ nos_forum_image }}:{{ nos_forum_version }}` from it. The post step copies
`/app/module.wasm` out of the running container and publishes it when its hash changed.

## Owner identity

The spacetime CLI runs as a throwaway container with `HOME=nos_forum_data_dir/cli`; its
server-issued token there owns the database. Another identity cannot republish (403).
Lose that directory and the module can only be replaced by deleting the database.

## DNS

`forum` proxied (orange) at Cloudflare. No new ports in v0.1. Calls (v0.2) add a
DNS-only `media` record and router forwards; see the spec's `04-realtime-and-media.md`.

## Authentik key rotation

SpacetimeDB caches Authentik's JWKS per issuer and does not refetch on an unknown `kid`.
After rotating the signing key, restart `infra-spacetimedb-1` or every forum login fails.
