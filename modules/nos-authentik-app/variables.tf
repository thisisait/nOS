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
  type    = bool
  default = false
}
