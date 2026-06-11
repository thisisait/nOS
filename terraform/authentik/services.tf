# ── nOS services — hand-authored Authentik wiring (ADR-0001 §9) ──────────────
# Phase 0 spike: two services covering BOTH modes. Phase 1 adopts the rest via
# `import` (one module call per service). VALUES come from var.* (tfvars.json,
# playbook-rendered); STRUCTURE is here. No Jinja in HCL.

locals {
  _scopes = [
    data.authentik_property_mapping_provider_scope.openid.id,
    data.authentik_property_mapping_provider_scope.email.id,
    data.authentik_property_mapping_provider_scope.profile.id,
  ]
}

# forward_auth → proxy provider (the incident service). NEVER an oauth2 provider.
module "infisical" {
  source = "../../modules/nos-authentik-app"
  mode          = "forward_auth"
  slug          = "infisical"
  name          = "Infisical"
  external_host = var.infisical_url

  authorization_flow_id  = data.authentik_flow.authorization.id
  authentication_flow_id = data.authentik_flow.authentication.id
  invalidation_flow_id   = data.authentik_flow.invalidation.id
  outpost_id             = data.authentik_outpost.embedded.id
  signing_key_id         = data.authentik_certificate_key_pair.signing.id
  scope_mapping_ids      = local._scopes
}

# native_oidc → oauth2 provider (auto-redirect login).
module "grafana" {
  source = "../../modules/nos-authentik-app"
  mode          = "native_oidc"
  slug          = "grafana"
  name          = "Grafana"
  external_host = var.grafana_url
  client_id     = "nos-grafana"
  client_secret = var.grafana_oidc_client_secret
  redirect_uris = ["${var.grafana_url}/login/generic_oauth"]

  authorization_flow_id  = data.authentik_flow.authorization.id
  authentication_flow_id = data.authentik_flow.authentication.id
  invalidation_flow_id   = data.authentik_flow.invalidation.id
  outpost_id             = data.authentik_outpost.embedded.id
  signing_key_id         = data.authentik_certificate_key_pair.signing.id
  scope_mapping_ids      = local._scopes
}
