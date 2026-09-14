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

# Escape-hatch OAuth2 device-code client (RFC 8628). Not in authentik_services:
# that map is generated from plugin authentik: blocks and would mint a
# confidential authorization_code provider. Default false → tofu is a no-op.
variable "install_device_gateway" {
  type        = bool
  default     = false
  description = "Mint the public nos-device-gateway OAuth2 client (device_code + refresh_token)."
}
