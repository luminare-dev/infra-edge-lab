# Inputs of the cf_tunnel module. Every DNS name and ingress hostname is checked against the
# rules in guard.tf before a plan is made (docs/adr/0009).

variable "account_id" {
  description = "Cloudflare account ID that owns the tunnel (32 hexadecimal characters)."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.account_id))
    error_message = "The account_id must be a Cloudflare account ID: 32 lower-case hexadecimal characters."
  }
}

variable "zone_id" {
  description = "Cloudflare zone ID of var.zone (32 hexadecimal characters)."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.zone_id))
    error_message = "The zone_id must be a Cloudflare zone ID: 32 lower-case hexadecimal characters."
  }
}

variable "zone" {
  description = "DNS zone the hostnames are created in, for example example.com. It is always passed in and never written in this repository."
  type        = string

  validation {
    condition     = can(regex("^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$", var.zone))
    error_message = "The zone must be a lower-case domain name without a trailing dot, for example example.com."
  }
}

variable "env" {
  description = "Environment that owns the tunnel and its records: lab, demo or showcase. It selects the allowed name prefix."
  type        = string

  validation {
    condition     = contains(["lab", "demo", "showcase"], var.env)
    error_message = "The env must be one of lab, demo or showcase."
  }
}

variable "tunnel_name" {
  description = "Name of the remotely managed tunnel, starting with the prefix of the environment (lab-, demo- or show-)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,62}$", var.tunnel_name)) && startswith(var.tunnel_name, local.tunnel_prefix)
    error_message = "The tunnel_name must be lower-case letters, digits and hyphens and start with the prefix of env: lab-, demo- or show-."
  }
}

variable "dns_names" {
  description = "First-level labels that get a proxied CNAME to the tunnel, for example [\"lab-demo\"]. lab allows lab-*, demo allows demo-*, showcase allows show-* and play."
  type        = list(string)

  validation {
    condition     = length(distinct(var.dns_names)) == length(var.dns_names)
    error_message = "The dns_names must not repeat a name."
  }

  validation {
    condition = alltrue([
      for n in var.dns_names :
      !contains(local.reserved_names, n) && !strcontains(n, "_domainkey") && !strcontains(n, ".")
    ])
    error_message = "The dns_names must not contain the zone apex (@), a reserved name (www, mx, scripts, triage, _dmarc, mta-sts, _mta-sts, *._domainkey) or a dotted name."
  }

  validation {
    condition     = alltrue([for n in var.dns_names : can(regex(local.name_pattern, n))])
    error_message = "Every dns_names entry must be a first-level label with the prefix of env: lab-* in lab, demo-* in demo, show-* or play in showcase."
  }
}

variable "address_records" {
  description = "DNS-only A or AAAA records, keyed by first-level label, for traffic a tunnel cannot carry (UDP game traffic on play). Allowed in showcase only, with the same name rules as dns_names."
  type = map(object({
    type    = string
    content = string
    ttl     = optional(number, 300)
  }))
  default = {}

  validation {
    condition     = length(var.address_records) == 0 || contains(local.address_record_envs, var.env)
    error_message = "The address_records are allowed in showcase only; lab and demo reach their hosts through the tunnel."
  }

  validation {
    condition     = alltrue([for r in values(var.address_records) : contains(local.address_record_types, r.type)])
    error_message = "The address_records may only be of type A or AAAA; this module never creates MX, TXT or any other record type."
  }

  validation {
    condition = alltrue([
      for r in values(var.address_records) : (
        r.type == "A"
        ? can(regex("^(\\d{1,3}\\.){3}\\d{1,3}$", r.content)) && can(cidrhost("${r.content}/32", 0))
        : strcontains(r.content, ":") && can(cidrhost("${r.content}/128", 0))
      )
    ])
    error_message = "Each address_records content must be an IPv4 address for type A or an IPv6 address for type AAAA."
  }

  validation {
    condition     = alltrue([for r in values(var.address_records) : r.ttl >= 60 && r.ttl <= 86400])
    error_message = "Each address_records ttl must be between 60 and 86400 seconds."
  }

  validation {
    condition = alltrue([
      for n in keys(var.address_records) :
      !contains(local.reserved_names, n) && !strcontains(n, "_domainkey") && !strcontains(n, ".")
    ])
    error_message = "The address_records must not use the zone apex (@), a reserved name (www, mx, scripts, triage, _dmarc, mta-sts, _mta-sts, *._domainkey) or a dotted name."
  }

  validation {
    condition     = alltrue([for n in keys(var.address_records) : can(regex(local.name_pattern, n))])
    error_message = "Every address_records name must be a first-level label with the prefix of env: show-* or play in showcase."
  }

  validation {
    condition     = length(setintersection(toset(keys(var.address_records)), toset(var.dns_names))) == 0
    error_message = "A name must not be in both dns_names and address_records."
  }
}

variable "ingress" {
  description = "Ingress rules of the tunnel, in order. Each hostname is <label>.<zone> with a label from dns_names. The module appends the catch-all rule (http_status:404) itself."
  type = list(object({
    hostname = string
    service  = string
    path     = optional(string)
    origin_request = optional(object({
      no_tls_verify      = optional(bool)
      origin_server_name = optional(string)
      ca_pool            = optional(string)
      http_host_header   = optional(string)
      access = optional(object({
        required  = optional(bool, true)
        team_name = string
        aud_tag   = list(string)
      }))
    }))
  }))

  validation {
    condition     = length(var.ingress) > 0
    error_message = "The ingress must hold at least one rule; the catch-all rule is added by the module."
  }

  validation {
    condition = alltrue([
      for r in var.ingress :
      endswith(r.hostname, ".${var.zone}") && can(regex(local.name_pattern, trimsuffix(r.hostname, ".${var.zone}")))
    ])
    error_message = "Every ingress hostname must be <label>.<zone> with a first-level label that has the prefix of env (lab-*, demo-*, show-* or play)."
  }

  validation {
    condition     = alltrue([for r in var.ingress : contains(var.dns_names, trimsuffix(r.hostname, ".${var.zone}"))])
    error_message = "Every ingress hostname must have its label in dns_names, so that each rule has a DNS record."
  }

  validation {
    condition = alltrue([
      for r in var.ingress :
      can(regex("^(https?|ssh|tcp|rdp|unix)://\\S+$", r.service)) || can(regex("^http_status:[1-5][0-9]{2}$", r.service))
    ])
    error_message = "Each ingress service must be an http://, https://, ssh://, tcp://, rdp:// or unix:// origin, or http_status:<code>."
  }

  validation {
    condition     = alltrue([for r in var.ingress : try(r.origin_request.access.required, true)])
    error_message = "An ingress rule with origin_request.access must keep required = true, so cloudflared itself rejects requests without a valid Access token."
  }
}
