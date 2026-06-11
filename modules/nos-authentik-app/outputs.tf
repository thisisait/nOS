output "mode"          { value = var.mode }
output "slug"          { value = var.slug }
output "application_id" { value = authentik_application.this.id }
output "provider_id"   { value = local.is_oidc ? authentik_provider_oauth2.this[0].id : authentik_provider_proxy.this[0].id }
output "is_proxy"      { value = local.is_proxy }
