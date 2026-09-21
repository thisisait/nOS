# Dolibarr — Skills

> **No HTTP skill surface for agents.** Dolibarr is the human CRM desk; the
> machine-readable projection of its master data is the KEAP party spine
> (`docs/doctrine/backoffice.md`). What exists is one CLI, run by Pulse or the
> operator, never an agent hitting Dolibarr REST.

## Hydrate the party spine from the desk

```bash
tools/digest-import-doli.py                    # docker fetch, gate, print (dry)
tools/digest-import-doli.py --absorb           # upsert (skip slugs already present)
tools/digest-import-doli.py --from-json f.json # tests / no docker
```

- Projects open thirdparties (IČO required) through the digest gate into
  `party` / `party-tax-identity`. Reads the MariaDB schema read-only.
- Exit 0 done/dry/idle (no desk) · 1 gate refused · 2 desk present but
  unreadable — an exit code, never a prose claim.

## What deliberately does not exist

- No Dolibarr REST token for agents, no webhook consumer, no write-back from
  KEAP to Dolibarr. A divergence between desk and spine is resolved by
  re-running the hydrator, not by teaching an agent the vendor API.
