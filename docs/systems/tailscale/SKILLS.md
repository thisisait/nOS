# Tailscale — Skills

> Callable actions for Tailscale. These are **host CLI** commands run against the
> local `tailscale` binary (`/usr/local/bin/tailscale`), not an HTTP API. They
> run on the Mac host, not inside a container.

## Authentication

- **Method:** None (host CLI — the interactive Tailscale.app login on the host; nOS provisions no token)
- **Binary:** `/usr/local/bin/tailscale`
- **Device login (one-time, interactive):** `https://login.tailscale.com`

---

## check-status

**Trigger:** "check tailscale status", "is the VPN up", "am I connected to the tailnet"
**Method:** CLI
**Command:** `tailscale status --peers=false`
**Output:** the node's connection state; exit `0` when up and authenticated.

---

## get-ip

**Trigger:** "get the tailscale IP", "what is my tailnet address"
**Method:** CLI
**Command:** `tailscale ip -4`
**Output:** the host's `100.x.y.z` tailnet address.

---

## connect

**Trigger:** "connect to the VPN", "bring tailscale up", "start tailscale"
**Method:** CLI
**Command:** `tailscale up`
**Output:** brings the node online; on first run opens a browser to
`https://login.tailscale.com` to authenticate the device.

---

## enable-ssh

**Trigger:** "enable tailscale ssh", "allow SSH over the tailnet"
**Method:** CLI
**Command:** `tailscale up --ssh`
**Output:** re-registers the node with Tailscale SSH enabled.

---

## advertise-subnet

**Trigger:** "advertise a subnet route", "share my home network over tailscale", "subnet router"
**Method:** CLI
**Command:** `tailscale up --advertise-routes=192.168.1.0/24`
**Output:** advertises the given CIDR as a subnet route (must be approved in the
Tailscale admin console). Replace the CIDR with the actual home subnet.
