# Ledger — the firm's books, not a fifth brain

> **PROPOSED, not settled.** Warehouse slug stays `ledger.md` until the
> public organ is renamed. Sibling of [`organs.md`](organs.md) and of
> Digest (the stomach: intake). Promote to `ssot/doctrine/` only after
> the name in §5.1 is picked — not before.

## 1. The organ already exists — do not mint a daemon

Apex already publishes **The Ledger**: *"Business runs on its own books."*
(`files/anatomy/apex/ruling.yml` `organs.ledger`). Today that group holds
ERPNext, FreeScout, Firefly, Metabase, Superset.

That is meaning **public organ** in [`organs.md`](organs.md) §1 — a purpose
grouping shown to strangers. It is **not** meaning 1 (Bone · Wing · Pulse ·
Cortex host daemons) and **not** a new `files/anatomy/ledger/` launchd
unit with an exclusive sqlite.

| piece | owns | is not |
|---|---|---|
| KEAP DataTables (`party`, `invoice`, `journal-entry`, `posting`, `pending-invoice-verify`) | the booked facts | a CRM |
| EspoCRM | the relationship desk | a second party store |
| Face Books | a projection + HMAC approve | the SoT |
| Digest | intake (raw → gate → absorb) | the books |
| Voice (mail, ntfy, …) | signals | the customer desk |

FreeScout stays in `ledger` (one customer desk). Mail stays in `voice`.
Do not merge Digest into Ledger: a stomach that books its own invoices is
the self-reporting defect.

## 2. This is core, not a consulting addon

Every firm that hosts nOS needs, at minimum: a CRM surface, invoices,
double-entry books, and a communication desk. The consulting-firm pilot
is the **first fixture** of that core, not a plugin that other tenants
leave off.

A tenant may disable ERPNext or Firefly and still have KEAP books + Espo.
They may not disable the SoT tables and call the estate "a firm OS".
**Default blank (settled 2026-09-20):** Espo + KEAP tables on; Firefly and
ERPNext stay off. Heavier books are opt-in, not the core.

## 3. One SoT, many projections

- **Write of booked rows** goes through Digest absorb (or a gate that is
  the same chokepoint). Face Books and `invoice-verify` HMAC upsert may
  resolve `pending-invoice-verify`; they do not insert `invoice` /
  `posting` behind absorb.
- **Espo** carries `nos:party:<slug>` in `Account.description`. Contact
  and Lead stay Espo's. Do not fork `party`.
- **Vision** extracts; the operator (or HMAC CLI) verifies. A model does
  not book.
- **Model C**: client isolation is analytical 311/321 (and `book_owner`
  on the invoice), not a database per client.
- Apex **withholds** `table:invoice`, `table:party`, `table:posting`, …
  on purpose: a client's books are not the public front door. Published
  atoms are capabilities, not rows. Firefly/ERPNext stay unpublished as
  defaults-off; FreeScout remains the customer desk in this organ until
  a rename.

## 4. Doors (the wiring that must stay honest)

| door | in | out |
|---|---|---|
| ISDOC importer | e-invoice | gated bundle → absorb |
| invoice-vision Pulse | photo/PDF | `pending-invoice-verify` |
| HMAC `invoice-verify` / Books approve | held row | absorb books it |
| `espo-party-sync` | `party` rows | Espo Account join tag |
| n8n ČNB / DTT | after approve | export, never a second SoT |

A release that ships Books without absorb, or Espo without the join tag,
or vision that writes `invoice` directly, is not this organ.

## 5. Name, defaults, commons (operator 2026-09-20)

1. **Name — still open.** `ledger` collides with every accounting product
   and with Firefly's own vocabulary. Apex key stays `ledger` until a
   rename; working candidates (pick one, then rename apex + this file):
   - **folio** — the bound account-book; unused in apex
   - **comptoir** — the merchant's counting desk
   - **praxis** — the consulting practice, not the books alone
   Not a fifth host daemon under any of those names.
2. **Settled:** Firefly and ERPNext off on a blank. Espo + KEAP tables
   are the core books/CRM.
3. **Settled:** the client/user portal lives in **commons** (universal
   base; a deployment fills it with what that firm needs). WordPress is
   that portal when the firm wants a CMS, not a second ledger.
4. **Config builder:** there is no clickable `config.yml` generator in
   this tree. Closest surfaces: `profiles/{all-on,gov-local,dev-minimal}.yml`
   (YAML, not a wizard); queued DTT `face-app-builder` (tenant apps, not
   `install_*` flags); `docs/overview.html` (map, not a picker). A
   first-onboard static chooser that emits `config.yml` is new work —
   it belongs next to commons, not inside this organ.
