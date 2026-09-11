---
title: Remote IDE over SSH
section: dev
order: 1
summary: VS Code Remote-SSH / Dev Containers and PhpStorm via JetBrains Gateway — nothing to install locally but the IDE.
---

Your code, your containers and your dev servers live on `__SHORT__`; your
laptop runs only the IDE window.

## VS Code

1. Install the **Remote – SSH** extension.
2. Add a host: `ssh <you>@__HOST__` (keys recommended: `ssh-copy-id <you>@__HOST__`).
3. Connect, *Open Folder*, pick your project under `/home/<you>/`.

The VS Code server is installed on the DGX automatically (arm64 build). With the
**Dev Containers** extension the *Reopen in Container* command uses **your own
rootless Docker** — nothing to configure, the active docker context is already
`rootless` (see [Rootless Docker](rootless-docker.html)).

Dev servers (`php artisan serve`, `vite`, …) bind a port on the DGX; VS Code
forwards it to your laptop automatically (*Ports* panel), so
`http://localhost:5173` on your machine is your Vite on the DGX. No nginx, no
public port.

## PhpStorm / JetBrains Gateway

Gateway → *SSH* → `__HOST__`, your login. It installs the IDE backend on the
DGX (arm64 Linux is supported) and streams the UI. For the interpreter use
**Docker** with the socket `unix:///run/user/<your uid>/docker.sock`
(`id -u` tells you the uid) and the image your project pins, e.g.
`php:8.1-cli`.

## Ports and networking

- Anything you start listens on the DGX; reach it through the IDE forward or
  an SSH tunnel: `ssh -L 5173:localhost:5173 <you>@__HOST__`.
- Rootless containers cannot bind ports below 1024 — use 8080, 5173, 3000 …
- `localhost` inside a container is the container; the host is reachable as
  `host.docker.internal` (rootless Docker maps it to your pasta gateway).

## What you cannot do, and why

- `sudo`, and the `docker` group: both are root. Your rootless daemon gives
  you everything a project needs without them.
- Bind `*.__HOST__` names or 80/443: those belong to the shared nginx. Ask
  the admin if a project needs a real hostname on the LAN.
