# 26 — The state reader read an event

**Found 2026-08-23, while triaging the estate's oldest standing red.**

`tools/red-status.py` opens with the sentence it was built on:

> a notification is an **EVENT** and red is a **STATE**, and this estate had no
> cheap way to ask for the state.

Its own inbox line did not obey it:

```
14 unread CRITICAL/HIGH in the Wing inbox (77 unread total, oldest 29 d ago)
```

That counts **unread**, which is a property of a human's attention, not of the
estate. Four of the loudest were `security-drift` rows saying *"1 critical, 11
high pending"*. Every one of them was **true when sent** — on 2026-08-22 the
queue really did hold 11 pending HIGH — and every one is false now, because
they were closed that afternoon.

So the state reader was generating a red from a stale event. The exact thing it
exists to stop, in the one place nobody thought to look: itself.

## Why it was invisible

The four notifications look wrong and are not. Checking them meant
reconstructing the queue at four past timestamps from git — and coming back with
*"the notifier was right every time"*, which is not the shape of answer anyone
goes looking for. The defect is not in the notifier and not in the queue; it is
in reading a record of the past as a claim about the present.

Corroborating detail, because it is the one that settles it: the same batch of
notifications reported **11 pending HIGH** while `rem-status.py` on the same day
reported **2**. Both correct — five hours apart.

## What made the fix cheap

The emitters already record structured claims. 70 of the 74 unread rows carry
`metadata_json`, and the drift class carries exactly what is needed:

```json
{"pending_critical": "1", "pending_high": "11", "scan_age_hours": "5"}
```

That is a **measurable** claim against a **file** — which keeps the fix inside
this reader's charter (no network, no Docker, no daemon). `_still_holds()`
re-decides it against the queue as it is now.

Three answers, and the middle one is load-bearing:

| | meaning |
| --- | --- |
| `True` | the estate still holds at least what was claimed |
| `False` | provably answered since |
| `None` | **no re-checkable claim — UNKNOWN, never cleared** |

The `None` branch is where this could have gone badly. A version that returned
`False` when it could not decide would have quietly drained the red list, which
is a far worse defect than the one it replaced.

Today: **4 provably stale, 9 unverifiable, 0 re-checked-and-still-true.**

## A correction made on the way, worth keeping

The first cut printed *"9 unread CRITICAL/HIGH still hold"*. Those nine are the
**unknown** ones. Calling unknown "still true" is the same overclaim as calling
it "cleared", pointed the other way, and it took writing the sentence out to see
it. The line now names all three populations separately and asserts nothing it
did not measure.

## What is still owed — and it is most of the backlog

**Nothing marks a superseded notification read, so it sits for ever.** 75 unread,
oldest 29 days, and **60 of them are repeating classes** — `os-resume` 31,
`backup` 25, `security-drift` 4 — where each new send makes its predecessor
false by construction.

A reader may not write, so the fix belongs to the emitter: **a successor
supersedes its predecessors**, the same authorship rule that closes an abandoned
agent session ([25](25-a-repair-whose-trigger-was-superseded.md)). It needs a
state distinct from `read`, because nobody read them — `read` would be a lie the
estate told itself about a human. Roadmap `notify-supersede`.

Also owed:

- **Only one class is re-checkable today.** `backup` (25 rows) is next and its
  source — `~/.nos/backup-verify.json` — is already open in this file. `os-resume`
  (31) probably is not.
- **`prometheus-alert-relay` cannot be re-decided at all** from files; it would
  need Prometheus, and this reader must not reach a daemon. Those stay UNKNOWN
  by design, which is the honest answer and not a gap to close.
