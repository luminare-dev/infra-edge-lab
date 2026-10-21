# The demo: one throw-away host with its own tunnel and Access applications, never protected
# (docs/adr/0014). substrate = "hcloud" creates a cloud server; substrate = "docker" creates the
# same host as a systemd container on the local Docker daemon, so the tunnel can be tested end
# to end on a CI runner without a cloud server. Names, records and Access rules are the same for
# both. The zone, the account and every credential come from the environment
# (secrets/demo.enc.env); none is written here.

# CLOUDFLARE_API_TOKEN, limited to the zone.
provider "cloudflare" {}

# HCLOUD_TOKEN of the project that holds nothing but this lab (used with substrate = hcloud).
# OpenTofu starts the provider even when no server is planned, and the provider refuses to start
# without a token of 64 characters. With substrate = docker it therefore gets 64 zeros, a value
# the API would reject; no server exists then, so nothing calls the API.
provider "hcloud" {
  token = var.substrate == "docker" ? format("%064d", 0) : null
}

# The local daemon: DOCKER_HOST, or the default socket (used with substrate = docker). The
# provider contacts the daemon only for a container or an image, so substrate = hcloud needs
# no Docker daemon.
provider "docker" {}

locals {
  host_name   = keys(var.hosts)[0]
  game_server = contains(var.hosts[local.host_name].groups, "fxserver")

  # demo-web and demo-ssh are for machines (the end-to-end test and CI), with a service token
  # each; demo-tx is for people (one-time PIN) and exists only on a game server host.
  access_apps = merge(
    {
      demo-web = { type = "self_hosted", auth = "service_auth" }
      demo-ssh = { type = "ssh", auth = "service_auth" }
    },
    local.game_server ? { demo-tx = { type = "self_hosted", auth = "email_otp" } } : {},
  )

  # cloudflared also checks the Access token of the web hostnames itself. The SSH hostname is
  # checked by Access at the edge and by the SSH keys of the host; the token check of
  # cloudflared is set for web origins only.
  access = {
    for name in keys(local.access_apps) : name => {
      required  = true
      team_name = var.access_team_name
      aud_tag   = [module.access.aud_tags[name]]
    }
  }

  # The connector runs on the host itself, so every origin is on localhost. The tunnel module
  # appends the catch-all rule.
  ingress = concat(
    [
      {
        hostname       = "demo-web.${var.zone}"
        service        = "http://localhost:80"
        origin_request = { access = local.access["demo-web"] }
      },
      { hostname = "demo-ssh.${var.zone}", service = "ssh://localhost:22" },
    ],
    local.game_server ? [
      {
        hostname       = "demo-tx.${var.zone}"
        service        = "http://localhost:40120"
        origin_request = { access = local.access["demo-tx"] }
      },
    ] : [],
  )
}

module "server" {
  source   = "../../modules/hcloud_vm"
  for_each = var.substrate == "hcloud" ? var.hosts : {}

  name           = "demo-${each.key}"
  env            = "demo"
  server_type    = var.server_type
  image          = var.image
  location       = var.location
  ssh_public_key = var.ssh_public_key
  # The demo is thrown away after each use: never protected, no billed primary IP.
  protect        = false
  use_primary_ip = false
  # The game port is open only on a game server host.
  game_port_open = contains(each.value.groups, "fxserver")

  fetch_tunnel_token = var.fetch_tunnel_token
  account_id         = var.account_id
  tunnel_id          = module.tunnel.tunnel_id
  enable_ci_ssh_fw   = var.enable_ci_ssh_fw
  ci_ssh_source_ips  = var.ci_ssh_source_ips
}

module "containers" {
  source = "../../modules/docker_host"
  count  = var.substrate == "docker" ? 1 : 0

  env         = "demo"
  hosts       = var.hosts
  platform    = var.platform
  name_prefix = var.name_prefix
}

module "access" {
  source = "../../modules/cf_access_app"

  account_id     = var.account_id
  zone           = var.zone
  env            = "demo"
  apps           = local.access_apps
  allowed_emails = var.allowed_emails
  allowed_idps   = var.allowed_idps
}

module "tunnel" {
  source = "../../modules/cf_tunnel"

  account_id  = var.account_id
  zone_id     = var.zone_id
  zone        = var.zone
  env         = "demo"
  tunnel_name = var.tunnel_name
  dns_names   = [for r in local.ingress : trimsuffix(r.hostname, ".${var.zone}")]
  ingress     = local.ingress
}
