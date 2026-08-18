# Foreign properties — upstream facts our work cannot remove

> Canonical. This document owns the rules that are true about **someone else's**
> software: images, binaries and protocols this estate consumes but does not
> build. Cited from code; every `§` is resolved by `tools/doctrine-cite.py`.

## 1. What belongs here

A rule earns a section only when all three hold:

1. it is a property of an artifact we do not build (an upstream image, binary
   or protocol);
2. **no change on our side removes it** — we can only route around it;
3. getting it wrong produces a *confident wrong reading* — a red that is not a
   fault, or a green that is not health — rather than an obvious crash.

Everything failing (2) belongs elsewhere: ours-and-fixable is a fix,
ours-and-remembered is a gate (`docs/doctrine/gates.md`), and a rule about the
operator's own machine is a runbook step (`docs/nos-cli.md`). A section here is
a **permanent accommodation**, so it names both the accommodation and the code
that performs it; a paragraph with no performing code is a claim, not doctrine.

## 2. A healthcheck in a minimal image may be unable to RUN

`scratch`, distroless and rust-slim images ship the service binary and little
else — no `wget`, no `curl`, no `python`, sometimes no shell at all. A
`CMD wget --spider …` healthcheck in such an image does not *fail*; it never
starts:

```
OCI runtime exec failed: exec failed: unable to start container process:
exec: "wget": executable file not found in $PATH
```

Docker records that as `(unhealthy)`, and at `docker ps` it is indistinguishable
from a service that is genuinely down. Two measured instances: `qdrant/qdrant:v1.13`
logged `wget: not found` 955× and gated off the apps post-hooks (2026-05-03);
the 2026-08-06 `redis_exporter` bump moved upstream's default image to `scratch`
and failed a converge after 1200 s while the exporter served metrics on `:9121`
the entire time.

### 2.1 The accommodation, in order of preference

1. **Pin a tag that still carries a shell**, where upstream publishes one —
   the `-alpine` suffix on `redis_exporter_version` (`default.config.yml`) is
   what keeps the existing `wget --spider` probe in
   `roles/pazny.grafana/templates/compose.yml.j2` executable. The numeric part
   moves with the pin sweep (this doctrine quoted `v1.88.0` and was stale
   within four days); the suffix is the doctrine. Dropping `-alpine` re-opens
   the 2026-08-06 failure exactly.
2. **Probe with what the image HAS** — bash-only: `["CMD", "bash", "-c",
   ":>/dev/tcp/127.0.0.1/<port>"]`, TCP liveness via bash's built-in
   pseudo-device (`apps/qdrant.yml`).
3. **No shell at all: declare no healthcheck** and rely on
   `restart: unless-stopped`. A check that cannot execute is worse than no
   check, because it manufactures a verdict.

### 2.2 A check that could not run is reported, never excused

`files/anatomy/scripts/stack-health-probe.py` inspects the health log of each
container it has already classified `failed` and annotates the ones whose check
could not execute (`blob_says_check_could_not_run`). The container **stays
failed** — a container whose health cannot be established is not a container
known to be well. What changes is that the line says which of the two broke.

## 3. `lscr.io/linuxserver/code-server` speaks plain HTTP on 8443

The port number says TLS; the listener does not. The LSIO image serves plain
HTTP on container port 8443 unless started with `--cert`, which nOS does not
pass. Traefik configured to speak HTTPS to it answered with
`tls_get_more_records: packet length too long` and a user-visible 502/404
(2026-05-04, `code.pazny.eu`).

### 3.1 The accommodation — an upstream is HTTP until measured otherwise

`traefik_https_upstream_ids` (`roles/pazny.traefik/vars/main.yml`) names only
services whose **own container listener** is TLS. It is `[]` today, and empty is
the current correct answer rather than a gap: every routed upstream in this
estate terminates TLS at the edge and speaks HTTP behind it. An id may be added
only with measured evidence of an internal TLS listener — **a port number is not
evidence**. Gate: `tests/anatomy/test_traefik_https_upstream_binds_tls.py`,
which exists to refuse a careless addition, not to assert a population.

## 4. OpenClaw's gateway service discards its own stderr

`openclaw gateway install` writes `~/Library/LaunchAgents/ai.openclaw.gateway.plist`
with:

```xml
<key>StandardOutPath</key>  <string>~/Library/Logs/openclaw/gateway.log</string>
<key>StandardErrorPath</key><string>/dev/null</string>
```

There is no flag to change it — `gateway install` accepts `--force --port
--runtime --token --wrapper` and nothing else — and the plist is regenerated on
every reinstall, so an edit does not survive.

**What that costs.** On 2026-08-11 the gateway had been failing with exit **78**
(`EX_CONFIG`) with `KeepAlive: true`, so launchd restarted it in a loop. Every
one of those runs printed the reason and every one of them wrote it to
`/dev/null`. `launchctl list` showed the number; nothing on the machine showed
the sentence. It became readable only by running the plist's own
`ProgramArguments` by hand:

```
Your OpenClaw config was written by version 2026.7.1-2, but this command is
running 2026.6.11. Refusing to run automatic gateway startup migrations…
```

**The rule.** When `ai.openclaw.gateway` reports a non-zero status, do not look
for a log — there is not one. Extract `ProgramArguments` from the plist and run
them directly; that is the only place the refusal is legible. The cause is
usually the one `roles/pazny.openclaw/tasks/main.yml` now reconciles: `npm
install -g` follows the current node, so every nvm bump strands the install the
plist still points at.

**Not ours to fix.** A wrapper of our own could tee stderr, but the plist is
regenerated by `gateway install --force` — the command we deliberately rely on,
because the service file's shape is theirs to change. Interposing would mean
owning a file upstream rewrites, which is the trade §1 says not to make.
