# JupyterHub

> Multi-user notebooks on a Linux host. Each person's server runs **as their own
> Linux login** (SystemdSpawner), in their own 0700 home, inside its own systemd
> cgroup — the same boundary an ssh session meets. Linux only.

## Quick Reference

| | |
|---|---|
| **URL** | `https://jupyter{host_alias_seg}.{tenant_domain}` (`jupyterhub_domain`) |
| **Port** | `8010` (`jupyterhub_port`) — the proxy on docker0 (`nos_docker_host_ip`), reached by Traefik only |
| **Toggle** | `install_jupyterhub: false` (on in `profiles/workstation.yml`) |
| **Role** | `roles/pazny.jupyterhub` — host-native, not a compose service |
| **Plugin** | `files/anatomy/plugins/jupyterhub-base` — Authentik native OIDC client `nos-jupyterhub`, tier 3 |
| **Units** | `nos-jupyterhub.service` (Hub, root) + `nos-jupyterhub-proxy.service` (configurable-http-proxy, pinned container, host network) |
| **Venv** | `/opt/nos/jupyterhub/venv` — Hub, Lab, kernel, pinned (`jupyterhub_version`, `jupyterlab_version`, …) |
| **State** | `/var/lib/nos-jupyterhub` (root 0700): sqlite, cookie secret, `hub.env` |
| **People's data** | their Linux homes — not the Hub's |

## Who can sign in

Two conditions, both required:

1. Authentik says the person is RBAC tier 3 or above (`allowed_groups` from
   `authentik_rbac_tiers`); tier 1 administers the Hub.
2. The person has a Linux login — the `unix` identity realm
   (`roles/pazny.linux.users`). An SSO identity with no login is refused by a
   `post_auth_hook` with a log line, never spawned.

So "who has notebooks" is declared in exactly one place: the roster
(`nos_identities` / `nos_extra_identities` with `realms: [authentik, unix]`).

## Isolation

- Home `0700`, owned by the person (`linux_users_home_mode`).
- `isolate_tmp`, `disable_user_sudo`; `MemoryMax`/`CPUQuota` per server
  (`jupyterhub_mem_limit`, `jupyterhub_cpu_limit`).
- Devices are NOT isolated — the GPU is a device.
- The test: `profiles/test-users.yml` gives bob and carol (both tier 3) logins;
  bob must not read carol's home from a notebook or from ssh.
