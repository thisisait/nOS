# Backoffice — the firm's desk, not a fifth brain

> **PROPOSED, not settled** only for promote-to-ssot. The names are
> settled: **backoffice** is the public organ; **praxis** is a pack
> inside it, not a second organ and not a host daemon. Sibling of
> [`organs.md`](organs.md) and of Digest (the stomach: intake).

## 1. Two names, one daemon refusal

Apex publishes **The Backoffice** — *"CRM, books and a customer desk, at home."*
(`organs.backoffice`). CRM, invoices, double-entry, a customer desk,
optional heavier books and analytics.

**Praxis** is not a 14th constellation and not `files/anatomy/praxis/`.
It is the default **practice pack** inside backoffice — Espo + KEAP
tables + invoice doors. A florist or a workshop later gets a different
pack; they still live under backoffice.

That is meaning **public organ** in [`organs.md`](organs.md) §1. It is
not Bone · Wing · Pulse · Cortex, and not a new launchd unit.

| piece | owns | is not |
|---|---|---|
| KEAP DataTables (`party`, `invoice`, `journal-entry`, `posting`, `pending-invoice-verify`) | the booked facts | a CRM |
| EspoCRM | the relationship desk | a second party store |
| Face Books | a projection + HMAC approve | the SoT |
| Digest | intake (raw → gate → absorb) | the books |
| Voice (mail, ntfy, …) | signals | the customer desk |
| Commons | the user portal | the backoffice |

FreeScout is the customer desk in backoffice. Mail stays in `voice`.
Digest does not book its own invoices.

## 2. Core for every tenant; praxis is the first pack

Every firm that hosts nOS needs a backoffice. The consulting-firm pilot
is the first **praxis** pack, not a plugin other tenants leave off.

**Default blank (settled 2026-09-20):** praxis on (Espo + KEAP tables);
Firefly and ERPNext off. Heavier books are opt-in packs, still under
backoffice.

## 3. One SoT, many projections

- **Booked rows** go through Digest absorb. Face Books and HMAC
  `invoice-verify` resolve `pending-invoice-verify`; they do not insert
  `invoice` / `posting` behind absorb.
- **Espo** carries `nos:party:<slug>` in `Account.description`. Do not
  fork `party`.
- **Vision** extracts; an operator or HMAC CLI verifies. A model does
  not book.
- **Model C**: isolation is analytical 311/321 and `book_owner`, not a
  database per client.
- Apex **withholds** `table:invoice`, `table:party`, `table:posting`, …
  A client's books are not the public front door. Atoms are
  capabilities, not rows.

## 4. Doors (praxis pack)

| door | in | out |
|---|---|---|
| ISDOC importer | e-invoice | gated bundle → absorb |
| invoice-vision Pulse | photo/PDF | `pending-invoice-verify` |
| HMAC `invoice-verify` / Books approve | held row | absorb books it |
| `espo-party-sync` | `party` rows | Espo Account join tag |
| n8n ČNB / DTT | after approve | export, never a second SoT |

A release that ships Books without absorb, or Espo without the join tag,
or vision that writes `invoice` directly, is not praxis and not
backoffice.

## 5. Settled (operator 2026-09-20)

1. Public organ = **backoffice**; **praxis** = pack. Apex key moved
   from `ledger` (re-signed). Promote this file when ssot harvest next
   recites doctrine.
2. Firefly and ERPNext off on a blank.
3. Client/user portal lives in **commons**. WordPress is that portal
   when the firm wants a CMS, not a second backoffice.
4. **Config builder:** none in this tree. YAML `profiles/*`, queued
   `face-app-builder` (apps, not `install_*`), `docs/overview.html`.
   A first-onboard chooser that emits `config.yml` is new work beside
   commons, not a 15th organ.
5. **Client-data training:** optional, default OUT, per `book_owner`
   (`party.training_opt_in`), withdrawable. Pipeline off until
   offboarding can honour Art-17 against a model. Art-7 capture is
   still unwired (`gdpr-consent-map.yml` `capture_wired: false`).
   No LoRA, no hosted trainer.
