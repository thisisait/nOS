# Dolibarr

> ERP/CRM desk for the praxis/consulting pack. Thirdparties, customer/supplier invoices, proposals — the operator-facing CRM surface whose master data the digest spine projects into KEAP.

## Quick Reference

| | |
|---|---|
| **URL** | `https://doli{host_alias_seg}.{tenant_domain}` (default `https://doli.dev.local`) |
| **Port** | `3016` (`dolibarr_port`; loopback publish → container `80`) |
| **Stack** | `b2b` |
| **Toggle** | `install_dolibarr: false` (default OFF; the praxis pack turns it ON) |
| **Compose** | `~/stacks/b2b/docker-compose.yml` (role fragment: `~/stacks/b2b/overrides/dolibarr.yml`) |
| **Image** | `dolibarr/dolibarr:21.0.4` (`dolibarr_version`) |
| **DB** | MariaDB `dolibarr` / user `dolibarr` (infra stack; `dolibarr_db_host: 127.0.0.1`) |
| **Data** | `dolibarr_data_dir` under `{{ nos_data_root }}/platform/services/dolibarr` |

## Authentication

`forward_auth` — the Traefik route is Authentik-gated; Dolibarr keeps its own
login behind the gate until the OIDC module is proven in `post.yml`
(`files/anatomy/plugins/dolibarr-base/plugin.yml` header comment is the
authority). Not `native_oidc` yet; do not stack a second gate when it flips.

## Position in the estate

Dolibarr is the CRM **desk** when installed — the KEAP DataTables stay the
spine (`docs/doctrine/backoffice.md`):

- **Hydration**: `tools/digest-import-doli.py` projects open thirdparties
  (IČO required) through the digest gate into `party` / `party-tax-identity`.
  It reads the MariaDB schema directly — never Dolibarr REST. Dry by default;
  `--absorb` writes. Bone is not a hydrator.
- **Agents read KEAP tables, never the vendor API** — the desk is for humans.
- **Books fallback**: with `install_dolibarr: false` the KEAP tables carry the
  books alone; nothing else changes shape.

## Operations

- Converge: `ansible-playbook main.yml --tags dolibarr` (A17 auto-fires the
  compose recreate).
- Health: manifest `health_check` GETs `http://localhost:3016/`.
- ARES enrichment of its thirdparties rides the n8n ARES pack →
  `party-registry-status` (`docs/doctrine/n8n-packs.md`), not a Dolibarr
  module.
