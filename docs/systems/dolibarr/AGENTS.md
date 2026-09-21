# Dolibarr — Agent Definition

## DolibarrAgent

**System:** Dolibarr ERP/CRM (Docker, `b2b` stack; container `b2b-dolibarr-1`)
**Endpoint:** none for agents — see Constraints
**Role:** There is deliberately no acting agent for Dolibarr. It is the
operator's CRM desk; the estate's readable truth about parties and invoices
lives in the KEAP DataTables the digest spine fills.

### Context

- UI: `https://doli.{tenant_domain}` behind Authentik forward-auth — a human
  surface, not an API for agents.
- Master data flows ONE way: Dolibarr MariaDB → `tools/digest-import-doli.py`
  (digest gate) → KEAP `party` / `party-tax-identity`. The importer reads the
  DB schema read-only and never calls Dolibarr REST.
- Registry status for its thirdparties (`party-registry-status`) is filled by
  the n8n ARES pack, keyed on the party spine — not by anything Dolibarr-side.

### Constraints

- **Agents read KEAP tables, never vendor REST** (`docs/doctrine/backoffice.md`).
  A task that seems to need the Dolibarr API is a task for the hydrator or for
  the operator at the desk.
- No agent credential exists for Dolibarr, by design; do not mint one.
- Writes to Dolibarr are the operator's (UI) or the playbook's (provisioning).

### Skills Reference

See [SKILLS.md](SKILLS.md) — the skill surface is the hydrator CLI, not HTTP.
