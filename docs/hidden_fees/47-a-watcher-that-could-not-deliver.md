# 47 — A watcher that exits zero on a critical it could not deliver

**Found** 2026-09-02 (external audit; named in active-work for weeks, never a
fee); **closed** 2026-09-03.

## What it looked like

`files/anatomy/scripts/drift-watch.sh:21` — "Exit 0 always (a watcher must not
fail the Pulse runner)", written into the header as doctrine. Consequence: a
CRITICAL security verdict with `WING_EVENTS_HMAC_SECRET` unset, or with the
notification POST failing, exited 0. The verdict existed; nobody could ever
learn of it; the run was green.

Fee 07 already named the rule this violates: a step that cannot do its job
must not exit 0. The header sentence was the violation, in writing.

## The close

`sev == critical` + undeliverable (either path) → exit 1. Pulse records
non-zero exits — that is what a watcher job's exit code is FOR. High/stale
verdicts keep the tolerant exit. Gate in
`test_the_silent_trio_can_now_fail.py` pins both refusing paths, retro-verified
by neutering one and watching red.
