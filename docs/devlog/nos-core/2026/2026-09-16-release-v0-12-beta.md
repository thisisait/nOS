---
id: 2026-09-16-release-v0-12-beta
title: "v0.12-beta — doctrine is a tree, the loop has a face, a proving instance runs"
date: 2026-09-16
namespace: nos-core
summary: "607 commits in the nineteen days after v0.11-beta (1107 files, +94k/−22k). v0.11 closed a loop no step can cheat. v0.12 makes that loop generated and visible, and the doctrine that lived as drafts becomes a cited tree. A four-hour repo-check is the proving instance. Anatomy replay stopped spreading a PK-keyed map as if it were a list. Woodpecker is the agent-forge CI. SMTP :25 stayed honest."
tags: [release, ssot, loops, nos-face, woodpecker, pulse, agentkit]
release: v0.12-beta
actors: [pazny, claude]
related: [RELEASE.md, ssot/INDEX.md, docs/doctrine/loops.md, files/anatomy/loops/repo-check.loop.yml]
---

`v0.11-beta` closed the propose → judge → drive → review chain so that no
participant writes its own outcome. `v0.12-beta` asks the next question:
**can an operator see that chain, can a loop be declared once, and does
doctrine cite like code?**

## Doctrine became a tree

Scattered `docs/doctrine/*.md` drafts were promoted into `ssot/` articles —
layers, identity, filesystem, gates, secrets, observability, face, loops,
operator-model, foreign-properties, virtiofs, workflows, generative-ui —
with an INDEX, citation rules, and an IDE wrap around `doctrine-cite --file`.
A cite that cannot resolve is a broken build, not a comment.

The constitution is no longer a memory. It is a path.

## The loop is generated, and one instance proves it

Pulse jobs for loops are harvested from `files/anatomy/loops/*.loop.yml` the
same way plugin manifests already were. Face draws the same files. news-scout
went from wiring to KEAP consolidation. **repo-check** is the proving
instance: four-hour cadence, red / estate / forge, report-only, nothing
applied. Overnight it ran five times at exit 0 with the forges identical.

Gitea is the agent-loop default when GitLab is declared off. The driver opens
the MR there; the reviewer still refuses on a red pipeline.

What the first live nights taught, and this cut pins:

- `loop:propose` exit 3 is **findings**, not a crash, when the job declares it.
- `loop:review` can be rc=0 with **zero merges** — Woodpecker red is a refusal,
  and that is the loop working.
- Anatomy replay asked Wing for `pulse_runs` and spread the JSON as an array.
  Nette Selection keys by `run_id`, so the payload was a UUID map and the
  table was empty against a healthy API — the same class Face already handled
  for `pulse_jobs`. `array_values` at Wing; `asKeyedList` at the Face BFF.
- The catalog's `{{ ansible_facts['env']['HOME'] }}` token inherited process
  `HOME`. The join gate reads `NOS_*` exports. CI went red on a name
  `post.yml` never declared. It is `NOS_HOME` now.

## Face shows the planner, not a second truth

The planner grew a roadmap graph (slice 1–4), a loops view from the ledger,
a routing graph, and a live-run overlay. One loop at a time. The overlay
counts SERE stages; it does not invent RSI. Dark chrome and pan/zoom are
polish on that contract, not a new one.

## AgentKit held to the September rulings

Five rulings (2026-09-02) are written down. MiniMax is armed for the bound
ceremonies that may use it; code-authoring stays on the default backend.
Agents got a DataTables verb surface and a read-only cortex-query skill.
A ceremony is not billed for inherited weather.

## Local CI is a forge, not a memory

Woodpecker pytest reds that had been sitting on `dev` were landed. The frozen
`tools/ci-local.sh` lane remains the 1:1 GitHub-runner mirror. SMTP's
healthcheck still probes published `:25`; STRICT wait **admits** unbound
smtp rather than lying the probe back to `:8080`.

## What did not get done, said plainly

GitHub CI on `master` was already red before this tip; the HOME join is why
the newest `dev` pytest failed, and that fix is in this tag — it is not yet
proof that Integration on `master` is green. The `master` ruleset still
requires signed commits and is still bypassed. REM-249 and REM-250 passed
the judges and wait on Woodpecker, not on another propose. Email is still
untestable on this estate. upgrade-architect:recipe-author is paused and has
never run. Four `-beta` drop criteria from v0.11 remain unmet.

None of that is hedging. The loop's own rule, applied to the notes: absence
of evidence is not recorded here as success.
