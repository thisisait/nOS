---
title: Troubleshooting
section: tips
order: 1
summary: The symptoms we have already seen on this box, and what each one meant.
---

| Symptom | Cause | Fix |
|---|---|---|
| Browser says the certificate is not trusted | the local CA is not imported on this device | [First login](first-login.html), step 2 |
| 8443 asks for a password again and again | wrong Linux password, or the account is not in `nos-users` | `ssh` in to check the password; admin: `id <login>` |
| KEAP shows the page but every save fails (403) | you opened it by IP or another name; the same-origin guard wants `https://__HOST__:8443` | use the name |
| Notebook kernel stays "connecting" forever | the websocket was refused as cross-origin (nginx sent `Host` without the port) | fixed in the recipe; if it returns: `journalctl -u jupyterhub` shows *Blocking Cross Origin WebSocket* |
| Chat: "Session expired" right after login, black page | Chat was behind the PAM gate; its bearer token and basic-auth fought over one header | Chat has its own login now; do a hard reload (Ctrl+Shift+R) |
| Chat shows no models | Open WebUI remembered `localhost:11434` from an older setup | Admin → Settings → Connections → Ollama URL `http://host.docker.internal:11434` |
| `docker: permission denied` / `Cannot connect to the Docker daemon` | your rootless daemon is not running, or the context is wrong | `systemctl --user start docker`; `docker context use rootless` |
| `docker run -p 80:80` fails | rootless daemons cannot bind ports below 1024 | use 8080 and forward |
| A build is killed / OOM inside your container | your user slice hit its 32 GB ceiling | `systemd-cgls /user.slice/user-$(id -u).slice`; free memory, or ask admin to raise `NOS_USER_MEM_MAX` |
| `spark1.local` does not resolve from my laptop | mDNS does not cross networks (corporate uplink) | use the IP the admin gives you; it is on the certificate |
| Everything is gone after a reboot | it is not: all units are enabled | wait ~1 min; `systemctl status nginx ollama jupyterhub`, `docker ps` |

## Reading the box's state (admin)

```
systemctl --failed
docker ps --format '{{.Names}} {{.Status}}'
curl -s http://127.0.0.1:8091/api/health
curl -s http://172.17.0.1:11434/api/ps
journalctl -p err -b --no-pager | tail
```

A dedicated one-command reader (`dgx-status`) is a roadmap row; until it
exists, these five lines are it.
