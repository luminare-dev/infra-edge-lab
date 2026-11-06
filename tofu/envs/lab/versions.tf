terraform {
  required_version = ">= 1.11.0"

  required_providers {
    # Below 1.0 a minor release may break: "~> 0.116.1" accepts patch releases only.
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.116.1"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.25"
    }
  }
}
