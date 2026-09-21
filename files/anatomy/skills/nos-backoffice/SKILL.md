---
name: nos-backoffice
description: Backoffice pack — CRM desk is Dolibarr when installed; agents read KEAP party/invoice tables, never vendor REST. Hydrator is digest-import-doli, not Bone.
metadata:
  nos:
    audience: [hermes, openclaw]
    platforms: [macos, linux]
    requires: [python3]
prerequisites:
  commands: [python3]
---

# nos-backoffice — one SoT, replaceable desk

The consulting-firm pack lives under the **backoffice** organ. Dolibarr is a
replaceable FOSS desk. nOS value is the hydrator + tables + skills, not the
container.

## The one rule

**Read counterparties and booked invoices through KEAP DataTables**
(`nos-datatables` / `nos_tables` / `tools/cortex-query.py` for knowledge).
Do not curl Dolibarr, Espo, or Firefly. Do not invent a second party table.

| surface | owns | door |
|---|---|---|
| Dolibarr | CRM desk (when `install_dolibarr`) | humans in the browser, Authentik gate |
| `party` / `invoice` / `posting` | governed facts | digest absorb |
| `digest-import-doli.py` | hydrator organelle | Pulse `crm-hydrate:hydrate-parties` |
| Face Books | projection + HMAC verify | not a store |
| KEAP explore | optional embed of party rows (`graph.mode: rows` on the table; hide iframe via `face_keap_explore_url: ""`) | not a second SoT |

## When NOT to use

- To book an invoice: that is HMAC `invoice-verify` / Books approve, then
  digest absorb — never a model, never Dolibarr REST, never a copy of
  `llx_facture` or Firefly into `invoice` / `posting`.
- To dual-write Espo-style (`espo-party-sync`). That path is retired.
- To treat Bone as a CRM client. Bone carries HMAC events; it does not hydrate.
- When the question is taxonomy/SKILLS.md recall — that is `cortex-query`.

## Hydrator

```
python3 tools/digest-import-doli.py              # dry, idle 0 if no desk
python3 tools/digest-import-doli.py --absorb     # Pulse does this
python3 tools/digest-import-doli.py --from-json tests/fixtures/doli-party.json
```

Join marker `nos:doli:<rowid>` sits in `party.notes`. Rows without a valid IČO
are skipped. Absorb skips slugs already present.

## Never

- Never print Dolibarr admin passwords or API keys.
- Never POST to `/api/index.php/` from an agent session.
- Never write `verified` on a roadmap row from this skill.
