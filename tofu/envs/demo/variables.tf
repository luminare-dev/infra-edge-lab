# Inputs of the demo environment: one host that is thrown away after each use, on a cloud server
# (substrate = "hcloud") or as a systemd container on the Docker daemon of a CI runner
# (substrate = "docker"), published through its own tunnel behind Access (docs/adr/0014). The
# state passphrase is declared in encryption.tofu.

variable "substrate" {
  description = "What runs the host: hcloud (a Hetzner Cloud server) or docker (a systemd container on the local Docker daemon, for the tunnel end-to-end test on a CI runner)."
  type        = string
  default     = "hcloud"

  validation {
    condition     = contains(["hcloud", "docker"], var.substrate)
    error_message = "The substrate must be hcloud or docker."
  }
}

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
  description = "E-mail addresses that may log in to demo-tx (one-time PIN). Needed only while the host is in the group fxserver; demo-web and demo-ssh use service tokens."
  type        = list(string)
  default     = []
}

variable "allowed_idps" {
  description = "IDs of the identity providers offered by demo-tx. Empty means every provider of the organization."
  type        = list(string)
  default     = []
}

variable "tunnel_name" {
  description = "Name of the demo tunnel; it starts with demo-."
  type        = string
  default     = "demo-edge"
}

variable "hosts" {
  description = "The one host of the demo, keyed by host name, with its inventory groups. It must be in the group edge (it runs the tunnel connector); with the group fxserver, demo-tx is added."
  type = map(object({
    groups = list(string)
  }))
  default = {
    edge-01 = { groups = ["edge", "db"] }
  }

  validation {
    condition     = length(var.hosts) == 1
    error_message = "The demo holds exactly one host."
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

variable "ssh_public_key" {
  description = "Public key of the admin user on the cloud server; required with substrate = hcloud."
  type        = string
  default     = null

  validation {
    condition     = var.substrate != "hcloud" || var.ssh_public_key != null
    error_message = "With substrate = hcloud, the ssh_public_key must be set."
  }
}

variable "server_type" {
  description = "Server type with substrate = hcloud (x86-64 only)."
  type        = string
  default     = "cx23"
}

variable "location" {
  description = "Location of the server with substrate = hcloud: nbg1 or fsn1."
  type        = string
  default     = "nbg1"
}

variable "image" {
  description = "Operating system image with substrate = hcloud."
  type        = string
  default     = "debian-13"
}

variable "fetch_tunnel_token" {
  description = "With substrate = hcloud: read the tunnel token during the plan and start cloudflared with it at first boot. It needs a Cloudflare token with tunnel write permission, so read-only plans leave it false."
  type        = bool
  default     = false
}

variable "enable_ci_ssh_fw" {
  description = "With substrate = hcloud: create the extra firewall for SSH from a CI runner (fallback for the first Ansible run without the tunnel)."
  type        = bool
  default     = false
}

variable "ci_ssh_source_ips" {
  description = "Source ranges of the CI SSH firewall when it is created, for example [\"198.51.100.7/32\"]."
  type        = list(string)
  default     = []
}

variable "platform" {
  description = "Operating system of the container with substrate = docker: debian13 or ubuntu2404."
  type        = string
  default     = "debian13"
}

variable "name_prefix" {
  description = "Prefix of the container, network and image names with substrate = docker."
  type        = string
  default     = "lab-"
}
