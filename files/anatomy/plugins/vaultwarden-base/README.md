# vaultwarden-base — service plugin (DRAFT) + mkcert conditional fix

> **Status:** research draft, 2026-05-03 evening. **NOT loaded by anything.**
> Fourth tune-and-thin pilot per `docs/active-work.md`. **First pilot with
> `data_subjects: end_users`** — proves the GDPR Article 30 register
> contract holds for services that legitimately process third-party
> personal data, not just operator infrastructure metadata.

## What landed LIVE alongside this draft

Same regression class as Open WebUI (2026-05-03 morning) and Grafana (this
batch): unconditional mkcert root CA mount + entrypoint cert-store rebuild
breaks Authentik LE cert validation on a public TLD.

`roles/pazny.vaultwarden/templates/compose.yml.j2` now gates the mount,
the custom entrypoint, AND the `extra_hosts authentik:host-gateway` alias
on `tenant_domain_is_local`:

| Surface | Before | After |
|---|---|---|
| `mkcert-ca.crt` volume mount | always (when `install_authentik`) | only when `tenant_domain_is_local` |
| `update-ca-certificates` entrypoint wrapper | always (when `install_authentik`) | only when `tenant_domain_is_local` |
| `extra_hosts authentik:host-gateway` | always (when `install_authentik`) | only when `tenant_domain_is_local` |

On a public TLD (LE certs):
- No mkcert CA shadowing → Authentik OIDC handshake validates cleanly
- No entrypoint cert-store rebuild → faster startup, fewer moving parts
- No host-gateway alias → real DNS resolves Authentik, no Docker Desktop
  weirdness

## The end_users / contract / forever GDPR shape

This is the FIRST plugin draft where the GDPR row diverges sharply from
the operator-only services (Portainer, Grafana, Qdrant, Woodpecker):

| Block | Value | Reason |
|---|---|---|
| `legal_basis` | `contract` | Operator hosts vault FOR family / team — service contract relationship |
| `data_subjects` | `[operators, end_users]` | First time `end_users` appears |
| `retention_days` | `-1` (forever) | Vault IS permanent storage; -1 is the documented sentinel |
| `transfers_outside_eu` | `false` | All-local Vaultwarden, no Bitwarden cloud sync |
| `breach_severity_default` | `critical` | Vault breach = worst case; auto-tag any incident at max severity |
| `dsar_endpoint` | `wing-cli vault-erase --user $DSAR_USER_EMAIL` | First plugin with a real DSAR endpoint (post-A8 conductor wires this; today it's a manual curl) |

The `apps_runner` parser already enforces TLS-from-data gates when
`data_subjects` includes `end_users`, so a misconfigured Vaultwarden
deploy WITHOUT TLS termination would refuse to render.

## Notable design choices

- **`lifecycle.post_blank.conditional_remove_dir`** — the role's
  `tasks/main.yml` does NOT carry blank-reset cleanup today, on purpose.
  This plugin formalizes the contract: blank does NOT destroy the vault
  by default; operator opts in via `vaultwarden_blank_destroys_vault: true`.
  Loses-everything-once-on-mistake protection.
- **`observability.alerts.vaultwarden_admin_token_in_logs`** — class-
  level guard against the `ADMIN_TOKEN=...` ever appearing in container
  logs. Loki query alerts at `severity: critical` if a future
  refactor accidentally enables verbose env-dump.
- **`tier: 3` (user)** — Vaultwarden is END-user UI, unlike Portainer
  / Qdrant / Grafana (admin tier). `nos-users` group + above can reach
  the login form; the vault itself is gated by master password (which
  Authentik can NOT replace — this is a key Bitwarden security property).
- **Wing /hub card uses `icon: lock`** — visual cue that this card
  links to a credentials store (different visual class from infra UI).

## Two-blank gotcha

None for Vaultwarden — no API-driven post-setup, no plist env to
re-render. SSO works on first blank if Authentik is up; if Authentik
isn't ready when Vaultwarden boots, the SSO login button just fails
gracefully and master-password login still works.

## Reading order for the next agent

1. `roles/pazny.vaultwarden/templates/compose.yml.j2` — see the live
   mkcert conditional pattern (mirrors Open WebUI + Grafana).
2. This `plugin.yml` — see the `gdpr:` block as the canonical shape for
   any future end-user-facing service (Nextcloud, Outline, Open WebUI's
   user-content storage, etc. all need similar shape).
3. `files/anatomy/plugins/qdrant-base/plugin.yml` — sibling pilot with
   `data_subjects: operators` for contrast.
