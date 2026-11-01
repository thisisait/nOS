---
id: 2026-11-01-release-v0-18-beta
title: "v0.18-beta — the medulla wakes, and a blank teaches the backup to keep what it was given"
date: 2026-11-01
namespace: nos-core
summary: "DRAFT, not cut. 773 commits after v0.17-beta. One Rust core fires the schedule, holds the halt and the settings, and gets a native face (nOS.app). Iris starts sub-agents, hears them end and can propose loops. The 2026-10-30 blank went green and the days after showed what green had hidden: a nightly that overwrote good dumps with empty ones, a restore that brought the data back but not the service, a Kiwix that slept forever. Each is now pinned by a gate or a drill. Eight security bumps, and an advisory reader found to be wrong in both directions."
tags: [release, medulla, nos-app, iris, backup, blank, restore, advisories, paperclip]
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
draws the run as a tree. She can read loop runs and propose a loop — filing it
stays the operator's. None of this has run end-to-end live yet; that is an exit
criterion, not a footnote.

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

CI was red on dev from 10-29 to 11-01 (a lint error the local suite does not
run, then a gate the full run caught); green again at `7bc17c34`. No second host
converged this release. The e2e journeys last ran on 10-09. A second blank —
after Paperclip re-boarding is tested — is planned before the cut.
