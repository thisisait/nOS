---
id: 2026-06-13-wp-rbac-mirror-site-polish
title: "The devlog gets a face — RBAC mirroring, custom fields, a real theme"
date: 2026-06-13
namespace: nos-core
summary: "One day after the devlog platform shipped, its WordPress presentation grew up: Authentik groups now mirror into WordPress roles on every OIDC login (highest privilege wins, demotion enforced), Secure Custom Fields and GeneratePress install declaratively via wp-cli, and the whole thing stays inside the mu-plugin + compose-extension doctrine."
tags: [wordpress, rbac, authentik, devlog, sso]
actors: [pazny, claude]
related: [roles/pazny.wordpress/files/rbac-role-sync.php]
---
The devlog platform shipped yesterday with a deliberately bare WordPress: the
default theme, no custom fields, and OIDC users landing as whatever role the
`openid-connect-generic` plugin felt like giving them. Today's pass closes
those three gaps without breaking the doctrine that every WordPress behavior
must be playbook-declared.

## RBAC mirroring — Authentik stays the source of truth

nOS already has a four-tier RBAC model bound to Authentik groups
(`nos-providers`/`nos-admins` → `nos-managers` → `nos-users` →
`nos-guests`). WordPress was the one SSO surface where that hierarchy
evaporated at the door.

The fix is a third mu-plugin, `rbac-role-sync.php`, following the exact
pattern of the OIDC bootstrap: it reads `WP_OIDC_GROUP_ROLE_MAP` from the
container env and hooks BOTH `openid-connect-generic` actions — user-create
*and* update-using-current-claim — so the role is enforced on every login,
not just the first. Highest-privilege mapped group wins; a user whose groups
no longer map gets demoted to subscriber. Local accounts (the break-glass
admin, the `nos-devlog-bot` writer) never traverse the OIDC hooks and are
structurally untouchable.

One trap dictated the data shape: the map is a **JSON string literal** in
`default.config.yml`, not a dict piped through `to_json` — `to_json` is an
Ansible filter, and anything in the vars files lands in the core-up
`{{ vars }}` namespace where only stock Jinja filters survive. The trap that
cost a release cycle in May now gets dodged at design time.

## Declarative site polish

`wordpress_theme: generatepress` and
`wordpress_extra_plugins: [secure-custom-fields]` are now config vars; the
role's post.yml installs and activates them via wp-cli behind `is-active`
guards, so steady-state runs stay offline-quiet and `changed=0`. Secure
Custom Fields is the WordPress.org-maintained GPL fork of ACF — the cleanest
all-FOSS custom-fields choice — and GeneratePress carries the devlog's
long-form entries far better than a default theme.

## What pins it

`tests/anatomy/test_wordpress_rbac_mirror.py`: both OIDC hooks present, the
mu-plugin staged and ro-mounted, the role map parsing as literal JSON and
covering all five tier groups, and the polish tasks guarded by `is-active`
checks. Live-verified on the box: GeneratePress active, SCF active, and the
role map env landing in the container after the plugin-loader re-render.
