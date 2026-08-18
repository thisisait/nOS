# 17 — Wing's own dependency tree has never been audited

**Status:** OPEN as a class; the one instance it was hiding is paid. Found
2026-08-18 while adding an unrelated dependency.

## The fee

The security machine scans the estate thoroughly and from two directions:
`files/vuln-scan/scan-runner.sh` walks the service components on a nightly
rotation, and `docs/llm/security/remediation-queue.json` holds 202 rows of
findings against container images and their upstreams.

Neither ever looks at `files/anatomy/wing/composer.lock`.

That tree is not peripheral. It is what runs the **audit hash chain**, the
**AgentKit runtime** and every credential resolution, the **operator console**
that is Tier-1 RBAC, and the **Pulse API** the job daemon talks to. It is the
most privileged code in the estate, and the one dependency set nothing asks
about. `composer audit` — which ships with composer, needs no service, no key
and no network beyond packagist — has apparently never been run against it.

The same hole exists for the other language trees by the same argument:
`files/anatomy/bone/` (Python, holds the HMAC secret) and
`files/anatomy/face/` + `files/anatomy/cortex/` (npm). This entry is about the
class, not only the PHP half.

## What it was hiding

The first run, on the day the fee was found:

```
guzzlehttp/guzzle 7.15.1
  CVE-2026-69246  HIGH    noncanonical host can bypass host-based checks
  CVE-2026-69245  MEDIUM  noncanonical cookie domain keeps subdomain scope
```

Published 2026-08-03; found 2026-08-18, fifteen days later, by accident. The
fix was one patch release — 7.15.1 → 7.15.2 — and is applied: the lock is
bumped and `composer audit --locked` is clean. Guzzle is Wing's HTTP client,
so a host-check bypass sits directly under the code that calls Bone,
Authentik and every agent backend.

## Why it is a fee and not a bug

Nothing failed. The nightly scan ran and reported honestly on the components
it was given; the queue is accurate about what it covers. No layer's job was
to notice that a whole dependency tree was outside the sweep, and coverage
that was never claimed cannot go stale visibly. The scan-state file lists
components and their scan dates — and a tree that is not a component simply
does not appear, which reads identically to "nothing to report".

## When the bill comes due

- **Any CVE in this tree that matters more than a URL parser.** Nette's
  application/database/security packages, Latte, Tracy (a debug bar that can
  render stack traces), and the OTel exporter all sit here. The next one may
  not be a fifteen-day-old patch release.
- **The gov profile.** `docs/compliance/` treats the audit chain as a control;
  a control whose runtime has an unaudited dependency tree is a control with
  an unmeasured floor.
- **Any claim that the estate's supply chain is scanned.** It is scanned for
  images. Saying "scanned" without the qualifier is the kind of sentence this
  estate has had to retract before.

## How it was found

Sideways, per the entry test — `composer require ai-access/ai-access` printed
*"Found 2 security vulnerability advisories affecting 1 package"* as a footnote
to an unrelated spike. Nobody was looking; composer volunteered it.

## What closes it

Not a blocking pytest gate. `tools/rem-status.py` states the reason in its own
header: a gate that goes red because upstream published a CVE is red on a
calendar rather than on a defect, and CI would then be failing for something no
commit caused. The right shape is the estate's own — **a reader, wired into the
sweep that already exists**:

1. `composer audit --locked --format=json` over `files/anatomy/wing`, plus the
   equivalents for Bone (`pip-audit`) and the npm trees (`npm audit`).
2. Its findings entering `remediation-queue.json` through the same path a
   container CVE takes, so severity, disposition and `resolved_by` work
   unchanged.
3. The trees named as components in `scan-state.json`, so a tree that stops
   being scanned shows as `scan_failed` rather than as absence.

Until then the honest statement is the one at the top of this file: the sweep
covers images, not our own code's dependencies.
