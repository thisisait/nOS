---
title: Admin — upgrades
section: admin
order: 3
summary: Bump KEAP, Open WebUI, Ollama, JupyterHub or the recipe itself — each is one pinned place.
---

## KEAP (the DataTables engine)

Pinned in `setup-root.sh` (`KEAP_PIN=v1.44.0`, mirroring `keap_version` in nOS's
`default.config.yml`). To upgrade:

1. Set `KEAP_PIN` to the new tag; check the tag's notes in
   [nos-keap](https://github.com/thisisait/nos-keap) — some versions are
   traps (nOS's `roles/pazny.keap/defaults/main.yml` lists them).
2. `rm -rf /srv/nos-dgx/keap/src` (the clone is shallow and pinned) and run
   the recipe: it clones, builds `nos/keap:<ver>-<sha>` natively (several
   minutes), rewrites the image tag in compose, brings the stack up, re-runs
   the knowledge ingest and reconciles the tables.
3. `nos dtt status` still reads the roadmap → done. The data dir is untouched
   across versions; a schema-changing release says so in its notes.

## Open WebUI (Chat)

```
docker compose -f /srv/nos-dgx/compose.yml pull open-webui
docker compose -f /srv/nos-dgx/compose.yml up -d open-webui
```

Accounts and chats live in the `open-webui` volume. Note: Open WebUI persists
settings in its DB and prefers them over environment variables — the Ollama
URL is stored there (`Admin → Settings → Connections`) and survives image
changes.

## Ollama

```
curl -fsSL https://ollama.com/install.sh | sudo sh     # re-runs in place, keeps models
sudo systemctl restart ollama
```

The drop-in `/etc/systemd/system/ollama.service.d/nos-dgx.conf` (bind address,
keep-alive) is ours and survives the installer. Pull models as root
(`sudo -u ollama` is not needed): `OLLAMA_HOST=http://172.17.0.1:11434 ollama pull <tag>`.

## JupyterHub

The venv is root-owned under `/opt/nos-dgx/jupyterhub/venv`:

```
sudo /opt/nos-dgx/jupyterhub/venv/bin/pip install -U jupyterhub jupyterlab notebook
sudo systemctl restart jupyterhub        # running Labs survive (cleanup_servers=False)
```

Users' own kernels (`~/venvs/…`) are theirs and unaffected.

## Node (for the Hub's proxy)

`/opt/nos-dgx/node` is the official arm64 tarball, latest 22.x at install time.
To move to a newer line: `sudo rm -rf /opt/nos-dgx/node`, edit the `latest-v22.x`
URL in the recipe if the major changes, run the recipe.

## The recipe itself

It is part of nOS: branch `feat/minimal-linux-dgx`, directory
`bootstrap/minimal-linux-dgx/`. Pull, read the diff, run the script. The
runtime checkout `/srv/nos` is updated the same way (`git -C /srv/nos pull`).
