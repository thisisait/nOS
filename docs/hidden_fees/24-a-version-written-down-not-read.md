# 24 — A version written down, not read

**Found 2026-08-23 by the nightly scan (REM-218, cycle 38), then reproduced
independently in one command.**

`default.config.yml:2371` read:

```yaml
freescout_version: "2.1.5-php8.3"   # nfrastack …; app 1.8.231 — REM-142 (7 GHSA fixes)
```

The container runs **1.8.230**, and always did:

```
docker exec b2b-freescout-1 grep -m1 "'version'" /www/html/config/app.php
    'version' => '1.8.230',
```

## The claim was impossible on the day it was written

FreeScout **1.8.231** was released **2026-07-25**. The image `2.1.5-php8.3` was
published **2026-07-18**. A 18 July image cannot contain a 25 July application.

Nobody needed the container to catch this — one subtraction would have done it.
What was missing was any reason to subtract, because nothing ever read the
number back.

## What it cost

REM-142 was **closed** on that premise. REM-193 was **filed** on it, its whole
text reading *"pinned app 1.8.231 lags security release 1.8.232"*. So for six
weeks the queue recorded as patched:

* **GHSA-m4hc-rc98-38jc** (HIGH) — a restricted agent lifts their own
  admin-imposed "see only assigned conversations" restriction.
* **GHSA-cr68-27qv-p5m4** (MEDIUM) — incomplete fix for CVE-2026-40570,
  cross-visibility customer data.

Both patched in 1.8.231. Both live.

## Why it was invisible, and this is the general part

**An image tag and an application version are two different numbers, and for
most services they happen to agree.** That agreement is what makes the
exception impossible to see. Measured across the estate today: gitea
`1.27.2`/`1.27.2`, bookstack `26.05.2`/`26.05.2`, keap `1.40.1-<sha>`/`1.40.1`
— three agreements and one silent divergence.

`tools/discovery-scan.py` compares the queue against `docker ps`, and `docker
ps` reports the **tag**. Every reader the estate had was on the wrong side of
that gap.

And the claim itself lived in a **comment**. The convention was already there —
`# … app 1.8.231 …` — it was simply never load-bearing. A claim that nothing
reads is a wish.

Sibling: [12](12-keap-image-tag-is-not-a-version.md) is the same headline with a
different mechanism — there the tag is *mutable*, here the tag is *unrelated*.
Neither is fixed by the other.

## What closes it

**`tools/app-version.py`** — asks each running container what version it *is*,
via a file the app ships or the binary's own `--version`, and compares that to
the `app X.Y.Z` claim parsed out of the pin's own comment. Deliberately not a
new field: the convention existed, it just needed a reader.

It reports the finding in one command, with three MATCHes for credibility:

```
freescout MISMATCH   tag 2.1.5-php8.3 (does NOT track the app) · app 1.8.230 · pin claims 1.8.235
gitea     MATCH      1.27.2
bookstack MATCH      26.05.2
keap      MATCH      1.40.1
```

`tag_tracks_app: false` marks a deliberate divergence — nfrastack ships
FreeScout 1.8.x inside images numbered 2.x — so upstream's choice does not
render as a defect.

Gate: `tests/anatomy/test_the_version_reader_asks_the_application.py`, whose
central assertion is that **no probe may read the image**. A probe that shelled
`docker inspect --format {{.Config.Image}}` would report MATCH forever and look
like a working tool. Proven in the failing direction.

**The pin is bumped** to `2.2.5` — note the suffix drop, the php8.3 line ends at
2.1.5 and 2.2.x is php8.5-only, verified by enumerating all 165 registry tags
rather than trusting the advisory. Recipe track `freescout-2.1-to-2.2` added.

## What is still owed

- **The bump is unverified.** `2.2.5` is *claimed* to bundle 1.8.235 and that
  claim comes from release notes — the same kind of source that was believed
  once already. `tools/app-version.py` will say, after a converge, and until
  then it correctly reports MISMATCH.
- **Four services are in the table; the estate runs about sixty.** Absence from
  it is not a claim of health. The entry cost is three lines, and the moment to
  pay it is when a pin's comment starts asserting a bundled version.
- **Nothing checks the arithmetic** — that a claimed app version postdates the
  image's publish date. Both numbers are available from the registry API and
  neither is in the repo. That check would have caught this without a container.
- **PHP 8.3 → 8.5 crosses a minor.** FreeScout 1.8.235 on PHP 8.5 is upstream's
  own supported line (they consolidated to php8.5-only at 2.2.0), but this
  estate has not run it. The STRICT health gate is what will say.
