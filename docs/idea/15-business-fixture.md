# 15 — A real business on nOS

**Status: increment 1 SHIPPED 2026-08-14 (structure + synthetic seed, commit
`8165de48`); proposed 2026-08-09, targeted 2026-08-15 (`w-fixture`).**
**Detail:** the roadmap row carries the schedule; this file carries the argument.

## What shipped, and what "unblocked" turned out to license (2026-08-14)

Nine git-owned DataTables (`state/keap-tables/{party,party-tax-identity,
party-address,party-contact,print-machine,print-material,print-order,
print-job,print-job-step}.table.yml`), a deterministic synthetic seed
(`state/fixtures/label-printer.seed.yml`), an idempotent converge seeder
(`roles/pazny.keap/tasks/seed-fixture-tables.yml`, opt-in via
`keap_seed_business_fixture`, default false), and the offline referee
(`tests/anatomy/test_fixture_tables_declare_the_business.py`).

**"Unblocked" re-derived, because the two register entries are different
registers of different things.** The 2026-08-13 Article-30 work (88 records)
declares the AGENT ceremonies' processors. The rule below needs an entry for
the FIXTURE's processing of customer data plus the company's written yes —
neither exists, and pre-declaring one would assert processing that does not
occur (the same wrongness the empty list had, pointing the other way — the
minimax lesson). So what is licensed today is exactly what shipped: real
structure, synthetic people, with the synthetic-ness ENFORCED by gate
(`.invalid` mail, `+420 000` phones, unissued tax-id ranges, `synthetic-`
slugs) rather than by convention.

**Drift found while building, so the next reader does not rediscover it:**

- A live table `Business partners` (seeded 2026-07-29 as "cortex test data")
  exists on the estate and in NO git file — it is the flat pre-`rowRef` shape
  (billing/delivery as text columns on the partner row) that
  `docs/archive/datatables-relations.md` §5 argues against. The party set
  supersedes it; nothing reads it; **its retirement is an operator decision**
  (its four rows are disposable TEST data by its own description).
- The relations doc's spelling `onRefDelete` predates the implementation:
  KEAP ships `onDelete` (+ `refDisplay`), verified against
  `~/keap/src/shared/contracts/table.ts` and `row-refs.test.ts`.
- KEAP's agent row-upsert treats a row's `slug` as its row id, so seed rowRef
  values are literal target slugs and a re-seed PATCHes instead of
  duplicating — this is what makes proof 3 attemptable.

**Still ahead:** the converge that creates the tenant (proof 3 measured, not
argued), the cortex chain over `print-job-step` (the machine-stop question),
the loop question (proof 1), and — only after the register entry and the
written yes — real people.

## The idea

Host one actual company on this estate and run the whole spine against a kind of
data nOS has never held.

Everything in the corpus today is **documentary** — taxonomy nodes, captured
pages, notes, a self-model. Firefly holds money. Neither is *work in progress*.
The estate has never been asked a question whose answer changes at 14:00 because
a machine finished a job.

## Why a fixture rather than a demo

A demo is data we write to make the system look answerable. A fixture is data
someone else's week depends on, which is the only kind that argues back. The
distinction matters because every claim we have made about relations, about the
cortex, and about the loop has been measured against a corpus **we authored**.

`docs/idea/03` already names this failure honestly: parity is measured nightly
and the referee itself prints `realUserDocs: 70` against a floor of 25 — the
corpus is thin *by input*, not by design. A business fixture is the input.

## Which business, and why the obvious two lose

**Recommended: a label printer.**

Its core object is a **job** — a deadline, a material, a quantity, a machine, and
a physical outcome. That is the shape nOS has no example of. It is also small
enough to be honest: a print shop with forty open orders *is* a print shop, so
the fixture never becomes a synthetic-data generator pretending to be a business.

**Call centre — the wrong first bet, and not for a soft reason.** It rides
FreePBX, which is the estate's single vendor-blocked CRITICAL: the tiredofit
image was abandoned upstream on 2022-04-30 and REM-014/046/113 are recorded as
**unfixable**, accepted risk, `install_freepbx: false` by default. Building the
first real business on the one service we cannot patch inverts the point. Its
data shape also needs *volume* to mean anything, and a call centre without
volume is a toy.

**E-shop — the fallback, and it would exercise `rowRef` hardest.** Held back
only because it is the most solved shape in the world: every framework ships an
e-shop demo, so it tests our tables less and our thinking not at all.

## What it exercises, listed so the fixture can fail visibly

| surface | what a print shop asks of it |
|---|---|
| `rowRef` (KEAP, shipped 2026-08-09, never run live) | order → customer, job → order, job → material. N:N on job ↔ machine. |
| EN 16931 party/tax/address tables | a real VAT id, a real delivery address that differs from the billing one |
| the parser's mandatory `gdpr:` block | a customer list is personal data; there is no fixture exemption |
| cortex over transactional data | "which jobs miss their deadline if machine 2 stops" is not a document lookup |
| the loop | a question whose right answer changed since the last time it was asked |

## The one rule this fixture ships with

**Real structure, synthetic people — until an Article 30 register entry exists.**

A real company's customers are not a test fixture. The estate already enforces
this at the deploy gate (`nos_app_parser` refuses a manifest without purpose,
legal basis, categories, subjects, retention, processors and the EU-residency
flag) and the enforcement is not waivable for our own convenience. Model the
real business; populate it with people who do not exist, until the register says
otherwise and the company has said yes in writing.

The order matters and it is cheap to get right: the register entry is a form,
and it takes an afternoon. Loading real customers first and documenting later is
the sequence that cannot be undone.

## What would prove it worked

Not "the tables render". Three things, in order of how much they would tell us:

1. **A question the operator did not pre-plan gets a correct answer** through the
   validated-chain path, over job data, without anybody writing a query.
2. **A relation we shipped turns out to be wrong for real work** — the fixture
   earning its keep by disagreeing with the design.
3. **A converge does not lose it.** The fixture survives `nos --remove=data`
   → reinstall as a documented, reproducible tenant, or the estate cannot host a
   business at all, only demonstrate one.

The third is the real gate, and it is the one most likely to fail.
