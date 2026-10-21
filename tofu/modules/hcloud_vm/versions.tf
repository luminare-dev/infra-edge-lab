terraform {
  required_version = ">= 1.11.0"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.69"
    }
    # Only for the tunnel token data source, which is read when fetch_tunnel_token = true.
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.25"
    }
  }
}
