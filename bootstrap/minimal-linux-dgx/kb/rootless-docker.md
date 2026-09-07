---
title: Rootless Docker per user
section: dev
order: 2
summary: Your own daemon, your own images, any PHP version per project, capped at 32 GB / 10 cores.
---

Every developer runs their **own** Docker daemon as their own user. No shared
daemon, no `docker` group, no root: a container escape lands in your account,
not in root.

## Check it is yours

```
docker context show          # rootless
docker info --format '{{.SecurityOptions}}  root={{.DockerRootDir}}'
```

Expect `rootless` in the options and `root=/home/<you>/.local/share/docker`.
Images and volumes live there, on the 3.7 TB NVMe. If the daemon is not
running (fresh account): `/srv/nos-dgx/bin/nos-user-setup` starts it, or
`systemctl --user start docker`.

## A different PHP per project — the normal case

Pin the version in the project, not on the machine:

```yaml
# docker-compose.yml
services:
  app:
    image: php:8.1-fpm-alpine          # another project: php:8.3-fpm
    volumes: [".:/var/www/html"]
  node:
    image: node:22-alpine
    working_dir: /app
    volumes: [".:/app"]
    command: sh -c "npm ci && npm run dev -- --host"
    ports: ["5173:5173"]
```

```
docker compose up -d
docker compose exec app php -v
docker compose run --rm app composer install
```

Two projects with two PHP versions run side by side under your account; a
`devcontainer.json` does the same for VS Code (*Reopen in Container*).

## Limits you will hit, on purpose

| Limit | Value | Why |
|---|---|---|
| memory, all your processes + containers | 32 GB | one runaway build must not starve the LLM or KEAP |
| CPU | 10 cores | same |
| host ports | ≥ 1024 | unprivileged |
| networking | `pasta` user-mode | fine for dev servers; not for raw sockets / multicast |

`systemd-cgls /user.slice/user-$(id -u).slice` shows your slice with the daemon
and every container inside it. The ceiling is per user, not per container.

## Housekeeping

```
docker system df           # what your store holds
docker system prune        # drop stopped containers, dangling images
docker builder prune       # build cache
```

Nobody else can see or clean your store; the admin's `docker ps` (the root
daemon that runs KEAP and Chat) does not list your containers at all.

## GPU inside your containers?

Possible via CDI (`--device nvidia.com/gpu=all`) but not enabled for rootless
daemons yet — ask the admin if a project needs it. For notebooks the GPU is
already there: [Notebooks and the GPU](notebooks-gpu.html).
