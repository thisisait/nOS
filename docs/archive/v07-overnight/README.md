# v0.7 overnight plans — archived 2026-08-02, unimplemented

38 plan documents, **11 230 lines**, all authored on 2026-06-14 in one batch and
all naming the same target branch: `feat/v0.7-overnight`.

**That branch has zero commits that are not already in `master`.** None of these
were implemented. They read as a plan and were not one — while they sat in
`docs/plans/`, that directory overstated what was planned by roughly a factor of
two, which is the reason they are here rather than there.

They are archived, **not deleted**, because several contain real analysis that
was never wrong — only never acted on. Inbound links between them are preserved:
the whole block moved together, so relative references still resolve.

## What is still live, and where it went

Anything from this batch that still matters was folded into `docs/idea/` during
the 2026-08-02 consolidation. Specifically worth knowing:

- **`v07-darwin27-*` (16 docs)** — a macOS 27 "Golden Gate" readiness sweep.
  The live successor is `docs/archive/macos27-golden-gate-readiness.md`; the
  ansible-core 2.24 item survives in CLAUDE.md's tech-debt list.
- **`v07-sec-*` (6 docs)** — superseded by the live remediation queue,
  `docs/llm/security/remediation-queue.json`, which is scanner-maintained and
  reconciled against `docker ps`.
- **`v07-sso-*` (7 docs)** — the SSO trichotomy and its per-service verdicts are
  doctrine now, in `docs/sso-and-attribution.md`.
- **`v07-gov-p0-isds-niaeideas-greenfield.md`** — still genuinely open, and the
  only P0 in the batch. Tracked in `docs/compliance/`.

## The rule this batch teaches

A plan that names a branch should be checked against that branch. Thirty-eight
documents claimed a destination that never received a single commit, and nothing
noticed for seven weeks because nobody compared the claim to the repository.

**At the next release, reconcile this directory and delete what has no successor.**
