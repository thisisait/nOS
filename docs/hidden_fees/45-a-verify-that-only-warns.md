# 45 — A verify that only warns

**Found** by an external repo audit 2026-09-02; **closed** 2026-09-03.

## What it looked like

`tasks/iiab/stack_verify.yml` — a task file NAMED verify, TAGGED verify, whose
every `uri` probe carried `failed_when: false`, whose failures surfaced as a
`debug` WARNING, and whose summary was a `debug`. Nothing in the flow could
fail the play. A converge with dead infra stayed green through the very step
that claimed to confirm "all services respond".

## Why it hid

The word. Portainer's silent verify got a gate when it was caught; this one
carried the same name and nobody looked twice. The STRICT compose health-wait
upstream made it FEEL covered — but that proves the container, not the service.

## The close

An `assert` on `_auto_failed` after the retry pass: infra still dead after two
minutes of retries is a red converge. Onboarding stays tolerant (interactive by
design). Gate: `test_the_silent_trio_can_now_fail.py`, retro-verified by
deleting the assert and watching it go red.
