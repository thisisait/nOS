---
id: 2026-09-20-release-v0-13-beta
title: "v0.13-beta — the firm desk is backoffice; praxis is a pack"
date: 2026-09-20
namespace: nos-core
summary: "72 commits after v0.12-beta. The public organ for CRM, books and a customer desk is named backoffice; praxis is the first pack inside it (Espo, KEAP tables, ISDOC and vision doors, HMAC approve). SOURCE only: a git ref is not a converge, and photo-to-booked is not proven live."
tags: [release, backoffice, praxis, digest, espocrm, gdpr, nos-face]
release: v0.13-beta
actors: [pazny]
related: [RELEASE.md, docs/doctrine/backoffice.md, profiles/praxis.yml]
---

`v0.12-beta` made the loop generated and visible. `v0.13-beta` asks whether a
consulting firm can sit at a **desk that is actually ours**: CRM, books,
invoice intake, a client portal, SSO, GDPR, backup — without a second ledger
and without a fifth host daemon.

The answer in this tree is a **pack**, not an organ. Apex publishes
**The Backoffice**. Praxis is Espo + KEAP tables + the invoice doors for the
first firm. Firefly and ERPNext stay off. WordPress is commons, not a second
backoffice. `profiles/praxis.yml` is the overlay a first Mac runs; the committed
defaults do not seed a synthetic tenant unasked.

## Doors, not a demo video

ISDOC dual-resolves seller and buyer, stamps `book_owner` only when that party
is on the document, and `attach_ledger` folds journal-entry + posting into the
same gated absorb. Isolation is analytical 311/321, not a database per client.
Rounding, reverse charge and dobropis have fixtures under
`state/fixtures/isdoc-realworld/`.

Vision Pulse writes `pending-invoice-verify`. HMAC `invoice-verify` and Face
Books approve; they do not insert invoice rows. `absorb-approved` is the
scheduled booker. Join key is `sidecar_id`, not slug.

Espo is a Tier-2 manifest. OIDC is a PUT after start. Party remains SoT;
Account.description carries `nos:party:<slug>`.

## Growth that must not leak

A guest SSO user must not read `invoice` / `party` through Face. The BFF GET
fails closed on visibility. KEAP's own agent RO bearer still does not see the
caller's tier — that door is named, not closed.

Leaving a client is not `remove=data`. `tools/offboard-book-owner.py` plans a
`book_owner` erasure and refuses a confirm token that is not the slug. Live
KEAP delete is not proven. Espo delete is still manual. Embeddings versus
Art-17 is unsolved.

Client-data training is a column (`party.training_opt_in`) default **false**.
Art-7 capture is still unwired. There is no Pulse job that trains on invoices.

Nightly copy #1 tars `dir-tenants` so PDFs under `incoming/` are not only in
`keap.db`. That is SOURCE wiring, not a restore drill.

## What this cut refuses to claim

photo→booked is not proven live. Client portal pages are not created. UC10
(fraud crosscheck) is blocked. UC13 (from-blank) is unrun. REM-249 stays
operator-gated. n8n does not drive invoices. The tag is not cut in this
narrative; `RELEASE.md` carries the same named red.
