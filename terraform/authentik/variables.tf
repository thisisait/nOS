variable "authentik_url" {
  type        = string
  description = "Authentik base URL (loopback on the operator host)."
}
variable "authentik_token" {
  type        = string
  sensitive   = true
  description = "Authentik API token (authentik_bootstrap_token), bridged from the playbook."
}

# ── Per-service values (rendered into nos.auto.tfvars.json by the playbook) ──
variable "infisical_url" {
  type    = string
  default = "https://vault.dev.local"
}
variable "grafana_url" {
  type    = string
  default = "https://grafana.dev.local"
}
variable "grafana_oidc_client_secret" {
  type      = string
  default   = ""
  sensitive = true
}
