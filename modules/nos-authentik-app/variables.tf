variable "mode" {
  type        = string
  description = "nOS SSO doctrine label: native_oidc | forward_auth | header_oidc."
  validation {
    condition     = contains(["native_oidc", "forward_auth", "header_oidc"], var.mode)
    error_message = "mode must be native_oidc, forward_auth, or header_oidc."
  }
}
variable "slug" { type = string }
variable "name" { type = string }
variable "external_host" {
  type        = string
  description = "Public https URL (proxy external_host + app launch URL)."
}
variable "authorization_flow_id"  { type = string }
variable "authentication_flow_id" { type = string }
variable "invalidation_flow_id"   { type = string }
variable "outpost_id"             { type = string }
variable "signing_key_id"         { type = string }
variable "scope_mapping_ids"      { type = list(string) }
variable "client_id" {
  type    = string
  default = ""
}
variable "client_secret" {
  type      = string
  default   = ""
  sensitive = true
}
variable "redirect_uris" {
  type    = list(string)
  default = []
}
variable "proxy_mode" {
  type    = string
  default = "forward_single"
}
variable "internal_host_ssl_validation" {
  type = bool
  # true matches Authentik's server-side default. With no internal_host set
  # (forward_single proxies route via Traefik, not the outpost) Authentik
  # normalizes the field back to true regardless of what the API write sent —
  # default=false produced a PERPETUAL 23-provider in-place diff (true->false
  # on every plan, re-applied forever, never converging).
  default = true
}
