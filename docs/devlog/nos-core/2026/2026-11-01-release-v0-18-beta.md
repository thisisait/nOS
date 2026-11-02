---
id: 2026-11-01-release-v0-18-beta
title: "v0.18-beta — the medulla wakes, and a blank teaches the backup to keep what it was given"
date: 2026-11-01
namespace: nos-core
summary: "DRAFT, not cut. 862 commits after v0.17-beta. One Rust core fires the schedule, holds the halt and the settings, and gets a native face (nOS.app). Iris starts sub-agents and hears them end, live. The 2026-10-30 blank went green and the days after showed what green had hidden; each defect is now pinned by a gate or a drill. A second host, Ubuntu on a small Intel box, was installed from nothing and reached SSO over mDNS, with every defect fixed in the repo. Eight security bumps, and an advisory reader found to be wrong in both directions."
tags: [release, medulla, nos-app, iris, backup, blank, restore, advisories, paperclip, linux, mdns]
release: v0.18-beta
status: draft
actors: [pazny, claude]
related: [RELEASE.md, files/anatomy/thalamus/medulla, files/anatomy/thalamus/app, roles/pazny.backup/files/backup-verify.sh, tasks/_restore_postgres_db.yml, tools/advisory-patrol.py, tools/paperclip-company.py, state/genome/advisory-judgements.yml]
---

`v0.18` set out to give the estate one Rust core that runs it — the medulla —
and to let Iris delegate. Both landed in code. What the release will be
remembered for, though, is a blank.

## The blank on 2026-10-30

`nos --remove=data --confirm`, then `nos`. The converge went green. The next
seventy-two hours were a list of what green had not said:

- **03:00, the nightly backup.** It dumped the freshly blanked estate over the
  good dumps in staging: Paperclip 6.2 MB → 80 KB, the directory 726 MB → 4 MB.
  The pre-wipe restic snapshot is what saved the company. Now a blank clones its
  dumps to `~/backups/pre-blank/<stamp>`, and a dump that shrinks below 10 %
  keeps its predecessor as `.prev` and turns red-status red (`9a815ff1`).
- **The restore.** `restore_postgres_dbs=paperclip` brought back one database
  alone, the live one kept beside it — and Paperclip restarted 74 times on
  "permission denied". Three tables in the dump were owned by `postgres`. The data
  was all there; the service was not. Every relation is now given back to the db
  owner after the replay (`a1792602`), and the weekly drill replays every per-db
  dump into a throwaway Postgres and counts the rows (`fa28cbc0`). The drill used
  to open three SQLite files. Restore into a side instance, with a login, is still
  to be built (row `backup-dna`) — a client handover may not promise it yet.
- **Kiwix.** The blank deleted the downloaded ZIM library, the converge stopped
  on "press ENTER", and when a ZIM did arrive the server kept answering 502: its
  entrypoint slept forever when it started empty. Three fixes, the last one a
  loop that waits for a ZIM (`e8bd5881`). Smoke `--strict` went 31/32 → **32/32**
  on 2026-11-01.
- **No more ENTER.** A converge nobody watches must not wait. The onboarding
  prompt is a warning; a refused MariaDB root login fails instead of skipping
  every later task; the gate's allowlist lost its "open" rows. Seventeen hints
  that told the operator `ansible-playbook main.yml --tags …` — which asks for sudo
  twice on the estate — now say `nos --tags …`.

## The medulla and its face

`nos-pulse serve` fires the Pulse jobs; `medulla state`, the socket and
`/api/v1/admin/state` answer one struct; `medulla halt|resume` holds the halt,
recorded in Wing with the person and the bearer; the settings store holds
`pulse.paused`. nOS.app — SwiftUI, built with SwiftPM, signed locally — shows it
in the menu bar, halts with a native confirm and opens the face. Not yet:
Developer ID and native approvals.

## Iris delegates

`start_agent` asks the person, then starts a Wing run with their bearer;
managers may start read-only sub-agents; the end comes back as a card, not as
text injected into her context; `stop_agent` is refereed by Wing; `read_run`
draws the run as a tree. On 11-02 it ran live on the Studio: run `0153c4c7`,
parent `thalamus:a03c5f17`, the report shown, the tree drawn.

The loop half went less far. Iris guessed runner paths and `for_each` flags
until she dropped `run:` altogether; the validator only said "no". Its refusals
now name the runners that exist and the fix, and her next draft,
`repo-health-check`, was valid and runnable. The operator did not file it — it
duplicates `repo-check` — so filing, a Pulse run and her analysis move to v0.19.
She answers sensibly on the local model, but slowly enough to be hard to use.

## A second host, from nothing

A small Intel box (i5, no AVX2) was installed from a USB stick and converged
from the repo the way a stranger would. The rule was that nothing is fixed on
the box: each defect went back into the repo and the box ran `nos update` and
`nos` again.

- `bootstrap.sh` now takes a fresh Ubuntu to a first `nos`; preflight stops
  early with the fix (missing passlib, a weak prefix, toggles typed as text).
- A `.local` tenant is published over mDNS. The first version collided on the
  reverse record, then could not reach D-Bus, then hid the failure behind a shell
  `wait`. It now publishes each name with no PTR, as `avahi`, and exits when one
  publisher dies. From the Studio `kiwix.mini.local` resolved and SSO worked.
- A fresh host minted the v2 secret scheme, so the operator's old
  `<prefix>_pw_…` habit was wrong and nothing said what was right. A converge
  now ends with how to log in and how another machine trusts the CA — never a
  secret.
- With the medulla as a system service, Wing kept its old groups until a
  reboot, could not see `/var/lib/nos/settings`, wrote the halt to `~/.nos` and
  answered success, while Pulse read the other file. An ACL fixes it for the
  operator; the fallback itself should refuse (row `set-point-stray-file`).

Journeys there: 40/41, the one miss Iris on a CPU she cannot use.

## Advisories, walked by hand

On 10-31 every advisory match was walked through with the operator. Eight bumps
went live on 11-01 (n8n 2.37 → 2.45.7, WordPress, Grafana, Redis, Uptime Kuma,
FrankenPHP, Santa, cortex `qs`), thirty-two matches were judged in
`state/genome/advisory-judgements.yml`. Two lessons:

- **The reader is wrong both ways.** It raised false alarms on multi-bound ranges
  (Jellyfin, Gitea) and — worse — showed n8n with one advisory while about forty
  applied, some reachable without a login. Red-status under-reported. Row
  `advisory-range-parse`.
- **FrankenPHP rebuilds its release binaries every night** and overwrites them,
  so a sha256 pin is stale within a day. The new binary was genuine (`gh
  attestation verify`); the pin was re-made. Provenance instead of bytes is row
  `frankenphp-nightly-digest`.

The patrol itself reported a finding with exit 1 — the same code a crash
produces. It now exits 10 / 11 (`fd394782`).

## Companies of agents

A Paperclip company is now declared in its own repo (`ssot/company.yml`,
`agents/<name>/AGENTS.md`) and applied through Paperclip's API
(`tools/paperclip-company.py`). Its first use rebuilt a ten-agent company that
had spent $81 in three hours on unlimited Opus.

## What is not true yet

CI was red on dev from 10-29 to 11-01, and once more on 11-02 (a lint error the
local suite does not run, then a gate committed before the graph it reads was
regenerated); green at `27390c4b`. A second blank of the Studio is the last step
before the cut. The USB installer exists on a branch and stays there until it
has been reviewed more than once. A loop from Iris is proposed, not yet run.
