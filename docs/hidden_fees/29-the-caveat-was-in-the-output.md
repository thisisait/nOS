# 29 — The caveat was printed, and the consumer ignored it

**Found 2026-08-23, three times in one day, by three different consumers of one
reader.**

`tools/tls-uptake.py` ends its PostgreSQL block with a sentence it prints every
single run:

> this is ONE SAMPLE of live backends — a client whose pool is idle does not
> appear at all, so absence here is not evidence that it connects encrypted

That sentence was written deliberately, by the same hand, one day earlier. Then:

| consumer | what it did | how long it was wrong |
| --- | --- | --- |
| `sec-transport-hedgedoc`, first cut | counted plaintext hedgedoc backends, required zero — hedgedoc's pool was idle, so it returned `confirmed` immediately | minutes |
| `sec-transport-pg` | required no plaintext backend *in the sample*; one sample in four missed hedgedoc entirely and read 38-of-38 | a day, and it flipped a roadmap row to `confirmed` |
| the MariaDB block itself | reported a ratio **cumulative since server start**, which cannot move after a fix, so no rung was verifiable by it at all | since the reader was written |

Measured directly, four consecutive samples seconds apart:

```
n=41 users=authentik,hedgedoc,metabase,miniflux,paperclip,postgres  plain=['hedgedoc']
n=41 users=authentik,hedgedoc,metabase,miniflux,paperclip,postgres  plain=['hedgedoc']
n=42 users=…,outline,…                                              plain=['hedgedoc']
n=38 users=authentik,metabase,miniflux,paperclip,postgres           plain=[]
```

The fourth line is the whole fee. Nothing changed on the estate between them.

## Why a printed caveat does not protect anything

Because it is prose in a human render, and the consumers are programs reading
`--json`, where the sentence does not exist as a field. The `basis` key on the
MariaDB block says `"cumulative since server start"` and nothing was ever going
to read it. **A caveat that lives only in text is a comment**, and this
repository already knows what comments are worth against a detector: they get
matched as facts (`detectors-must-read-artifacts-not-prose`) or, as here,
skipped entirely.

The reader was honest. It said what it could and could not support, in the
place a person would see it. It just had no way to make a *consumer* honest,
and three consumers in a row were written by someone who had read the sentence
that morning.

## What it cost, exactly

`sec-transport-pg` reported **done**. It went into a handoff as *"the probe
reads the effect, so it flipped on its own"* — offered as evidence that the
system self-verifies. It had flipped on a sampling accident, and the one client
that was still plaintext was the very one the sample missed.

That is worse than a probe that fails, because a failing probe gets
investigated.

## What closes it, and what does not

**Not** a louder caveat. The fix in each case was to change the QUESTION from
one absence cannot answer to one it cannot fake:

- `nothing-plaintext-in-this-sample` → **`present-and-encrypted` for a NAMED
  set**, reporting `unsampled:<who>` when a required client is not there. An
  idle client now makes the probe say *"I could not tell"*, which is the true
  answer.
- the cumulative ratio → **`--window N`**, the delta over the last N seconds:
  the fraction of connections opened *just now* that were encrypted. A window
  in which nothing connected reports **no rate at all** — never 0, never 100.
- and each probe now **echoes its verdict** instead of swallowing it (see
  below), so the evidence a roadmap row stores says which of the outcomes
  happened.

## A second, smaller defect found on the way, and it is the same shape

Nine probes were written as:

```sh
test "$(python3 -c '…print(verdict)…')" = "expected"
```

The verdict goes into the command substitution and reaches nobody. The
`sec-backrest-auth` probe carried a comment claiming *"it now PRINTS which of
the two happened, and roadmap-verify keeps stdout as evidence"* — and
`roadmap-verify` does keep stdout, and stdout was **empty**. The probe was
right, and mute, and its own comment said otherwise.

Fixed to `v=$(…); echo "$v"; test "$v" = …`, with every rewritten probe's exit
code compared before and after so the change is provably behaviour-preserving.

## The rule

**An honest reader cannot make a dishonest consumer honest.** If a measurement
has a condition under which it means nothing, the condition belongs in the
*data* — a field, a distinct verdict string, an absent value — not in a
sentence beside it. `None` for "no rate" is worth more than a paragraph
explaining when the number lies.

## What is still owed

- **Seven other probes read `tls-uptake.py` or a sibling and have not been
  audited against this.** The two fixed here were fixed because they failed
  loudly; the rest have not been sampled repeatedly to see whether they flap.
- **No probe declares its own sampling requirement.** `sec-transport-pg` now
  hardcodes five expected users inside the probe string. That list will rot,
  and nothing will notice until a service is renamed — at which point it reads
  `unsampled:` for ever, which is at least the safe direction.
