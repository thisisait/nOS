---
id: 2026-06-01-release-v0-4-beta
title: "v0.4-beta — Linux, byte-identical on the Mac"
date: 2026-06-01
namespace: nos-core
summary: "One tag, two big moves: the playbook now provisions Ubuntu 24.04 end-to-end while staying macOS-byte-identical (every Linux gate resolves true on a Mac), and a Czech public-administration audit drives a gov/GDPR remediation batch — enforced MFA, at-rest gates, encrypted backups, a tamper-evident audit hash-chain, and a breach-notification engine — all default-OFF behind a gov profile. Plus a CVE batch that uncovered the dead-pin shadow trap."
tags: [release, linux, cross-platform, gdpr, compliance, security, mfa, idempotence]
release: v0.4-beta
actors: [pazny, claude]
related: [RELEASE.md]
---
Two themes that sound unrelated — cross-platform and government compliance —
share one engineering principle in this tag: **new capability must not move a
single byte for existing users**. Linux gates resolve true on a Mac; gov
controls ship default-OFF behind `profiles/gov-local.yml`. A non-gov macOS run
before and after v0.4-beta renders identically.

## The platform seam

`tasks/_platform.yml` resolves `nos_pkg_manager`, `nos_service_manager`, nginx
paths and the docker binary per OS, and every Homebrew install, `launchctl`,
`osascript`, `defaults` and `pmset` call is gated on the resolved facts. On
Linux: Bone, Pulse, backup and heartbeat render `systemd --user` units with
linger enabled; Wing runs the FrankenPHP single binary from `~/.local/bin`;
mkcert installs via apt with a platform-aware CAROOT; Traefik is the edge
proxy (host-nginx vhosts stay macOS-only). A standing
`Integration (ubuntu-24.04)` CI job now wet-tests `ansible-playbook main.yml`
on a real Linux runner. The honest footnote ships in the code itself: the Wing
FrankenPHP path carries `NEEDS-VM-VALIDATION` markers — CI-exercised, not yet
full-runtime-validated on a physical Ubuntu box.

A small gem from the port: a systemd `Persistent=` timer's bound oneshot can
fail at provisioning time because the service it triggers isn't ready when the
timer starts — that failure is now tolerated by design, not retried into
submission.

## Gov compliance — structural controls, honest gaps

The 2026-05-31 audit verdict was blunt: not gov-deployable, five P0 blockers.
This batch closes the structural four:

- **Enforced MFA** — a dedicated `nos-tier1-mfa-flow` (TOTP + WebAuthn),
  routing all 9 Tier-1 providers, with `configure`-not-deny semantics: an
  un-enrolled user self-enrolls inline, never hits a lockout. The first
  blueprint version was atomically rejected over a binding to a non-existent
  stage — the fix drops the brittle bindings and reorders apply so the MFA
  flow exists before the providers that reference it.
- **At-rest gate** — hard preflight fail on FileVault-off / no-LUKS before any
  personal-data service starts.
- **Backup encryption** — AES-256-CBC client-side stream filter before objects
  reach RustFS, with a `resolve_openssl` shim to survive launchd's PATH and
  macOS LibreSSL quirks; restores auto-detect `.enc` and fail loud on a wrong
  passphrase.
- **Tamper-evident audit chain** — an HMAC-SHA256 per-event hash-chain with
  byte-parity proven between the Python (Bone) and PHP (Wing) writers, WORM
  triggers on signed rows, and a daily verify cached so rendering the header
  badge costs one SELECT, not a chain walk.

Plus a breach-notification engine (pure-math Art-33/NIS2 deadline clamps,
hourly escalation scan, provably inert on an empty register) and the GDPR
subject-rights surface: consent ledger, audited right-of-access export, and
honest Art-17 erasure — exact-email matching to prevent cross-subject erasure,
and a DSAR status that only reads `completed` when zero manual steps remain.
The release notes keep a "Residual gaps" section on purpose: consent capture
is unwired, retention is metadata-only, ISDS/NIA federation is greenfield.
Compliance theater is a bug class too.

## The dead-pin shadow

The CVE batch (n8n RCE trio, Tempo S3-key exposure, FreeScout CRITICAL access
control, ntfy) surfaced a trap worth a memory entry: service version vars live
in **both** `default.config.yml` and role defaults, and vars_files outrank
role defaults — so bumping only the role default produces a pin that renders
nowhere. A live n8n RCE pin was dead on arrival until the unshadow commit
synced the pins to `default.config.yml`. New rule: bump the config, then
verify the running image tag.

## Idempotence as a feature

The macOS Integration re-run finally reports `changed=0`: `wing_api_token`
(regenerated every run, churning Pulse's launchd plist and every agent bearer)
is now persisted in `~/.nos/secrets.yml` with four sibling tokens; volatile
`generated_at` footers were dropped from renders no consumer reads; PECL,
dotnet, and service-start tasks key `changed_when` off real state.

## Validation

Linux: standing ubuntu-24.04 CI wet-test green. Gov: LIVE-validated on a
`+all +gov` reconverge, `failed=0`, with `gdpr_consent` migrated on the real
`wing.db` and all 31 boilerplate Art-30 purposes replaced by authored ones —
enforced from here on by a CI coverage gate.
