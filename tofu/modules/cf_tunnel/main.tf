# A remotely managed Cloudflare tunnel (its configuration is held by Cloudflare, so there is no
# credentials file on the host), its ingress rules and the DNS records that point at it. The
# tunnel token is never read here and never an output: the configure step fetches it from the
# API when it needs it.

locals {
  # Comment on every record this module creates; the sweeper and a reviewer of the zone use it
  # to tell these records apart from the rest of the zone.
  comment = "managed-by-tofu env=${var.env}"

  # The last rule of every tunnel answers 404 for any hostname or path that no rule above
  # matches, so a request never falls through to an origin by accident. It is last by
  # construction (concat below); the variable validations give every rule in front of it a
  # hostname, and the catch_all_last test checks the result.
  catch_all = {
    hostname       = null
    service        = "http_status:404"
    path           = null
    origin_request = null
  }

  ingress = concat(
    [for r in var.ingress : {
      hostname       = r.hostname
      service        = r.service
      path           = r.path
      origin_request = r.origin_request
    }],
    [local.catch_all],
  )
}

resource "cloudflare_zero_trust_tunnel_cloudflared" "this" {
  account_id = var.account_id
  name       = var.tunnel_name
  # Remotely managed: no tunnel_secret; the connector authenticates with the tunnel token.
  config_src = "cloudflare"
}

resource "cloudflare_zero_trust_tunnel_cloudflared_config" "this" {
  account_id = var.account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.this.id

  config = {
    ingress = local.ingress
  }
}

resource "cloudflare_dns_record" "tunnel" {
  for_each = toset(var.dns_names)

  zone_id = var.zone_id
  name    = "${each.key}.${var.zone}"
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.this.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1 # automatic, as required for proxied records
  comment = local.comment
}

resource "cloudflare_dns_record" "address" {
  for_each = var.address_records

  zone_id = var.zone_id
  name    = "${each.key}.${var.zone}"
  type    = each.value.type
  content = each.value.content
  proxied = false
  ttl     = each.value.ttl
  comment = local.comment

  lifecycle {
    # Second line of the record-type guard, after the variable validation.
    precondition {
      condition     = contains(local.address_record_types, each.value.type) && contains(local.address_record_envs, var.env)
      error_message = "DNS-only records next to the tunnel must be A or AAAA, and only in showcase."
    }
  }
}
