---
id: 2026-11-03-security-day
title: "A security day before the cut: an agent's read tool could run code"
date: 2026-11-03
namespace: nos-core
summary: "Four read-only review agents, a GET-only pentest of the mini's SSO layer and a CVE sweep, on the day v0.18-beta was to be cut. The SSO layer held. Two holes did not: the read tool every reading agent holds let a prompt-injected agent run code as the operator through git's fsmonitor, and the mDNS publisher written two days earlier put container labels unquoted into a shell. Both fixed with gates that run the real code; the rest went to the roadmap."
tags: [security, agentkit, mdns, pentest, advisories, immune]
release: v0.18-beta
status: draft
actors: [pazny, claude]
related: [files/anatomy/wing/app/AgentKit/Tools/BashReadOnlyTool.php, tasks/mdns.yml, tests/anatomy/test_an_agent_read_tool_cannot_write_or_exec.py, tools/advisory-status.py]
---

The plan for 3 November was a blank and a cut. The operator asked for a
security check first, and then another one.

## What held

A pentest of the mini's SSO layer, GET requests only: ten ways around
forward-auth (double slashes, encoded dot-dot, `.well-known`, forwarded and
original-URL headers, a trailing dot in the Host), injected `X-Authentik-*`
identities at Wing and KEAP, the enrolment, recovery and initial-setup flows,
an open redirect in `?next=`. Every one ended at Authentik's login, or at a
401 that said the request had not come through the proxy. The active port scan
was refused by the agent's own safety layer; a repo-only review of the intended
exposure found 80, 443 and 22 open with stock defaults.

## What did not

**The read tool.** `bash-read-only` is what the librarian, the curator, the
surveyor, the conductor and the architects use to look at the repo. It ran
argv without a shell and blocked a list of git's exec flags. It did not look at
the subcommand. `git config --global core.fsmonitor <cmd>` passed, and HOME was
passed through, so it wrote the operator's `~/.gitconfig`; the next `git status`
in any repo ran `<cmd>`. A KEAP record or a web page an agent reads is enough to
ask for that. `rg --pre` ran a program outright, `tree -o` and `git diff
--output` wrote files, and `cat ~/.nos/secrets.yml` returned every bearer the
estate has. The old gate grepped the PHP source; the new one runs the tool under
PHP against a temp home that looks like the live one (the checkout agents read is
`~/.nos/estate`, beside the secrets), red three of four on dev.

**mDNS.** Written on 1 November so that a `.local` tenant resolves on Linux, the
publisher read every `Host()` from Traefik's files and from the labels of every
running container, and wrote each name into a systemd unit's `bash -c`. A label
`Host(\`a;touch …;b.mini.local\`)` ran as avahi at every boot. The fix keeps only
DNS names; the first attempt at it also added a comment with an apostrophe
inside the shell body, which Ansible read as an open quote, and dev did not load
for an hour.

## What the patrol cannot see

The operator had heard of a new hole in Ubuntu 24.04 and one in Playwright. Both
were real (a remote kernel TCP use-after-free with its fix only in -proposed;
Chromium inside Playwright, unfixed upstream) and neither showed anywhere,
because the advisory patrol reads pins and lockfiles, not host packages, not a
pending reboot, not a browser that an npm package downloads. That is a row now,
not a miss.

## Where it goes

The deep probes are moving out: `nos-immune`, a repo of its own that attacks a
running estate from another host with its own short-lived identity, while nOS
keeps the innate part — readers, smoke, verify, patrols, the guards themselves.
The disk the operator wanted back is not in the tests (one percent of a
worktree) but in Rust's `target/` (seventy-seven).
