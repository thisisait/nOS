# 31 — A cutover that needs the proxy the default install stopped shipping

**Found 2026-08-29, while trying to delete host nginx as dead weight. It is not
dead; that is the problem.**

The audit said: `install_nginx: false` since C1 (2026-04-29), Traefik is the
primary edge, `templates/nginx/` is 3 303 lines, `tasks/nginx.yml` another 139,
and seven of its tuning vars (`nginx_gzip`, `nginx_worker_processes`,
`nginx_ssl_ciphers`, …) have zero consumers anywhere in the tree. CLAUDE.md
calls it "an opt-in fallback for operators with bespoke vhost-level
constraints". Every sign of a component nobody uses.

It is not a fallback. It is the only implementation of the coexistence
framework's cutover.

## The mechanism

`files/anatomy/library/nos_coexistence.py` provisions a second version of a
service on a shifted port and cuts over by **rewriting an nginx vhost and
reloading nginx** — `render_nginx_vhost()`, `_nginx_vhost_path()`, and
`nginx_sites_dir` as a `required: True` module parameter. There is no Traefik
path in the module, none in `roles/pazny.traefik`, and no coexistence router in
the file provider.

`tasks/coexistence-provision.yml:93-108` already knows:

```yaml
# Only reload nginx when it's the active edge (install_nginx). On a Traefik-
# primary install (the default) nginx isn't installed, so `brew services reload
# nginx` exits non-zero and fails the whole provision — the track is already
# provisioned and the vhost is inert without a running nginx
```

That comment is accurate and it is the whole finding. On a **default** install
the coexistence track boots, the vhost is written to a directory no server
reads, the reload is skipped so nothing fails, and the module reports success.
The track is running and unroutable. Nothing is red.

## Why it looks fine from either end

From the nginx end: a component that is off by default, whose vars nobody
reads, documented as optional — an obvious cut.

From the coexistence end: a framework with a module, guards
(`G-COPY-HAS-MIGRATION`), a Wing view, and a docs page, all describing a
cutover that reads as implemented. `coexistence_supported: true` sits on two
rows of `state/manifest.yml`.

Neither end says the sentence that joins them: **the shipped cutover works only
under a configuration the estate has not defaulted to for four months.**

## The fee

Deleting nginx breaks coexistence silently — the module would keep writing
vhosts to nowhere. Keeping nginx pays 3 400 lines of second edge proxy to hold
one feature's last mile. And the doctrine sentence is wrong in the direction
that matters: *optional* invites the deletion this audit nearly made.

## What was done, 2026-08-29

Nothing to the code, deliberately. The nginx tree stays; the audit's largest
"cut" was withdrawn once the dependency was traced. What is owed is a decision,
and it is the operator's:

1. **Give coexistence a Traefik path** — the file provider already derives every
   other route from `state/manifest.yml`; a coexist track is one more router
   with a shifted upstream. Then nginx is genuinely optional and the 3 400 lines
   can go.
2. **Or say plainly** that coexistence requires `install_nginx: true`, in
   CLAUDE.md and in the module's own refusal — a provision for a web service
   under a Traefik-primary install should *refuse*, not succeed inertly.

Until one of them lands, the honest reading of `coexistence_supported: true` is
"supported on an install nobody runs".
