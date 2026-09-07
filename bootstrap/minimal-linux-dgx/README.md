# nos-dgx — nOS DataTables + skills on the DGX Spark

**The hostname is read live.** `setup-root.sh` renders `nginx/nos-dgx.conf`,
`compose.yml` and `www/index.html` from the `__HOST__`/`__SHORT__` templates in
the staging tree using `hostname -s`, and re-issues the leaf certificate when the
name or an uplink IP is missing from it. Rename the box → reboot → re-run the
script; the CA does not change, so nobody re-imports anything.

The partial nOS that runs here: **KEAP** (the DataTables engine, Docker, arm64),
the **DTT tools** and **skill library** from the runtime checkout `/srv/nos`,
**Open WebUI** over a **native Ollama** system service, all behind **nginx**
with **PAM** login against the box's Linux accounts. No Ansible, no Wing/Bone/
Pulse, no Authentik — this is `docs/plans/datatables-subsystem.md` §8 with
nginx playing the outpost.

| URL | What | Who |
|---|---|---|
| https://<host>.local/ | landing + root CA download | anyone on the LAN |
| https://<host>.local:8443/ | KEAP — roadmap, current-state, tables | group `nos-users` |
| https://<host>.local:8444/ | Open WebUI — chat on local models | its own accounts (admin invites; bearer vs basic-auth clash, see nginx conf) |
| https://<host>.local:8445/ | JupyterHub — one Lab per user, as that Linux user, CUDA kernel | PAM login form, group `nos-users`; `admin` is Hub admin |
| http://127.0.0.1:8091 | KEAP agent door (bearer tokens) | shell users, MCP |
| http://172.17.0.1:11434 | Ollama API (no auth) | host + containers only |

## JupyterHub

Native, root-run Hub (`/opt/nos-dgx/jupyterhub/{venv,chp}`, root-owned on
purpose), `LocalProcessSpawner` starts each Lab setuid as the user in `$HOME`,
`PAMAuthenticator` + `allowed_groups={nos-users}`. State in
`/var/lib/nos-dgx/jupyterhub` (root 0700), config `/etc/nos/jupyterhub_config.py`.
A `pre_spawn_hook` hands each Lab the KEAP tokens its user's group may read, so
`requests.get(f"{os.environ['KEAP_API_URL']}/agent/v1/tables/roadmap/rows", headers=…)`
works from a cell. The shared kernel carries torch (cu130, aarch64) when the
wheel installs; users add their own kernels with `python -m ipykernel install --user`.

## Layout

```
/srv/nos            runtime checkout of nOS (fix/dtt-env-addressing), origin=GitHub
/srv/nos-dgx        rendered copy of this directory + keap/{src,data} (clone + data)
/opt/nos-dgx        jupyterhub/{venv,chp} — root-owned runtime
/var/lib/nos-dgx    jupyterhub state (root 0700)
/srv/nos-seed.git   bare, shared seed repo — every user clones it to ~/nos-seed
/etc/nos/keap-compose.env   all tokens (root:nos-maintainers 0640) — compose env_file
/etc/nos/keap.env           RO token + addresses (root:nos-users 0640)
/etc/nos/keap-rw.env        RW token + proxy secret (root:nos-maintainers 0640)
/etc/nos/mkcert             the local CA (CAROOT)
/etc/profile.d/nos.sh       sources whichever of the above you may read
```

Groups: `nos-users` (may log in to the web + read tables), `nos-maintainers`
(RW token, compose, seed pushes). `docker` and `sudo` stay what they are —
**`tester` is in neither**, by design.

## Phases

**A** (done by the session, no root): KEAP image built, repo tools patched,
this tree staged.

**B** (root, once, idempotent): `sudo bash <checkout>/bootstrap/minimal-linux-dgx/setup-root.sh` — the
script's own directory is the source tree; it clones nos-keap at the pin and builds
the image when missing, so a fresh box needs only Docker + this checkout.

**C** (inside B, run as admin): `docker compose up -d`, knowledge ingest,
`seed-tables.py` (roadmap + current-state). Re-run by hand any time:
```bash
. /etc/profile.d/nos.sh
docker compose -f /srv/nos-dgx/compose.yml up -d
docker exec iiab-keap-1 node knowledge/ingest.mjs
/srv/nos-dgx/bin/seed-tables.py
```

**D** (any maintainer): the first row is this plan itself.
```bash
nos dtt capture --slug dgx-standalone-dtt --title "..." --track platform --task-type converge --status doing --body "..."
cd ~/nos-seed && git add -A && git commit -m "first row" && git push
nos dtt seed && nos dtt status
```

## Adding a user

```bash
sudo useradd -m -s /bin/bash -G nos-users <name> && sudo passwd <name>
sudo -u <name> -H /srv/nos-dgx/bin/nos-user-setup
# admin tier: add a line to the $nos_groups map in nginx/nos-dgx.conf, then
sudo install -m 0644 /srv/nos-dgx/nginx/nos-dgx.conf /etc/nginx/sites-available/ && sudo nginx -t && sudo systemctl reload nginx
```

## What this deliberately does not do

- No per-user identity on the MCP/agent door: `/agent/v1` is bearer RO/RW, so
  every shell user looks like one agent (`X-Keap-Agent: <user>@spark-03bd` is a
  label, not auth). Per-user attribution works through the browser (PAM).
- No KEAP fs-sync of home directories (they are 0750; needs a shared tenant tree).
- No firewall changes. Ollama is unreachable from the LAN only because it binds
  the docker0 address.
- The old `open-webui` bundle container is left stopped, its volumes intact.
