# v0.7 SEC — WordPress unauthenticated endpoint hardening

Status: **PLAN** (not implemented). Branch: `feat/v0.7-overnight`.
Confirmed item. Authoritative attack-surface source: `docs/llm/security/attack-surface.json`
`web_ui_unauthenticated_paths` lists three WordPress entries with `auth: none`.

## Problem / why

The WordPress site (iiab stack, role `pazny.wordpress`, plugin
`files/anatomy/plugins/wordpress-base`) is reachable at the Traefik edge on
`wordpress.<tld>` with three unauthenticated endpoints that are live attack
surface (verbatim from `attack-surface.json` lines 51–53):

| Path | Risk | Auth today |
|---|---|---|
| `/xmlrpc.php` | XML-RPC abuse — brute-force amplification, `pingback.ping` SSRF/DDoS reflection, `system.multicall` credential-stuffing | none |
| `/wp-json/wp/v2/users` | User enumeration — leaks login names (`slug`) for every author to anonymous callers | none |
| `/wp-login.php` | Login form — brute-force target | none |

WordPress is the **only public-facing service by design** (its GDPR block in
`wordpress-base/plugin.yml` lists `anonymous_visitors` as a data subject, legal
basis `legitimate_interests`). Unlike Tier-1 services it is intentionally NOT
behind `forward_auth` — the README is explicit ("Proxy-auth / `forward_auth` is
intentionally NOT used … gives WP real user objects"). So the standard nOS gate
(`authentik@file` middleware) is the wrong tool here: it would break public
content AND the OIDC round-trip, which lands on
`/wp-admin/admin-ajax.php?action=openid-connect-authorize` (the registered
redirect_uri in `wordpress-base/plugin.yml`).

Hardening therefore has to happen **inside WordPress**, surgically, without
breaking: (a) anonymous read of public posts/pages, (b) the OIDC login flow,
(c) the devlog REST writes that use an Application Password
(`files/devlog-app-passwords.php` + `tasks/devlog.yml`), (d) `/wp-login.php` as
the **documented break-glass** (`wordpress-base/plugin.yml`
`autologin.break_glass: "/wp-login.php"`, `docs/break-glass-runbook.md`).

### Constraint that drives the design

`/wp-login.php` MUST stay reachable — it is the break-glass when Authentik is
down. So the fix is NOT "block the login form"; it is "remove the abusable
behaviour": kill XML-RPC, stop REST user enumeration for anonymous callers, and
strip author-enumeration vectors (`?author=N` redirect, REST `users` for anon,
oEmbed author data, RSD/WLW link headers). The login form survives; only
brute-force *amplifiers* and *enumeration* go away.

## Approach

Ship a new **must-use plugin** `security-hardening.php` staged into the existing
mu-plugins directory mount. This is the in-pattern mechanism: the role already
stages `oidc-bootstrap.php`, `devlog-app-passwords.php`, `rbac-role-sync.php`
into `{{ stacks_dir }}/iiab/wordpress/mu-plugins/` and mounts that dir read-only
at `/var/www/html/wp-content/mu-plugins`. The blank-safety gate
(`tests/anatomy/test_wordpress_mu_plugins_blank_safety.py`) **already enforces**
that every `*.php` in `roles/pazny.wordpress/files/` gets a staging copy task
that runs before the compose render — so adding the file + a copy task is the
minimum that keeps that gate green, and it auto-loads on every request with no
activation step.

mu-plugin behaviour (all hooks, no DB writes, idempotent by nature):

1. **XML-RPC** — `add_filter('xmlrpc_enabled', '__return_false')` +
   `add_filter('xmlrpc_methods', ...)` to drop `pingback.ping` /
   `pingback.extensions.getPingbacks`, and remove the `X-Pingback` response
   header (`wp_headers` filter). Gated by `WP_HARDEN_XMLRPC` env (default on).
2. **REST user enumeration** — `add_filter('rest_endpoints', ...)` removing
   `/wp/v2/users` and `/wp/v2/users/(?P<id>[\d]+)` routes for **unauthenticated**
   requests only (`is_user_logged_in()` check inside an
   `rest_authentication_errors`/`rest_endpoints` guard), so logged-in editors and
   the devlog Application-Password bot keep full access. Gated by
   `WP_HARDEN_REST_USERS` (default on).
3. **Author / misc enumeration** — block `?author=<n>` query-var redirect
   (`template_redirect` → 404 for anon), `remove_action('wp_head','wp_oembed_add_discovery_links')` author leak,
   `remove_action('wp_head','rsd_link')`, `remove_action('wp_head','wlwmanifest_link')`,
   `remove_action('wp_head','wp_generator')` (version disclosure — a fourth,
   adjacent win). Gated by `WP_HARDEN_AUTHOR_ENUM` (default on).

The three env gates render from the `wordpress-base` compose extension
(`templates/wordpress-base.compose.yml.j2`) so an operator can disable any leg
(e.g. a site that legitimately needs XML-RPC for the Jetpack/mobile app) without
editing PHP. Defaults ON — secure-by-default, opt-out.

### Why a mu-plugin, NOT a Traefik middleware

- Traefik can match `/xmlrpc.php` and `/wp-json/wp/v2/users` by path, but the
  WP REST namespace shares the `/wp-json/` prefix with the OIDC callback and the
  devlog writes — a path block is coarse and risks the SSO/devlog flows.
- `?author=N` is a query-string vector; Traefik query matching is brittle.
- Edge blocks don't strip the `X-Pingback` header or `wp_generator` meta.
- The mu-plugin keeps the logic *with the service it protects* and survives a
  proxy swap (host-nginx fallback on macOS vs Traefik on Linux). The plan adds
  **no** Traefik change.

## Files to touch

| File | Change |
|---|---|
| `roles/pazny.wordpress/files/security-hardening.php` | **NEW** mu-plugin (header block matching `rbac-role-sync.php` style; `if (!defined('ABSPATH')) exit;`; all `getenv('WP_HARDEN_*')` gated, default-on when unset) |
| `roles/pazny.wordpress/tasks/main.yml` | **NEW** copy task staging `security-hardening.php` → `{{ stacks_dir }}/iiab/wordpress/mu-plugins/security-hardening.php`, `mode: '0644'`, `notify: Restart wordpress`. Place it BEFORE the `Render compose override fragment` task (gate `test_copies_run_before_compose_render` enforces ordering) |
| `files/anatomy/plugins/wordpress-base/templates/wordpress-base.compose.yml.j2` | Add `WP_HARDEN_XMLRPC`, `WP_HARDEN_REST_USERS`, `WP_HARDEN_AUTHOR_ENUM` env keys under the existing **unconditional** `environment:` block (next to `_NOS_PLUGIN`), each `"{{ wordpress_harden_* | default(true) | lower }}"`. NOT inside the `install_authentik` gate — hardening is independent of SSO. |
| `default.config.yml` | Add 3 toggles near the other `wordpress_*` keys (~line 1138): `wordpress_harden_xmlrpc: true`, `wordpress_harden_rest_users: true`, `wordpress_harden_author_enum: true`. Stock-Jinja: plain booleans, real defaults — no filters. |
| `roles/pazny.wordpress/defaults/main.yml` | Mirror the 3 toggles (role-default parity, matching the existing `wordpress_*` shadow pattern). |
| `roles/pazny.wordpress/README.md` | New "## Security hardening" section documenting the three legs, the env toggles, and that `/wp-login.php` stays live as break-glass. |
| `docs/llm/security/attack-surface.json` | Update the three WP rows' `auth`/`risk` to note the mu-plugin mitigation (so the next scan doesn't re-flag as untouched). Keep the rows — login form is still *present* by break-glass design, just no longer an enumeration/amplification vector. |
| `tests/anatomy/test_wordpress_security_hardening.py` | **NEW** gate (see below). |

No change to: Traefik dynamic templates, `state/manifest.yml`, the role compose
template, `post.yml`. No live-system writes.

## The gate (`tests/anatomy/test_wordpress_security_hardening.py`)

Offline, static — mirrors the style of `test_wordpress_mu_plugins_blank_safety.py`
and `test_wordpress_rbac_mirror.py`. Asserts:

1. **File exists** — `roles/pazny.wordpress/files/security-hardening.php` is
   present and contains the `if (!defined('ABSPATH'))` guard.
2. **All three mitigations are wired in PHP** — the file references
   `xmlrpc_enabled`, removes the `users` REST routes (regex match on
   `rest_endpoints` + `wp/v2/users`), and blocks `?author=`
   (`author` query-var / `template_redirect`). Each behind its `getenv('WP_HARDEN_*')`
   gate string.
3. **Staging task present + ordered** — re-uses the blank-safety helper logic: a
   copy task with `src: security-hardening.php` and dest under the staging dir
   exists in `tasks/main.yml`, runs after the mkdir and before the compose render
   (this is *also* covered transitively by the existing blank-safety gate, but we
   assert it explicitly so a failure points at THIS feature).
4. **Env toggles rendered** — `wordpress-base.compose.yml.j2` contains all three
   `WP_HARDEN_*` keys, and they sit OUTSIDE the `{% if install_authentik %}`
   block (parse the template text; assert each key appears and that the
   `install_authentik` gate opens *after* the line — i.e. hardening is
   SSO-independent).
5. **Config defaults true** — `default.config.yml` and
   `roles/pazny.wordpress/defaults/main.yml` both define the three vars as `true`.
6. **Break-glass preserved** — assert the mu-plugin does NOT touch
   `xmlrpc`-unrelated login: a negative grep that `wp-login.php` / `login_form` /
   `authenticate` are NOT disabled in the file (it must not block the form).

The existing `test_wordpress_mu_plugins_blank_safety.py` will *also* turn red if
the staging copy is forgotten — that's the safety net that makes "mount never
loads it" impossible to ship.

## Risks & mitigations

- **Breaking the OIDC login** — the callback is `admin-ajax.php`, NOT a REST
  user route, and `xmlrpc_enabled=false` doesn't touch it. REST-user blocking is
  anon-only (`is_user_logged_in()` guard), so the post-login identity sync
  (`rbac-role-sync.php` reads `WP_User`) is unaffected. *Mitigation:* gate #2 +
  verification recipe step 4 (drive the SSO button).
- **Breaking devlog REST writes** — the devlog bot authenticates with an
  Application Password (Basic auth → `is_user_logged_in()` true for that request),
  so the anon-only REST guard lets it through; and devlog writes posts, not
  `/users`. *Mitigation:* verification step 5 hits a devlog write path.
- **Some operators want XML-RPC** (Jetpack, WP mobile app) — that's why each leg
  is an independent opt-out env toggle, defaults secure. Documented in README.
- **mu-plugin load order** — WP loads mu-plugins alphabetically;
  `security-hardening.php` sorts before `oidc-bootstrap.php`? No — `o` < `s`, so
  OIDC bootstrap loads first; irrelevant since our hooks fire on `init`/`rest_*`/
  `template_redirect`, well after all mu-plugins are loaded. No ordering hazard.
- **Read-only mount** — the mu-plugins dir is mounted `:ro`; the plugin only
  registers hooks, never writes — compatible.
- **`?author=N` 404 vs legitimate author archives** — block only the *redirect
  probe* for **anonymous** requests where `is_admin()` is false and the request
  is the numeric `author` query var (the enumeration vector), NOT pretty
  `/author/<slug>/` archives. Conservative: 404 the numeric form only.

## Verification recipe (READ-ONLY against live; full proof needs a playbook run)

Static (no live system, runs in CI + locally):

```bash
python3 -m pytest tests/anatomy/test_wordpress_security_hardening.py \
                  tests/anatomy/test_wordpress_mu_plugins_blank_safety.py -q
python3 -m pytest tests/anatomy/ -q          # whole suite stays green
ansible-playbook main.yml --syntax-check     # clean
# stock-Jinja trap gate for the 3 new config vars:
python3 -m pytest tests/anatomy/test_config_stock_jinja_only.py -q
```

Live behavioural proof (operator-run, AFTER an `ansible-playbook main.yml
--tags stacks,wordpress` reconverge — NOT part of this unsupervised change):

```bash
WP=https://wordpress.dev.local
# 1. XML-RPC dead (expect 405 / disabled, NOT 200 with methodResponse):
curl -sk -X POST "$WP/xmlrpc.php" -d '<methodCall><methodName>system.listMethods</methodName></methodCall>' | head
# 2. No X-Pingback header:
curl -skI "$WP/" | grep -i pingback   # expect: empty
# 3. REST user enumeration blocked for anon (expect 401/rest_user_cannot_view or 404):
curl -sk "$WP/wp-json/wp/v2/users" | head
# 4. Author probe 404 for anon:
curl -sko /dev/null -w '%{http_code}\n' "$WP/?author=1"   # expect 404
# 5. Break-glass still alive (login form must still render):
curl -sk "$WP/wp-login.php" | grep -qi 'user_login' && echo "break-glass OK"
# 6. SSO button still works — click "Sign in with Authentik" in a browser; lands
#    on /wp-admin (proves the OIDC callback path is untouched).
# 7. Devlog write still works — re-run the devlog ping or
#    `docker compose -p iiab exec -T wordpress wp post list --allow-root` to
#    confirm the bot's Application-Password REST writes are unaffected.
```

Expected: 1 disabled, 2 empty, 3 blocked, 4 → 404, 5 → form present, 6 → SSO
lands, 7 → devlog writes succeed.

## Commit shape (when implemented — single surgeon commit)

```
sec(wordpress): kill xmlrpc + REST user enum (mu-plugin)

- attack-surface.json flagged /xmlrpc.php, /wp-json/wp/v2/users,
  ?author=N reachable anon — amplification + user enumeration
- new security-hardening mu-plugin: xmlrpc off, anon REST users
  blocked, author-probe 404'd, version/RSD/WLW headers stripped
- env-gated (WP_HARDEN_*, default-on) so XML-RPC stays opt-in-able
- /wp-login.php untouched — it is the documented break-glass
- gate test_wordpress_security_hardening.py pins all three legs
```
