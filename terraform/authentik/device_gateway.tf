# Escape hatch: RFC 8628 device-code client for the handheld BFF.
# Not a nos-authentik-app for_each instance — that module mints confidential
# browser-redirect providers. count=0 when install_device_gateway is false.
#
# Flipping the flag off plans DESTROY of these root resources. nos_tofu_destroy_split
# only attributes module.service["slug"]; that destroy needs a supervised tofu apply.
#
# grant_types values are Authentik 2026.5 GrantType choices
# (authentik/common/oauth/constants.py): DEVICE_CODE =
# "urn:ietf:params:oauth:grant-type:device_code", REFRESH_TOKEN =
# "refresh_token". Token POST uses grant_type= that URN. No ROPC,
# no browser redirect grant (a device has no redirect).

resource "authentik_provider_oauth2" "device_gateway" {
  count = var.install_device_gateway ? 1 : 0

  name        = "nOS device gateway"
  client_id   = "nos-device-gateway"
  client_type = "public"
  grant_types = [
    "urn:ietf:params:oauth:grant-type:device_code",
    "refresh_token",
  ]

  authorization_flow  = data.authentik_flow.authorization.id
  authentication_flow = data.authentik_flow.authentication.id
  invalidation_flow   = data.authentik_flow.invalidation.id
  signing_key         = data.authentik_certificate_key_pair.signing.id
  # offline_access is device-only — browser apps in module.service stay the
  # three OIDC scopes. Without this mapping Authentik mints no refresh_token.
  property_mappings = concat(local._scopes, [
    data.authentik_property_mapping_provider_scope.offline_access.id,
  ])

  sub_mode    = "hashed_user_id"
  issuer_mode = "per_provider"

  include_claims_in_id_token = true
  access_code_validity       = "minutes=10"
  access_token_validity      = "minutes=10"
  refresh_token_validity     = "days=30"
  # Remaining lifetime ≤ validity ⇒ Authentik issues a new refresh token on use.
  refresh_token_threshold = "days=30"
}

resource "authentik_application" "device_gateway" {
  count = var.install_device_gateway ? 1 : 0

  name               = "nOS device gateway"
  slug               = "device-gateway"
  protocol_provider  = authentik_provider_oauth2.device_gateway[0].id
  policy_engine_mode = "any"
  open_in_new_tab    = false
}
