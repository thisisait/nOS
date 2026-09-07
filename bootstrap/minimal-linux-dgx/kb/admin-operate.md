---
title: Admin — operating the box
section: admin
order: 2
summary: Where everything lives, the services and their logs, re-running the recipe, renaming the host, certificates.
---

## The recipe is the source of truth

Everything on this box is produced by **one script** in the nOS checkout:

```
sudo bash /home/admin/projects/nOS/bootstrap/minimal-linux-dgx/setup-root.sh
```

It is idempotent: run it after any change to the recipe, after adding a user,
after renaming the host. It renders the hostname into nginx/compose/landing,
re-issues the leaf certificate when the name or an uplink IP is missing from
it, rebuilds nothing that is already there. A full log lands wherever you
`tee` it; the previous runs are in `/srv/nos-dgx/setup-root.log`.

Edit in the checkout (`bootstrap/minimal-linux-dgx/`), commit on branch
`feat/minimal-linux-dgx`, then run the script. Do not edit `/srv/nos-dgx`
by hand — the next run overwrites it.

## Layout

| Path | What |
|---|---|
| `/srv/nos` | runtime checkout of nOS (the `nos` CLI and tools run from here) |
| `/srv/nos-dgx` | rendered recipe: `compose.yml`, `nginx/`, `www/`, `bin/`, `keap/{src,data}` |
| `/srv/nos-seed.git` | bare, shared roadmap seed repo |
| `/etc/nos/` | tokens (`keap.env` RO for nos-users, `keap-rw.env` for maintainers, `keap-compose.env` all), the CA (`mkcert/`), `jupyterhub_config.py` |
| `/opt/nos-dgx/` | root-owned runtimes: `jupyterhub/{venv,chp}`, `node` |
| `/var/lib/nos-dgx/jupyterhub` | Hub state (db, cookie secret) |
| `/usr/share/ollama/.ollama/models` | the models, shared |
| `/home/<user>/.local/share/docker` | each developer's own image/volume store |

## Services

| Unit | What | Logs |
|---|---|---|
| `nginx` | the edge: 443 / 8443 / 8444 / 8445 | `/var/log/nginx/{access,error}.log` |
| `docker` (root) | the `iiab` stack: `iiab-keap-1`, `iiab-open-webui-1` | `docker logs <name>` |
| `ollama` | model server on `172.17.0.1:11434` | `journalctl -u ollama` |
| `jupyterhub` | the Hub on `127.0.0.1:8000` | `journalctl -u jupyterhub` (single-user servers log here too) |
| `user@<uid>` | each user's rootless docker, dev servers | `journalctl --user -M <login>@ -u docker` |

```
systemctl status nginx ollama jupyterhub
docker ps                                          # the two stack containers, healthy?
curl -s http://127.0.0.1:8091/api/health           # KEAP version + OK
docker compose -f /srv/nos-dgx/compose.yml up -d   # (as a maintainer) re-apply the stack
```

A stack restart keeps all data: KEAP in `/srv/nos-dgx/keap/data`, Chat in the
Docker volume `open-webui`.

## Renaming the host

Change it in the DGX dashboard, reboot, run the recipe. The leaf certificate is
re-issued for the new name; the **CA does not change**, so nobody re-imports
anything. Old bookmarks with the old name stop working; KEAP accepts writes only
from `https://<newname>.local:8443`.

## Certificates

CA: `/etc/nos/mkcert` (published as `/nos-dgx-rootCA.pem` on the landing page).
Leaf: `/etc/nginx/tls/spark.pem`, valid ~2 years, names = host, short host, every
uplink IP, localhost. To force a re-issue delete the leaf and run the recipe.

## Two network uplinks

Wi-Fi (`192.168.68.x`, default route) and a USB ethernet on the corporate
network (`10.53.201.x`). nginx listens on both; mDNS answers only on physical
interfaces. `ufw` is installed but **disabled** — see the hardening row in the
roadmap before opening this box to a wider network.
