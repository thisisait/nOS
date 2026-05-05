# wordpress-base

Service plugin for WordPress under nOS. Wires Authentik SSO via the
[openid-connect-generic](https://wordpress.org/plugins/daggerhart-openid-connect-generic/)
WordPress plugin, configured at runtime by the mu-plugin `oidc-bootstrap.php`
that the role drops at `wp-content/mu-plugins/`.

## Tier

**4 (guest)** — public-facing site; anonymous visitors reach published
content without login. The Authentik tier guard applies to wp-admin only.

## What this plugin does

- Renders a compose extension at `{{ stacks_dir }}/iiab/overrides/wordpress-base.yml`
  carrying the `WP_OIDC_*` env vars + the mkcert CA mount conditional.
- Declares the Authentik OIDC client (id, secret, redirect URIs, scopes)
  for the loader's authentik-base aggregator to harvest into the
  `10-oidc-apps` blueprint.
- Declares the GDPR Article 30 row (legitimate_interests, retention 365d).
- Provides the Wing `/hub` deep-link card.

## What this plugin does NOT do

- WordPress install (DB schema, salts, themes) — that's `pazny.wordpress`.
- DB provisioning (MariaDB) — `pazny.mariadb` owns it.
- Image pin / mem_limit / port — those stay in the role's compose template.

## Status

Ships in Phase 1 mop-up (2026-05-05). Worker U6 was scoped 8 plugins but
ran out of agent quota at 7; this manifest closes the batch.

## Health

`https://{{ wordpress_domain }}/wp-login.php` — 200 OK once WP is up,
even before SSO is wired (login button appears after Authentik bootstrap).
