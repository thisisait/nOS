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
It is the default **practice pack** inside backoffice — Dolibarr + KEAP
tables + invoice doors. EspoCRM is retired (`apps/espocrm.yml.draft`).
A florist or a workshop later gets a different pack; they still live
under backoffice.

That is meaning **public organ** in [`organs.md`](organs.md) §1. It is
not Bone · Wing · Pulse · Cortex, and not a new launchd unit.

| piece | owns | is not |
|---|---|---|
| KEAP DataTables (`party`, `invoice`, `journal-entry`, `posting`, `pending-invoice-verify`) | booked facts (fallback SoT when Dolibarr is off) | a CRM |
| Dolibarr | the relationship desk (CRM SoT when `install_dolibarr`) | a second party table |
| Face Books | a projection + HMAC approve | the SoT |
| Digest | intake (raw → gate → absorb) | the books |
| Voice (mail, ntfy, …) | signals | the customer desk |
| Commons | the user portal | the backoffice |

FreeScout is the customer desk in backoffice. Mail stays in `voice`.
Digest does not book its own invoices.

## 2. Core for every tenant; praxis is the first pack

Every firm that hosts nOS needs a backoffice. The consulting-firm pilot
is the first **praxis** pack, not a plugin other tenants leave off.

**Default blank (settled 2026-09-21):** praxis on (Dolibarr flag in
`profiles/praxis.yml`; committed default `install_dolibarr: false`);
Firefly and ERPNext off. KEAP tables stay the books fallback.

## 3. One SoT, many projections

- **Booked rows** go through Digest absorb. Face Books and HMAC
  `invoice-verify` resolve `pending-invoice-verify`; they do not insert
  `invoice` / `posting` behind absorb.
- **Dolibarr** is the CRM desk when installed. Agents must not hardcode
  Dolibarr URLs; they read `party` / `invoice` via tables MCP (or future
  `get db:`). The hydrator organelle is `crm-hydrate-base` +
  `digest-import-doli` (MariaDB `llx_societe` → digest absorb), not Bone
  and not vendor REST. Join marker `nos:doli:<rowid>` in `party.notes`.
  Do not fork `party`.
- **KEAP explore** may embed party row objects (`graph.mode: rows` on
  `party.table.yml`, then keap-embed-sync). Opt-out the iframe with
  `face_keap_explore_url: ""`. Cortex / nos-lang / Digest / Bone / Pulse
  consume tables and events, not Dolibarr REST.
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
| `digest-import-doli` (Pulse `crm-hydrate:hydrate-parties`) | open thirdparties with IČO | KEAP `party` projection |
| n8n ČNB / DTT | after approve | export, never a second SoT |

A release that ships Books without absorb, or Dolibarr as a second
party table without the hydrator organelle, or vision that writes `invoice`
directly, is not praxis and not backoffice.

## 4b. Organelles (what Espo/Firefly never grew)

The desk container is replaceable FOSS. The pack is the tendons:

| organelle | organ | artifact |
|---|---|---|
| hydrator | Digest + Pulse | `crm-hydrate-base`, `tools/digest-import-doli.py`, `imp_doli-party` |
| party spine | Cortex / KEAP | `state/keap-tables/party.table.yml` (`graph.mode: rows`) |
| agent procedure | nos-lang / skills | `files/anatomy/skills/nos-backoffice/SKILL.md` |
| HMAC events | Bone | digest absorb already posts through the KEAP agent door |
| books intake | Digest + Pulse + Bone | ISDOC / vision queue / HMAC `invoice-verify` — already an organelle |

Dolibarr `Facture` and Firefly are **desks**, not a second invoice spine.
A hydrator that copies `llx_facture` (or Firefly journals) into `invoice` /
`posting` would fork the books the way Espo forked `party`. Withhold it.
Bone does not grow a CRM client. A hydrator that PATCHes existing slugs is
a digest-constitution change, not a Dolibarr feature.

## 5. Settled (operator 2026-09-20)

1. Public organ = **backoffice**; **praxis** = pack. Apex key moved
   from `ledger` (re-signed). Promote this file when ssot harvest next
   recites doctrine.
2. Firefly and ERPNext off on a blank. Dolibarr off in committed
   defaults; praxis overlay turns it on.
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
