# ── nOS services — data-driven Authentik wiring (ADR-0001 §9 + Phase 1) ──────
# ONE hand-authored for_each module over var.authentik_services (a map rendered
# by the playbook from the aggregated per-plugin authentik: blocks — the same
# SoT the imperative blueprint used). Add a plugin → it appears in the map →
# tofu manages it. No per-service HCL. Exotic services that need raw resources
# get their own module/resource block alongside this (the escape hatch).
#
# A forward_auth/header_oidc service yields a proxy provider (never oauth2), so
# the MTI shared-base cascade (ADR-0001 trigger) is impossible by construction.

locals {
  _scopes = [
    data.authentik_property_mapping_provider_scope.openid.id,
    data.authentik_property_mapping_provider_scope.email.id,
    data.authentik_property_mapping_provider_scope.profile.id,
  ]
}

module "service" {
  source   = "../../modules/nos-authentik-app"
  for_each = var.authentik_services

  mode          = each.value.mode
  slug          = each.key
  name          = each.value.name
  external_host = each.value.external_host
  client_id     = lookup(each.value, "client_id", "nos-${each.key}")
  client_secret = lookup(each.value, "client_secret", "")
  redirect_uris = lookup(each.value, "redirect_uris", [])

  authorization_flow_id  = data.authentik_flow.authorization.id
  authentication_flow_id = data.authentik_flow.authentication.id
  invalidation_flow_id   = data.authentik_flow.invalidation.id
  outpost_id             = data.authentik_outpost.embedded.id
  signing_key_id         = data.authentik_certificate_key_pair.signing.id
  scope_mapping_ids      = local._scopes
}
