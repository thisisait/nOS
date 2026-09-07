---
title: First login
section: start
order: 2
summary: Get an account, trust the local certificate, open the three services.
---

## 1. Get an account

Ask the admin. You get a Linux login on `__SHORT__` and an initial password;
change it right away over SSH:

```
ssh <you>@__HOST__
passwd
```

The name `__HOST__` resolves via mDNS on the same LAN (macOS and Linux out of
the box, Windows with Bonjour). From another network use the IP the admin gives
you — it is on the certificate too.

## 2. Trust the local certificate authority (once per device)

The web uses TLS signed by a local CA. Download
[`nos-dgx-rootCA.pem`](/nos-dgx-rootCA.pem) and import it as a **trusted root**:

- **macOS** — double-click, Keychain → *System* → set *Always Trust*.
- **Windows** — `certmgr.msc` → *Trusted Root Certification Authorities* → Import.
- **Firefox** (any OS) — Settings → Privacy & Security → Certificates → Import → tick *trust for websites*.
- **Linux** — `sudo cp nos-dgx-rootCA.pem /usr/local/share/ca-certificates/nos-dgx.crt && sudo update-ca-certificates`.

Without this every service shows a certificate warning; with it the padlock is
green on all ports.

## 3. Open the services

- **KEAP** `https://__HOST__:8443/` — the browser asks for a name and password:
  your Linux ones. Use the *name*, not the IP, for anything you write: KEAP
  refuses writes from a different origin.
- **Chat** `https://__HOST__:8444/` — the admin creates your account inside
  Open WebUI (self-signup is off). Pick a model from the top-left list.
- **Notebooks** `https://__HOST__:8445/` — the login form takes your Linux
  credentials and starts *your* JupyterLab in your home directory.

## 4. Your shelf (optional, shell users)

The first time you SSH in, run

```
/srv/nos-dgx/bin/nos-user-setup
```

It links the nOS skill library into your AI harness directories
(`~/.claude/skills`, `~/.hermes/skills`, …), writes `~/.nos/nos-cli.env` so the
`nos` CLI finds the checkout, clones the roadmap seed repo to `~/nos-seed`, and
— if you are not in the `docker` group — starts your own rootless Docker daemon.
Run it again any time; it only adds what is missing.
