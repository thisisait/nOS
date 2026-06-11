# Auth from playbook-bridged values (variables.tf ← nos.auto.tfvars.json).
# The bootstrap token is the same one the blueprint apply uses today; it never
# lives in HCL — it flows through the 0600 tfvars.json (Infisical custody).
provider "authentik" {
  url   = var.authentik_url
  token = var.authentik_token
}
