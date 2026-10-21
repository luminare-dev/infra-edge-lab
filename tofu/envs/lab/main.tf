# The lab: virtual machines on Proxmox VE, published through one remotely managed tunnel whose
# connector runs on the edge host (docs/adr/0014). Only lab-demo is public; the hypervisor UI,
# the status page and the game server admin panel sit behind Cloudflare Access, and lab-pveapi
# lets CI reach the Proxmox VE API with a service token. The zone, the account and every
# credential come from the environment (secrets/lab.enc.env); none is written here.

# PROXMOX_VE_ENDPOINT, PROXMOX_VE_API_TOKEN and, behind Access, PROXMOX_VE_API_HEADERS.
provider "proxmox" {}

# CLOUDFLARE_API_TOKEN, limited to the zone.
provider "cloudflare" {}

locals {
  fx_hosts = [for name, h in var.hosts : name if contains(h.groups, "fxserver")]
  fx_host  = length(local.fx_hosts) == 1 ? local.fx_hosts[0] : null

  # Access applications: people log in with a one-time PIN, CI uses a service token. lab-tx
  # exists only while a host is in the group fxserver.
  access_apps = merge(
    {
      lab-pve    = { type = "self_hosted", auth = "email_otp" }
      lab-status = { type = "self_hosted", auth = "email_otp" }
      lab-pveapi = { type = "self_hosted", auth = "service_auth" }
    },
    local.fx_host == null ? {} : { lab-tx = { type = "self_hosted", auth = "email_otp" } },
  )

  # cloudflared itself also rejects a request to these hostnames without a valid Access token.
  access = {
    for name in keys(local.access_apps) : name => {
      required  = true
      team_name = var.access_team_name
      aud_tag   = [module.access.aud_tags[name]]
    }
  }

  # Ingress rules of the tunnel. The connector runs on the edge host, so 127.0.0.1 is the edge
  # host itself. The Proxmox VE API has a self-signed certificate, hence no_tls_verify; the
  # connection runs inside the lab network only. The tunnel module appends the catch-all rule.
  ingress = concat(
    [
      { hostname = "lab-demo.${var.zone}", service = "http://127.0.0.1:8080" },
      {
        hostname       = "lab-status.${var.zone}"
        service        = "http://127.0.0.1:3001"
        origin_request = { access = local.access["lab-status"] }
      },
    ],
    local.fx_host == null ? [] : [
      {
        hostname       = "lab-tx.${var.zone}"
        service        = "http://${module.vm[local.fx_host].ipv4}:40120"
        origin_request = { access = local.access["lab-tx"] }
      },
    ],
    [
      {
        hostname       = "lab-pve.${var.zone}"
        service        = "https://${var.pve_ip}:8006"
        origin_request = { no_tls_verify = true, access = local.access["lab-pve"] }
      },
      {
        hostname       = "lab-pveapi.${var.zone}"
        service        = "https://${var.pve_ip}:8006"
        origin_request = { no_tls_verify = true, access = local.access["lab-pveapi"] }
      },
    ],
  )
}

module "vm" {
  source   = "../../modules/pve_vm"
  for_each = var.hosts

  name      = each.key
  env       = "lab"
  node_name = var.node_name
  vm_id     = each.value.vm_id
  cores     = each.value.cores
  memory    = each.value.memory
  disk_gb   = each.value.disk_gb
  ipv4_cidr = each.value.ipv4_cidr
  gateway   = var.gateway
  ssh_keys  = var.ssh_keys
  tags      = each.value.groups
  protect   = each.value.protect
}

module "access" {
  source = "../../modules/cf_access_app"

  account_id     = var.account_id
  zone           = var.zone
  env            = "lab"
  apps           = local.access_apps
  allowed_emails = var.allowed_emails
  allowed_idps   = var.allowed_idps
}

module "tunnel" {
  source = "../../modules/cf_tunnel"

  account_id  = var.account_id
  zone_id     = var.zone_id
  zone        = var.zone
  env         = "lab"
  tunnel_name = var.tunnel_name
  dns_names   = [for r in local.ingress : trimsuffix(r.hostname, ".${var.zone}")]
  ingress     = local.ingress
}
