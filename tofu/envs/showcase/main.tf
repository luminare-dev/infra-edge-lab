# The showcase: a skeleton for one long-lived cloud server that is never thrown away. It is not
# applied from this repository yet (docs/adr/0014). Everything here is protected: the server
# has delete and rebuild protection, and its primary IPv4 address outlives a replacement of
# the server, so that the DNS-only record "play" (game traffic over UDP, which a tunnel cannot
# carry) stays valid. The zone, the account and every credential come from the environment
# (secrets/showcase.enc.env); none is written here.

# CLOUDFLARE_API_TOKEN, limited to the zone.
provider "cloudflare" {}

# HCLOUD_TOKEN of the project that holds nothing but this lab.
provider "hcloud" {}

locals {
  # Fixed, not a variable: a showcase is always protected.
  protect = true

  host_name   = keys(var.hosts)[0]
  game_server = contains(var.hosts[local.host_name].groups, "fxserver")

  # show-web is public. People log in to show-tx and show-status with a one-time PIN; show-ssh
  # is for machines (CI and deploys) with a service token.
  access_apps = merge(
    { show-ssh = { type = "ssh", auth = "service_auth" } },
    local.game_server ? { show-tx = { type = "self_hosted", auth = "email_otp" } } : {},
    var.status_origin == null ? {} : { show-status = { type = "self_hosted", auth = "email_otp" } },
  )

  # cloudflared also checks the Access token of the web hostnames itself; the SSH hostname is
  # checked by Access at the edge and by the SSH keys of the host.
  access = {
    for name in keys(local.access_apps) : name => {
      required  = true
      team_name = var.access_team_name
      aud_tag   = [module.access.aud_tags[name]]
    }
  }

  # The connector runs on the server, so its own origins are on localhost. The tunnel module
  # appends the catch-all rule.
  ingress = concat(
    [
      { hostname = "show-web.${var.zone}", service = "http://localhost:80" },
      { hostname = "show-ssh.${var.zone}", service = "ssh://localhost:22" },
    ],
    local.game_server ? [
      {
        hostname       = "show-tx.${var.zone}"
        service        = "http://localhost:40120"
        origin_request = { access = local.access["show-tx"] }
      },
    ] : [],
    var.status_origin == null ? [] : [
      {
        hostname       = "show-status.${var.zone}"
        service        = var.status_origin
        origin_request = { access = local.access["show-status"] }
      },
    ],
  )
}

module "server" {
  source   = "../../modules/hcloud_vm"
  for_each = var.hosts

  name           = "show-${each.key}"
  env            = "showcase"
  server_type    = var.server_type
  image          = var.image
  location       = var.location
  ssh_public_key = var.ssh_public_key
  protect        = local.protect
  use_primary_ip = true
  # The game port is open only on a game server host (play points at it).
  game_port_open = contains(each.value.groups, "fxserver")

  fetch_tunnel_token = var.fetch_tunnel_token
  account_id         = var.account_id
  tunnel_id          = module.tunnel.tunnel_id
}

module "access" {
  source = "../../modules/cf_access_app"

  account_id     = var.account_id
  zone           = var.zone
  env            = "showcase"
  apps           = local.access_apps
  allowed_emails = var.allowed_emails
  allowed_idps   = var.allowed_idps
}

module "tunnel" {
  source = "../../modules/cf_tunnel"

  account_id  = var.account_id
  zone_id     = var.zone_id
  zone        = var.zone
  env         = "showcase"
  tunnel_name = var.tunnel_name
  dns_names   = [for r in local.ingress : trimsuffix(r.hostname, ".${var.zone}")]
  ingress     = local.ingress

  # Game traffic (UDP) cannot go through the tunnel: play is a DNS-only A record of the
  # server's primary IPv4 address.
  address_records = {
    play = { type = "A", content = module.server[local.host_name].ipv4 }
  }
}
