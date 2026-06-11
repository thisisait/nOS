# nOS — OpenTofu root for the Authentik consumer (ADR-0001, Phase 0).
# OpenTofu, NEVER Terraform (BSL conflicts with nOS all-FOSS). Provider pinned;
# .terraform.lock.hcl joins the frozen-CI toolchain next to requirements.lock.yml.
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    authentik = {
      source  = "goauthentik/authentik"
      version = "~> 2026.5"
    }
  }
}
