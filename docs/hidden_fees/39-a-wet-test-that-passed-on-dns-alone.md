# 39 — A wet-test that passed on DNS alone

**Found 2026-08-31, while checking whether the trunk was fit to tag.**

`master`'s CI has been red since **2026-07-16** — nine consecutive runs across
three SHAs, 46 days, and through **both** the `v0.10-beta` and `v0.11-beta`
tags. That is not the fee. The fee is the year before it, when the same job was
green.

## What the probes were actually proving

The integration wet-test finishes by running `tools/nos-smoke.py`, which derives
one probe per service from `state/manifest.yml` and asks for an HTTP status.
`tests/config.yml` — the config both integration jobs run under — carries:

```yaml
install_nginx: true
install_traefik: false
```

On Linux that pair cannot serve anything. Per-service nginx vhosts are
macOS-only; Traefik is the Linux edge. So on the Linux runner **nothing has ever
listened on 443**, for any service, on any run.

The probes passed anyway, because until `b0df60e9 fix(smoke): a probe must test
the service, not DNS` they were satisfied by name resolution. `dnsmasq` was
installed and `*.dev.local` pointed at `127.0.0.1`, which was enough. A probe
that resolves a name and calls it a service is the whole fee in one line.

## When the bill came due

The moment the probe got honest. `b0df60e9` added a loopback retry so a probe
would stop passing on DNS alone; the retry then got `Connection refused` on
every host, correctly, and the job went red and stayed red:

```
face      https://os.dev.local/       200,301,302,308  DEAD  ❌ Temporary failure in name resolution
wing      https://wing.dev.local/     200,301,302,308  DEAD  ❌ (loopback retry: Connection refused)
mailpit   https://mail.dev.local/     200,301,302,308  DEAD  ❌
app_*     https://*.apps.dev.local/   …                DEAD  ❌ (all four)
```

**The probe did not break the build. It stopped hiding that the build proved
nothing.** And the bill was paid twice over before anyone read it: two beta tags
were cut on a trunk whose only end-to-end evidence was a red X nobody opened.

## How it was found

Sideways, as always. The operator asked whether the repo was ready to prepare a
release — "zda máme všechno na dev, aktuální piny, otagováno" — and the tag
check ran into `gh run list --branch master`. Nothing in the estate reports the
trunk's CI state; `tools/red-status.py` surfaces it now, which is how it reached
an inbox at all, but it reads the newest run rather than the streak, so "red for
46 days" and "red once" render identically.

## A second thing this hid

The July note in CLAUDE.md — that `integration-linux` does not prove the
playbook because `docker compose up infra` returns rc=1 and the health probe
passes an empty stack as `0/0 ready` — is **out of date and was never
re-checked**. The 2026-08-28 run reaches `iiab: 3/3 ready` and `apps: 5/5
ready`. The stacks have been coming up for some time; the caveat outlived the
condition it described, and its presence made the red look expected.

## What closes it

Partly closed: PR #28 overrides `install_traefik=true` / `install_nginx=false`
on the Linux job only, so macOS keeps exercising the nginx vhost path that is
real there, and Linux gets the edge its platform actually uses. If the job goes
green, the wet-test is proving reachability for the first time since July; if it
stays red, what remains are genuine findings that were masked until now.

## What is still owed

- **A streak, not a state.** `red-status.py` reports the newest CI run. Nine
  failures in a row and one bad night look the same. A trunk gate that has been
  red for six weeks is a different fact from one that broke this morning.
- **Nothing refuses a tag on a red trunk.** `v0.10-beta` and `v0.11-beta` were
  both cut while this was failing. The release flow has no gate that reads CI.
- **The stale caveat.** CLAUDE.md still describes the July Linux behaviour.
  A note that says "this job proves nothing" is load-bearing in the wrong
  direction once the job starts proving something.
