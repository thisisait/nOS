# Tenant-global lookups shared by every nos-authentik-app module instance.
# Names mirror the values the imperative blueprint (10-oidc-apps.yaml) used,
# so an imported tenant reads no-change.
data "authentik_flow" "authorization" { slug = "default-provider-authorization-implicit-consent" }
data "authentik_flow" "authentication" { slug = "default-authentication-flow" }
data "authentik_flow" "invalidation" { slug = "default-provider-invalidation-flow" }

data "authentik_outpost" "embedded" { name = "authentik Embedded Outpost" }

data "authentik_certificate_key_pair" "signing" { name = "authentik Self-signed Certificate" }

data "authentik_property_mapping_provider_scope" "openid"  { scope_name = "openid" }
data "authentik_property_mapping_provider_scope" "email"   { scope_name = "email" }
data "authentik_property_mapping_provider_scope" "profile" { scope_name = "profile" }
