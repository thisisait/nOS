---
id: 2026-06-01-gov-gdpr-compliance-batch
title: "Could nOS run a Czech government office? An honest audit, then a batch"
date: 2026-06-01
namespace: nos-core
summary: "A 25-agent adversarial audit scored nOS against GDPR, NIS2/ZKB, and Czech eGovernment law — verdict: not deployable, five structural absences. One batch later, four of them shipped LIVE-validated: enforced MFA, a FileVault/LUKS at-rest gate, AES-256 backup encryption, a tamper-evident audit hash-chain with WORM triggers, and a breach-notification engine with statutory deadline countdowns. The entry is equally about what's still open."
tags: [gdpr, compliance, security, gov]
actors: [pazny, claude]
related: [docs/compliance/gov-readiness-audit-2026q2.md, docs/security-baseline.md, profiles/gov-local.yml]
---
## The question worth asking adversarially

nOS already had real GDPR machinery — a CI-pinned Article 30 register fed
from every plugin's mandatory `gdpr:` block, an erasure runner, a DSAR
recorder. The question was whether that scaffolding would survive contact
with the actual bar: a Czech public-administration body acting as GDPR
controller and NIS2/ZKB regulated-service provider.

So the audit was built to be hostile: 25 agents in four phases — inventory,
assess, adversarial-verify, synthesize — where every positive verdict had to
survive an independent skeptic citing source files. The skeptics earned
their keep. They found three claims the docs made that the code didn't
implement: "Nightly encrypted backup" (the script piped `gzip | aws s3 cp`,
zero crypto), a Bone embeddings-redaction control declared in a plugin
manifest with no implementing line, and a `pazny.audit_retention` role
referenced in the security baseline that did not exist on disk.

The verdict was blunt: **cannot be deployed as-is.** Four structural
absences (no at-rest encryption, no MFA anywhere, no operational breach
notification, a mutable audit log), plus the greenfield Czech integration
surface (ISDS, NIA/eIDAS).

## The batch: structural controls, default-off

The remediation batch — built with a 15-agent design workflow and a 35-agent
adversarial review whose 22 findings were themselves fixed or triaged —
shipped the four structural controls, deliberately default-OFF with
`profiles/gov-local.yml` as the opt-in:

- **MFA** as a dedicated `nos-tier1-mfa-flow` (TOTP + WebAuthn), routed to
  Tier-1 providers, with passkey resident-key relaxed to `preferred` after
  live testing showed `required` failing first-try enrollments.
- **At-rest gate**: `tasks/preflight-at-rest.yml` hard-fails a gov run if
  FileVault/LUKS is off — honestly documented as a host-volume gate, not
  per-service TDE.
- **Backup crypto**: AES-256-CBC client-side in `backup.sh` *before* upload,
  which also retired the false claim.
- **Tamper-evident audit log**: HMAC hash-chain over `events` rows, SQLite
  WORM triggers blocking UPDATE/DELETE, and `verify-audit-chain.php` on a
  daily Pulse job.
- **Breach notification**: pure `BreachDeadlines` computing the Art-33/34
  and NÚKIB 24h/72h/1-month countdowns, filing CLIs, an hourly scan, and a
  Tier-1 `/breaches` view.

The GDPR-article surfaces landed alongside: all 31 boilerplate Art-30
purposes hand-authored plus a Controller/DPO block (coverage gate enforces),
Art-17 erasure with honest terminal status and exact-email-match deletes,
an Art-15 right-of-access export, and an Art-7 consent registry explicitly
decoupled from the old "SSO gate = consent" proxy. The whole batch was
LIVE-validated on a `+all +gov` reconverge, failed=0; the cold blank that
followed surfaced four real bugs (MFA blueprint atomicity, a Portainer
admin-init window expiring mid-blank, two probe fixes) — all closed.

## The honest ledger

The reconciled scorecard moved Art-32 from 38 to 62 and NIS2 from 33 to 52,
and the audit's own framing is the part worth preserving: the uplift is
*capability*, not yet *enforcement*. Retention is still metadata — only
`wing.db` events actually get purged. Erasure automation is 3 of 29 stores;
backups are never subject-purged. Consent capture is wired into nothing.
And the two genuinely Czech blockers — ISDS (datové schránky) and NIA/eIDAS
federation — remain greenfield: zero code, no pretending otherwise.

## Where it stands

nOS is still not gov-deployable, and says so in its own committed audit.
But the blocker set shrank from "four structural absences plus greenfield"
to "two greenfield integrations plus enforcement depth" — and every control
that does exist is pinned by a gate, validated on a live run, and described
in the docs exactly as strongly as the code deserves. That last property is
the one the audit was really for.
