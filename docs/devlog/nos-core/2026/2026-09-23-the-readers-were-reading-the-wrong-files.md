---
id: 2026-09-23-the-readers-were-reading-the-wrong-files
title: "The readers were reading the wrong files"
date: 2026-09-23
namespace: nos-core
summary: "A day spent on the instruments. The camera button had never stored a photograph; WordPress ran three releases ahead of its own pin with a CVSS 9.2 sitting in the gap; the security-scan age came from the git copy, not the scanner; and four of four HIGH dependency alerts were in a test fixture. Each was a reader confidently answering about something other than what was asked."
tags: [readers, security, nos-face, wordpress, ollama, red-status]
release: v0.13-beta
actors: [pazny]
related: [RELEASE.md, tools/red-status.py, docs/nos-cli.md, files/vuln-scan/scan-runner.sh]
---

Four things went wrong today and they were the same thing four times. In each
case a component reported a state, the report was believed, and the report was
about a different object than the one the reader had in mind.

## A camera button that could never have worked

The operator said the photo upload in Files opens the camera and stores
nothing. It was not the camera. SvelteKit's `adapter-node` caps an incoming
request body at 512 KB by default, and over the cap it does not refuse
politely — it **errors the request stream** that the BFF is mid-way through
piping to Bone. So undici raised `TypeError: fetch failed`, the endpoint
returned a bare 500, and nothing anywhere said "too large".

Measured on the running container: 100 KB uploads 200, 2 MB returns 500. Every
phone photograph is 2–5 MB. The feature had therefore never once stored a
document, and the same cap is why "Upload" failed too when the file chosen was
a photo.

Two components own a ceiling here — Bone's `_MAX_UPLOAD_BYTES` (what will be
stored) and the shell's `BODY_SIZE_LIMIT` (what may be received) — and a shell
cap below Bone's is exactly the bug. `test_face_upload_cap.py` reads both
numbers out of their real artifacts rather than trusting the comment that says
they match, and was run against the broken state before being believed.

The same path had a second, quieter defect: the explorer asked *"overwrite?"*
and never forwarded the answer, so Bone answered 409 and the file the operator
had just agreed to replace stayed put. A confirmation dialog that changes
nothing is worse than none.

## WordPress: the pin and the running code had diverged by three releases

`docker inspect iiab-wordpress-1` said `wordpress:7.0.4`. `php -r 'echo
$wp_version'` **inside the same container** said `7.1.2`. WordPress had
auto-updated its own files inside the volume.

So the site being served was patched, and the *image* was the exposure. Any
routine `docker compose up --force-recreate` would have restored 7.0.4's PHP
files under a 7.1.2 database and reopened CVE-2026-87902 — CVSS 9.2,
unauthenticated path traversal to remote code execution, affected range 4.7.0
through 7.1.1 — until the auto-updater noticed again. A window nobody would
have been watching, opened by an ordinary converge. The precondition that makes
it RCE rather than file-read, `register_argc_argv`, is on by default in the
official PHP images; measured here, it is on.

Docker Hub never published a 7.0.x image past 7.0.4, so no same-branch patch
exists: the branch hop to 7.1.2 *is* the fix. Converged and verified image ==
code.

The general shape is one this estate keeps paying for: **a version pin answers
"what will be deployed", never "what is running"**, and for any image whose
application self-updates, the two drift apart by design.

## "Security scan stale — 16 days" was about the git copy

`red-status` had been reporting a stopped scanner. Both `scan-state.json` files
exist and disagreed by sixteen days and nine cycles: the writer's target,
`~/.nos/security/scan-state.json`, read cycle 64 and thirteen hours old, while
the committed copy under `docs/llm/security/` read cycle 55. The scanner had
run that morning. `scan-runner.sh` says which is which in its own header — the
reader simply asked the wrong file.

The cost is not that a number was wrong. It is that sixteen days of false red
teaches its reader to skim the line, which is how a reader stops being read.
Both facts are kept now: the scanner's age, and separately the promotion lag,
because a fresh checkout genuinely does believe the older notebook.

## The scanner had found the WordPress problem — and graded it LOW, correctly

This is the part worth carrying forward. On 2026-09-15 the scanner filed
REM-255: it caught that the running container served 7.1 while the pin and
image said 7.0.4, named the mechanism (core background auto-update crossing a
major boundary), and wrote almost exactly the remedy shipped today. It graded
the security half **LOW**, and it was right *on that day*: 7.1 was strictly
newer than 7.0.4, so there was drift but no exposure.

CVE-2026-87902 landed on that range a week later, and nothing re-graded the
row. A severity is assigned once, against the advisories that existed at filing
time, and never revisited — so open findings decay silently, always in the
unsafe direction. Re-grading open rows against each new advisory wave is the
work this implies.

## Four HIGH alerts about code we do not run

Of 39 open Dependabot alerts, 33 pointed at `state/fixtures/repos-fixture/` — a
two-file fake repository the importer reads as *input*, never installs, never
builds, never ships. All four HIGH were in it, and one read "@sveltejs/
adapter-node has a BODY\_SIZE\_LIMIT bypass", patched in a version the shell is
several releases past. Reported on the same afternoon that `BODY_SIZE_LIMIT`
was being configured for real, it would have sent a reader to harden code that
does not exist.

The reader now separates what we ship from what we keep as input and prints
both counts. Silently shrinking 39 to 6 would have been the same defect wearing
a fix.

## Handing the memory back

Nothing in this repo had ever set ollama's `keep_alive`, so its five-minute
default hands a 14.9 GB resident model to whatever runs next. That residency
has now damaged three separate consumers: the KEAP API (0.09 s to 25 s), a
digest absorb that timed out so its queue row was never filed, and — twice
today — a converge that aborted for reasons having nothing to do with what it
was converging. Grafana was reported unhealthy while `docker ps` said
healthy-for-32-hours; it was slow, not broken, and a health budget cannot tell
those apart. An Authentik verify timed out at thirty seconds.

`nos models` and `nos models unload` ship. A shorter global timeout looks like
the obvious fix and is the wrong one: the invoice pipeline calls the same model
once per page, and reloading 14.9 GB between pages costs more than the
residency does. Residency is only waste once the *work* is finished, and a
timer cannot know that — so unloading is an act, not a timeout. Who calls it
automatically is still open.

## What this day does not claim

`loop:vision-bench` is green again on a live run — accuracy 0.965 over 17 runs
against a floor of 0.85 — now that one Pulse run may hold many agent sessions
instead of colliding on a single uuid. That is measured.

Not measured: the full converge to `failed=0`, and the smoke run. Two HIGH
findings from scan cycle 64 stand open by choice — n8n answers the public
internet ungated (REM-276), because its remediation is a path split that must
be tested alongside the operator's workflow activation rather than landed blind
the evening before, and REM-275's advisory floor sits above the current pin.
