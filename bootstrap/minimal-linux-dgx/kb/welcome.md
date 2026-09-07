---
title: What this machine is
section: start
order: 1
summary: One DGX Spark, one login, three web services and a shell — and what each is for.
---

`__SHORT__` is an NVIDIA DGX Spark (20 cores, 121 GB unified memory, one GB10
GPU, 3.7 TB NVMe) that runs a **minimal nOS**: the DataTables engine, the agent
skill library, a chat UI on local models and a notebook server — for several
people at once, each under their own Linux account.

| Where | What | Sign in with |
|---|---|---|
| `https://__HOST__/` | this landing page + the certificate to install | — |
| `https://__HOST__:8443/` | **KEAP** — DataTables (roadmap, current-state), knowledge | your Linux password (browser prompt) |
| `https://__HOST__:8444/` | **Chat** — Open WebUI on the local Ollama models | its own account (the admin invites you) |
| `https://__HOST__:8445/` | **Notebooks** — JupyterHub, your own Lab, GPU kernel | your Linux password (login form) |
| `https://__HOST__:8447/` | **Automation** — n8n workflows and webhooks | its own account (the owner invites you) |
| `https://__HOST__:8446/` | **Backups** — Backrest, browse and restore | admin only |
| `ssh __HOST__` | your shell, your rootless Docker, the `nos` CLI | SSH |

**One identity.** Your Linux account is the account everywhere except Chat. The
password you use for SSH is the password the browser asks for on 8443 and the
one the notebook login form takes. Keep it strong: on this box a weak Linux
password is a weak web password.

**Who is who.** Members of group `nos-users` can log in to the web and read the
tables; `nos-maintainers` additionally hold the write token and run the stack.
The `admin` account is the operator. Ask them for an account — see
[First login](first-login.html).

**What survives a reboot.** Everything: nginx, the KEAP and Chat containers,
Ollama, JupyterHub, n8n and every user's rootless Docker come back on their own.
A restic backup runs every night to the external disk, and a restore drill
every morning says whether it is any good ([Backup and restore](admin-backup.html)).
