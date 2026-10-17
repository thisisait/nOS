---
id: 2026-10-11-release-v0-16-beta
title: "v0.16-beta — the body has a plan, and every part knows its name and its owner"
date: 2026-10-11
namespace: nos-core
summary: "408 commits after v0.15-beta, written up after the fact (catch-up in the v0.17-beta release). Mostly words and places: a proposed body plan and a lexicon with one meaning per word, state/ grouped by realm, one registry of generated files, software_owner on every manifest row, twelve fixes from the first clean-machine deploy, a strict smoke that signs in, and KEAP's Hippocampus giving OpenHuman a local memory."
tags: [release, body-plan, lexicon, ownership, clean-machine, smoke, openhuman, keap]
release: v0.16-beta
actors: [pazny, claude]
related: [RELEASE.md, ssot/doctrine/body-plan.md, state/genome/lexicon.yml, state/generated.yml, docs/hidden_fees/60-an-estate-that-remembered-its-own-setup.md]
---

This entry was missed at the cut and is written one release later, from
`RELEASE.md` and `git log v0.15-beta..v0.16-beta`, so a reader of the devlog
does not find a gap where a tag is.

`v0.16-beta` changed little on the running estate. It changed what an agent
reads before it touches anything: what each part is called, where its files
live, and who owns it.

## One word, one meaning

`ssot/doctrine/body-plan.md` was proposed, not put in force: the levels of the
organism, and what each word may and may not mean. The lexicon
(`state/genome/lexicon.yml`, rendered to `docs/glossary.md`) gives each word one
meaning and a counter-example, and a gate refuses retired phrases in the files
an agent is told to trust. KEAP is memory, not a cortex. The imprint, the one
page a newborn model reads first, is rendered from both, never hand-written.

## Where things live, and whose they are

`state/` is grouped by realm (habitat, fixtures, law companions), and a converge
writes nothing into it. One registry, `state/generated.yml`, says who writes each
generated file and how to check it. Every manifest row carries `software_owner`:
self or symbiont; the face became a core organ.

## A clean machine is not a remembered one

The first deploy on a Mac that had never run nOS needed twelve fixes, each green
on an estate converged hundreds of times. Each got a gate; the account is hidden
fee 60, and whether a clean-machine converge becomes a release MUST is the
operator's decision.

## Green means the user got in

`nos-smoke --strict` stopped counting a bounce to the Authentik login as green,
and with the tester it signs in. The blank on 2026-10-09 ended with one failed
first login (WordPress, passed on `--tags identities`), smoke 50/50, strict
49/50, live E2E 339 passed. At the cut two Macs converged `failed=0`, one of them
the first converge on macOS 27.

## OpenHuman remembers in KEAP

KEAP v2.1.0 speaks OpenHuman's memory protocol under `/hippocampus`; every memory
is a row of the `engram` table, in backups like any other. Without it OpenHuman's
memory was their cloud or nothing.
