variable "authentik_url" {
  type        = string
  description = "Authentik base URL (loopback on the operator host)."
}
variable "authentik_token" {
  type        = string
  sensitive   = true
  description = "Authentik API token (authentik_bootstrap_token), bridged from the playbook."
}

# The full service map — rendered into nos.auto.tfvars.json by the playbook
# (tasks/tofu-authentik.yml) from state/tofu-authentik-services.yml. Keyed by slug.
variable "authentik_services" {
  description = "Per-service Authentik wiring, keyed by slug."
  type = map(object({
    mode          = string
    name          = string
    external_host = string
    tier          = optional(number, 2)
    client_id     = optional(string, "")
    client_secret = optional(string, "")
    redirect_uris = optional(list(string), [])
  }))
  default = {}
}
