---
title: Admin — users and tiers
section: admin
order: 1
summary: Add a developer in three commands, give someone the maintainer tier, remove a user cleanly.
---

## Add a user

```
sudo useradd -m -s /bin/bash -G nos-users -c "Full Name" <login>
sudo passwd <login>
sudo bash /home/admin/projects/nOS/bootstrap/minimal-linux-dgx/setup-root.sh
```

The third line is the whole recipe re-run (idempotent, ~1 min when nothing is
missing): it enables linger for the new account, runs `nos-user-setup` as them
(skills, `nos` env, seed clone, **rootless Docker**), and reloads what changed.
Tell them to `passwd` on first login and to import the CA
([First login](first-login.html)).

If you only want the per-user half without the full run:

```
sudo loginctl enable-linger <login>
sudo -u <login> -H env XDG_RUNTIME_DIR=/run/user/$(id -u <login>) \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u <login>)/bus \
  /srv/nos-dgx/bin/nos-user-setup
```

## Tiers

| Tier | Linux group | Gets |
|---|---|---|
| 3 · user | `nos-users` | web login, RO token, own rootless Docker, own Lab |
| 2 · manager | `nos-users` + `nos-managers` (Linux group, create it) + nginx map | KEAP tables with visibility `tier-managers` (the roadmap) — the shell (identity outpost) reads the Linux group, the browser reads the nginx map; keep them in step |
| 1 · admin | `nos-users` + `nos-maintainers` + nginx map | RW token, compose, seed pushes, Hub admin |

KEAP reads the tier from the `X-Authentik-Groups` header nginx sets, and that
comes from a static map in
`bootstrap/minimal-linux-dgx/nginx/nos-dgx.conf`:

```
map $remote_user $nos_groups {
    default   "nos-users";                     # tier 3
    admin     "nos-providers,nos-admins";      # tier 1
    someone   "nos-managers";                  # tier 2 — add lines like this
}
```

After editing the map: re-run the recipe (it renders and reloads nginx), or
`sudo install -m 0644 /srv/nos-dgx/nginx/nos-dgx.conf /etc/nginx/sites-available/ && sudo nginx -t && sudo systemctl reload nginx`
after rendering `__HOST__`.

Maintainer tier = `sudo usermod -aG nos-maintainers <login>` plus the map line;
it takes effect at their next login (tokens are read from `/etc/nos/*.env` by
group at shell start).

**Never** add a developer to `docker` or `sudo`. Their rootless daemon covers
every project need; `docker` is root.

## Chat accounts

Open WebUI keeps its own users (its bearer token cannot share the
`Authorization` header with the browser's basic-auth, so it is not behind the
PAM gate). Admin → *Users* → *Add user* inside Chat.

## n8n accounts

Like Chat, n8n keeps its own users: the first visit to `https://__HOST__:8447/`
creates the **owner** (make that the admin), then *Settings → Users → Invite*
by e-mail. Everyone in n8n shares the instance's credentials store, so treat it
as a team space, not a per-user sandbox.

## Remove a user

```
sudo loginctl disable-linger <login>; sudo loginctl terminate-user <login>
sudo userdel -r <login>          # home incl. their docker store, venvs, seed clone
```

Then drop their line from the nginx map if they had one, and their Chat
account inside Open WebUI. The bare seed repo and the tables keep their rows
(history), attributed to the old login.
