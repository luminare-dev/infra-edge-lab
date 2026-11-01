# Inputs of the showcase environment: a skeleton for one long-lived, protected cloud server with
# a stable address, its own tunnel and Access applications. It is not applied
# from this repository yet. The state passphrase is declared in encryption.tofu.

variable "zone" {
  description = "DNS zone of the hostnames, for example example.com. It is always passed in (TF_VAR_zone) and never written in this repository."
  type        = string
}

variable "account_id" {
  description = "Cloudflare account ID that owns the tunnel and the Access applications."
  type        = string
}

variable "zone_id" {
  description = "Cloudflare zone ID of var.zone."
  type        = string
}

variable "access_team_name" {
  description = "Team name of the Cloudflare Zero Trust organization; cloudflared checks the Access token of every protected web hostname against it."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,62}$", var.access_team_name))
    error_message = "The access_team_name must be lower-case letters, digits and hyphens."
  }
}

variable "allowed_emails" {
  description = "E-mail addresses that may log in to the Access applications for people (one-time PIN): show-tx and show-status."
  type        = list(string)
}

variable "allowed_idps" {
  description = "IDs of the identity providers offered by the applications for people. Empty means every provider of the organization."
  type        = list(string)
  default     = []
}

variable "tunnel_name" {
  description = "Name of the showcase tunnel; it starts with show-."
  type        = string
  default     = "show-edge"
}

variable "hosts" {
  description = "The one host of the showcase, keyed by host name, with its inventory groups. It must be in the group edge (it runs the tunnel connector); with the group fxserver, show-tx is added."
  type = map(object({
    groups = list(string)
  }))
  default = {
    edge-01 = { groups = ["edge", "db", "fxserver"] }
  }

  validation {
    condition     = length(var.hosts) == 1
    error_message = "The showcase holds exactly one host."
  }

  validation {
    condition     = alltrue([for name in keys(var.hosts) : can(regex("^[a-z][a-z0-9-]{0,39}$", name))])
    error_message = "The host name must start with a letter and hold only lower-case letters, digits and hyphens (at most 40 characters)."
  }

  validation {
    condition = alltrue([
      for h in values(var.hosts) : contains(h.groups, "edge") && alltrue([
        for g in h.groups : contains(["edge", "db", "fxserver", "monitoring", "docker_hosts"], g)
      ])
    ])
    error_message = "The host must be in the group edge, and its groups must come from edge, db, fxserver, monitoring and docker_hosts."
  }
}

variable "status_origin" {
  description = "Origin of show-status, for example http://192.0.2.50:3001. The status page watches the showcase from another host, so there is no default; null leaves show-status out."
  type        = string
  default     = null

  validation {
    condition     = var.status_origin == null || can(regex("^https?://\\S+$", var.status_origin))
    error_message = "The status_origin must be null or an http:// or https:// origin."
  }
}

variable "ssh_public_key" {
  description = "Public key of the admin user on the server."
  type        = string
}

variable "server_type" {
  description = "Server type (x86-64 only)."
  type        = string
  default     = "cx23"
}

variable "location" {
  description = "Location of the server and its primary IP: nbg1 or fsn1."
  type        = string
  default     = "nbg1"
}

variable "image" {
  description = "Operating system image."
  type        = string
  default     = "debian-13"
}

variable "fetch_tunnel_token" {
  description = "Read the tunnel token during the plan and start cloudflared with it at first boot. It needs a Cloudflare token with tunnel write permission, so read-only plans leave it false."
  type        = bool
  default     = false
}
