# 63 — What Iris and the medulla do not see

**Found** 2026-11-01 (release-prep v0.18-beta, harvesting the `ponytail:` comments
added since v0.17-beta); **open** (carried on purpose, each with its upgrade path).

## The fee

Six limits shipped in v0.18-beta answer normally when they are reached. Nothing
fails, and the answer looks complete:

- **A sub-agent's report under 500 events is lost.** `files/anatomy/wing` run read
  (`4a95b5db`) takes the newest 500 events; a report buried under more comes back
  `null`, and Iris says the run reported nothing. Upgrade: a type filter in SQL.
- **A run started before a reconnect cannot be stopped from Iris.** `stop_agent`'s
  table of started runs is not rebuilt on resume (`31aca64c`); the stop answers "not
  mine". Upgrade: rebuild from Wing's runs for the person on resume.
- **A run's end is heard only by the connection that started it** (`4c79956c`): a
  closed or switched session hears nothing; `read_run` still draws it. Upgrade: the
  end as a ledger event any session replays.
- **A cancel can land on a run that just closed** (`acf9d067`): read then write; the
  run is recorded as cancelled though it finished. Upgrade: one conditional UPDATE.
- **A flooding Pulse job is held whole in memory** (`011a296c`): each stream is kept
  to EOF, as Python's `communicate()` did; a job that writes gigabytes grows the
  medulla with it. Upgrade: a bounded ring, keeping only the tail the record stores.
- **Organ identity is an argv prefix match** (`aec2c013`): two organs sharing an
  argv0 would be counted as one. Upgrade: the pid from launchd / systemd.

## When the bill comes due

The first sub-agent that logs more than 500 events before its report; the first
time the operator restarts the thalamus while Iris has a run going; the first Pulse
job that floods stdout (a verbose scan); the first host organ wrapped by another
organ's binary.

## How it was found

Not by a failure. Each was written down as a `ponytail:` comment when it was built,
and the release harvest (`git log -p v0.17-beta..dev -S'ponytail:'`) collected them.
The other fourteen comments from that harvest are ceilings that refuse or fall back
visibly (a strict parser, a fixed retry, a phrase match marked as such) and stay
where they are written.

## What closes it

Each line's upgrade, when its bill arrives — or sooner for the first two, which
decide whether Iris's delegation (the v0.18 thesis) holds once runs get long.
