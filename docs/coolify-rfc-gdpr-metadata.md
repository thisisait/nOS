# RFC: GDPR Article 30 metadata keys for Coolify service templates

**Status:** draft, not yet submitted upstream
**Affects:** [coollabsio/coolify](https://github.com/coollabsio/coolify) — `templates/compose/*.yaml`
**Author:** nOS / This is AIT (operator-driven; we maintain a sister
catalog at <https://github.com/pazny/nOS> using these keys)
**License:** the proposal is CC0 — feel free to adopt verbatim

---

## Motivation

Self-hosting communities increasingly include EU operators (or
operators with EU customers) for whom **GDPR Article 30** is a hard
legal requirement, not a checkbox. Article 30 obliges every controller
to maintain a written register of processing activities — purpose,
legal basis, categories of personal data, retention horizon, third-
party processors, EU/EEA transfer status, security measures.

Today this work is done **per app, per operator**, often by reading
upstream docs and guessing. The Coolify template catalog already
encodes header metadata (`# documentation`, `# slogan`, `# category`,
`# port`, `# tags`, `# logo`) so the Coolify UI can render the
service-picker. Adding a small set of `# gdpr_*` keys lets operators
inherit a sane DEFAULT for the Article 30 register, which they can
then edit per their own legal interpretation.

This is a **purely additive** change. Non-EU operators who don't care
ignore the keys. The Coolify UI doesn't have to surface them — they're
just metadata.

---

## Proposal

Extend the header convention with the following keys (all optional —
but if a template ships any one of them, it should ship all the
`gdpr_required_*` keys):

```yaml
# documentation: https://example.com/docs
# slogan: One-line description (existing)
# category: productivity (existing)
# port: 3000 (existing)
#
# # GDPR Article 30 — applies when self-hosted in the EU/EEA. Edit per
# # your own legal interpretation; these are upstream-suggested defaults.
# gdpr_purpose: |
#   Two-or-three sentences explaining why the operator processes data
#   when running this app. Plain language. Should make sense to a DPO
#   reading without context.
# gdpr_legal_basis_suggested: legitimate_interests
# # Allowed enum: consent | contract | legal_obligation
# #             | vital_interests | public_task | legitimate_interests
# gdpr_data_categories_typical: [email, ip_address, behavioural_data]
# gdpr_data_subjects_typical: [end_users]
# gdpr_retention_days_default: 365
# gdpr_processors_default: []
# gdpr_transfers_outside_eu: false
# # If true, the upstream image OR the documented "common" deployment
# # routes data outside the EEA — operators must override this manually
# # if they self-host on EU-only infra.
```

Implementation surface:

1. **Template catalog**: maintainers add the keys to whichever
   templates they're confident about. Empty / missing keys are fine —
   that's the `nullable` semantic.
2. **Coolify UI** (optional, follow-up): when `gdpr_*` keys are
   present, render a collapsible "Article 30" panel in the service
   detail view. No code changes needed for v1; the keys are just text.
3. **No runtime behaviour changes.** Coolify continues to deploy the
   compose template exactly as it does today. The keys are inert
   unless a downstream tool reads them.

---

## What this enables downstream

Tools like nOS's `tools/import-coolify-template.py` (Apache-2.0,
public) can pre-fill the importer's `gdpr:` block with the upstream
suggestions, instead of leaving every key as a `TODO`. Operators
still review and edit — but the cognitive load drops by 60-80% for
common apps where the legal basis is well-understood (e.g. a wiki for
team use → `legitimate_interests`; an e-signature tool → `contract`;
analytics → `consent`).

Other downstream tools (Cloudron, Yacht, Dokploy, Easypanel, Cosmos,
PikaPods) could adopt the same keys without coordination — the
metadata is the contract, not the implementation.

---

## What this is NOT

- **Not legal advice.** Suggested values are starting points, not
  binding statements about the operator's actual processing.
- **Not a replacement** for an operator's own Article 30 register —
  see Recital 13 + Article 30(5) for SME exemptions.
- **Not opinionated** about EU residency: `gdpr_transfers_outside_eu`
  reflects upstream's typical deployment, not the operator's actual
  infra.
- **Not a behaviour change.** Coolify can ignore these keys forever
  and nothing breaks.

---

## Open questions for upstream review

1. Should the keys live in the YAML header (current convention,
   comment-prefixed) or in a sibling `metadata:` block at the top of
   the compose YAML? The current header is text-comment-only and
   parsed string-by-string; a structured `metadata:` block would let
   Coolify use a YAML loader on it. The header path is closer to the
   existing convention; the metadata block is closer to e.g. Helm
   chart metadata.
2. Should `gdpr_legal_basis_suggested` be enum-bound or free-form?
   nOS's parser enforces the enum; upstream might prefer free-form
   to avoid arguing about edge cases.
3. Should there be a `gdpr_dsar_endpoint_typical` key encoding what
   path / shell hook the app provides for user-erasure? Most apps
   don't have one; this would be `null` everywhere.

---

## Reference implementation

nOS uses this proposal in its OWN manifest format
(`apps/<name>.yml`, schema at `state/schema/app.schema.json`). The
keys map cleanly:

| Upstream key (proposed)              | nOS field                           |
| ------------------------------------ | ----------------------------------- |
| `gdpr_purpose`                       | `gdpr.purpose`                      |
| `gdpr_legal_basis_suggested`         | `gdpr.legal_basis`                  |
| `gdpr_data_categories_typical`       | `gdpr.data_categories`              |
| `gdpr_data_subjects_typical`         | `gdpr.data_subjects`                |
| `gdpr_retention_days_default`        | `gdpr.retention_days`               |
| `gdpr_processors_default`            | `gdpr.processors`                   |
| `gdpr_transfers_outside_eu`          | `gdpr.transfers_outside_eu`         |

`tools/import-coolify-template.py` will be updated to read these
keys when present and pre-fill the draft instead of writing `TODO`.
