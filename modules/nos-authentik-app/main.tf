# nos-authentik-app — the one wiring shape every nOS service shares.
# native_oidc -> oauth2 provider; forward_auth/header_oidc -> proxy provider +
# outpost attachment. A forward_auth service NEVER gets an oauth2 provider, so
# the MTI shared-base cascade (ADR-0001 trigger) is impossible by construction.
terraform {
  required_providers {
    authentik = { source = "goauthentik/authentik" }
  }
}

locals {
  is_oidc  = var.mode == "native_oidc"
  is_proxy = !local.is_oidc
}

resource "authentik_provider_oauth2" "this" {
  count               = local.is_oidc ? 1 : 0
  name                = var.name
  client_id           = coalesce(var.client_id, "nos-${var.slug}")
  client_secret       = var.client_secret
  client_type         = "confidential"
  # Authentik 2026.5.x made grant_types an explicit ArrayField — a provider
  # created WITHOUT it gets an empty list and every authorization_code
  # request dies with invalid_request "The request is otherwise malformed"
  # (first hit live: grafana + gitlab SSO logins after the tofu cutover;
  # the 10-oidc-apps blueprint always set this). Minimal set, no ROPC —
  # mirrors the blueprint + test_oauth2_grant_types.py doctrine.
  grant_types         = ["authorization_code", "refresh_token"]
  authorization_flow  = var.authorization_flow_id
  authentication_flow = var.authentication_flow_id
  invalidation_flow   = var.invalidation_flow_id
  signing_key         = var.signing_key_id
  property_mappings   = var.scope_mapping_ids
  sub_mode            = "hashed_user_id"
  include_claims_in_id_token = true
  issuer_mode         = "per_provider"
  access_code_validity   = "minutes=10"
  access_token_validity  = "minutes=10"
  refresh_token_validity = "days=30"
  allowed_redirect_uris = [for u in var.redirect_uris : {
    matching_mode     = "strict"
    url               = u
    redirect_uri_type = "authorization"
  }]
}

resource "authentik_provider_proxy" "this" {
  count               = local.is_proxy ? 1 : 0
  name                = var.name
  external_host       = var.external_host
  mode                = var.proxy_mode
  authorization_flow  = var.authorization_flow_id
  authentication_flow = var.authentication_flow_id
  invalidation_flow   = var.invalidation_flow_id
  internal_host_ssl_validation = var.internal_host_ssl_validation
  access_token_validity        = "hours=1"
  refresh_token_validity       = "days=30"
}

resource "authentik_application" "this" {
  name              = var.name
  slug              = var.slug
  meta_launch_url   = var.external_host
  open_in_new_tab   = true
  policy_engine_mode = "any"
  protocol_provider = local.is_oidc ? authentik_provider_oauth2.this[0].id : authentik_provider_proxy.this[0].id
}

# Proxy providers must be bound to the embedded outpost or forward-auth 404s
# (the exact outpost-binding gap behind the triggering incident).
resource "authentik_outpost_provider_attachment" "embedded" {
  count             = local.is_proxy ? 1 : 0
  outpost           = var.outpost_id
  protocol_provider = authentik_provider_proxy.this[0].id
}
