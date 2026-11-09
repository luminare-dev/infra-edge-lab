terraform {
  required_version = ">= 1.11.0"

  required_providers {
    # Below 1.0, use a patch-only constraint because a minor release may break.
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.120.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.25"
    }
  }
}
