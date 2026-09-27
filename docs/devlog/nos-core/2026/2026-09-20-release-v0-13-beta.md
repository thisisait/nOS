---
id: 2026-09-20-release-v0-13-beta
title: "v0.13-beta — the firm desk is backoffice; praxis is a pack"
date: 2026-09-20
namespace: nos-core
summary: "183 commits after v0.12-beta. The public organ for CRM, books and a customer desk is named backoffice; praxis is the first pack inside it — Dolibarr as the desk, KEAP tables, ISDOC and vision intake, HMAC approve. A photographed invoice reached a balanced ledger on this estate; the from-blank path did not."
tags: [release, backoffice, praxis, digest, dolibarr, gdpr, nos-face]
release: v0.13-beta
actors: [pazny]
related: [RELEASE.md, docs/doctrine/backoffice.md, profiles/praxis.yml]
---

`v0.12-beta` made the loop generated and visible. `v0.13-beta` asks whether a
consulting firm can sit at a **desk that is actually ours**: CRM, books,
invoice intake, a client portal, SSO, GDPR, backup — without a second ledger
and without a fifth host daemon.

The answer in this tree is a **pack**, not an organ. Apex publishes
**The Backoffice**. Praxis is **Dolibarr** as the desk plus KEAP tables and the
invoice doors for the first firm — EspoCRM was tried and retired mid-cut, and
its tombstone ships with it. ERPNext stays off. WordPress is commons, not a
second backoffice. `profiles/praxis.yml` is the overlay a first Mac runs; the
committed defaults do not seed a synthetic tenant unasked.

## Doors, not a demo video

ISDOC dual-resolves seller and buyer, stamps `book_owner` only when that party
is on the document, and `attach_ledger` folds journal-entry + posting into the
same gated absorb. Isolation is analytical 311/321, not a database per client.
Rounding, reverse charge and dobropis have fixtures under
`state/fixtures/isdoc-realworld/`.

Vision Pulse writes `pending-invoice-verify`. HMAC `invoice-verify` and Face
Books approve; they do not insert invoice rows. `absorb-approved` is the
scheduled booker. Join key is `sidecar_id`, not slug.

Dolibarr is the desk, on the shared infra MariaDB, and its native OIDC is
live — the authorize button lands an Authentik session. Party remains SoT: the
hydrator reads Dolibarr's schema into KEAP `party` through the digest gate,
and agents read tables, never vendor REST.

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

## One document, one row, one ledger

Found by reading the live Books table rather than by a test: document
2026-BETA-002 stood **twice**, and one level down the book carried sixteen
journal entries for ten invoices — the fixture seeded a ledger while an import
of the same documents derived its own. Both halves balanced, which is exactly
why nothing caught it: two copies of a correct document are individually
correct, and a balance check cannot see duplication.

`invoice_slug(book_owner, seller, document_number)` is now THE derivation, and
absorb refuses any invoice whose slug is not it — so no producer can mint its
own id. The live rows were rebuilt to the derived spelling; the scanner reads
clean.

## What this cut refuses to claim

**photo→booked IS proven live** — a photographed invoice reached the verify
queue, was approved against its rendered source, and absorbed into a balanced
journal entry, twice. What is NOT proven is the same path **from a blank**:
UC13 is unrun, and it is named here rather than implied by the green.

Client portal pages are not an owner-scoped document desk. UC10 (fraud
crosscheck) is blocked. REM-249 stays operator-gated. n8n does not drive
invoices. A second manager can still read every `book_owner` — there is no
row-level client assignment. Live KEAP delete on offboard is not proven, and
embeddings versus Art-17 is unsolved.

GitHub Integration on `master` is not claimed green, and the signed-commit
ruleset is bypassed rather than met. `RELEASE.md` carries the same named red.
