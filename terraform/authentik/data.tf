# Tenant-global lookups shared by every nos-authentik-app module instance.
# Names mirror the values the imperative blueprint (10-oidc-apps.yaml) used,
# so an imported tenant reads no-change.
data "authentik_flow" "authorization" { slug = "default-provider-authorization-implicit-consent" }
data "authentik_flow" "authentication" { slug = "default-authentication-flow" }
data "authentik_flow" "invalidation" { slug = "default-provider-invalidation-flow" }

data "authentik_outpost" "embedded" { name = "authentik Embedded Outpost" }

data "authentik_certificate_key_pair" "signing" { name = "authentik Self-signed Certificate" }

# By `managed` where a nOS mapping could share the scope_name: nos_roles
# (services.tf) is scope_name "profile", so a scope_name lookup could resolve
# to it instead of the stock mapping (#52) — the blueprint path's bug, mirrored.
data "authentik_property_mapping_provider_scope" "openid"          { managed = "goauthentik.io/providers/oauth2/scope-openid" }
data "authentik_property_mapping_provider_scope" "email"           { managed = "goauthentik.io/providers/oauth2/scope-email" }
data "authentik_property_mapping_provider_scope" "profile"         { managed = "goauthentik.io/providers/oauth2/scope-profile" }
data "authentik_property_mapping_provider_scope" "offline_access"  { scope_name = "offline_access" }  # no nOS mapping shares it
