# Inputs of the lab environment: virtual machines on one Proxmox VE node, published through a
# Cloudflare tunnel behind Access (docs/adr/0014). The defaults use documentation addresses
# (192.0.2.0/24); the real values of a lab come from TF_VAR_* in secrets/lab.enc.env or from a
# git-ignored terraform.tfvars. The state passphrase is declared in encryption.tofu.

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
  description = "Team name of the Cloudflare Zero Trust organization; cloudflared checks the Access token of every protected hostname against it."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,62}$", var.access_team_name))
    error_message = "The access_team_name must be lower-case letters, digits and hyphens."
  }
}

variable "allowed_emails" {
  description = "E-mail addresses that may log in to the Access applications for people (one-time PIN): lab-pve, lab-status and lab-tx."
  type        = list(string)
}

variable "allowed_idps" {
  description = "IDs of the identity providers offered by the applications for people, for example the one-time PIN provider. Empty means every provider of the organization."
  type        = list(string)
  default     = []
}

variable "tunnel_name" {
  description = "Name of the lab's tunnel; it starts with lab-."
  type        = string
  default     = "lab-edge"
}

variable "node_name" {
  description = "Proxmox VE node that runs the virtual machines and holds the template."
  type        = string
  default     = "pve"
}

variable "pve_ip" {
  description = "IPv4 address of the Proxmox VE API on the lab network, the origin of lab-pve and lab-pveapi (port 8006). The default is a documentation address."
  type        = string
  default     = "192.0.2.2"

  validation {
    condition     = can(regex("^(\\d{1,3}\\.){3}\\d{1,3}$", var.pve_ip)) && can(cidrhost("${var.pve_ip}/32", 0))
    error_message = "The pve_ip must be an IPv4 address."
  }
}

variable "gateway" {
  description = "IPv4 default gateway of the virtual machines. The default is a documentation address."
  type        = string
  default     = "192.0.2.1"
}

variable "ssh_keys" {
  description = "Public keys of the admin user that cloud-init creates on every virtual machine (Ansible logs in with them)."
  type        = list(string)
}

variable "hosts" {
  description = "Virtual machines keyed by host name: VM ID (110 to 119), static address with prefix length, sizes, inventory groups and the protection flag. Exactly one host is in the group edge (it runs the tunnel connector), at most one in fxserver, and every host in db must be protected."
  type = map(object({
    vm_id     = number
    ipv4_cidr = string
    cores     = optional(number, 1)
    memory    = optional(number, 2048)
    disk_gb   = optional(number, 8)
    groups    = list(string)
    protect   = optional(bool, false)
  }))
  default = {
    edge-01 = { vm_id = 110, ipv4_cidr = "192.0.2.11/24", groups = ["edge", "monitoring"] }
    db-01   = { vm_id = 111, ipv4_cidr = "192.0.2.12/24", cores = 2, memory = 4096, disk_gb = 16, groups = ["db"], protect = true }
    fx-01   = { vm_id = 112, ipv4_cidr = "192.0.2.13/24", cores = 2, memory = 6144, disk_gb = 32, groups = ["fxserver"] }
  }

  validation {
    condition     = alltrue([for name in keys(var.hosts) : can(regex("^[a-z][a-z0-9-]{0,39}$", name))])
    error_message = "Each host name must start with a letter and hold only lower-case letters, digits and hyphens (at most 40 characters)."
  }

  validation {
    condition = alltrue([
      for h in values(var.hosts) : length(h.groups) > 0 && alltrue([
        for g in h.groups : contains(["edge", "db", "fxserver", "monitoring", "docker_hosts"], g)
      ])
    ])
    error_message = "Each host needs at least one group out of edge, db, fxserver, monitoring and docker_hosts."
  }

  validation {
    condition     = length([for h in values(var.hosts) : h if contains(h.groups, "edge")]) == 1
    error_message = "Exactly one host must be in the group edge: it runs the tunnel connector."
  }

  validation {
    condition     = length([for h in values(var.hosts) : h if contains(h.groups, "fxserver")]) <= 1
    error_message = "At most one host can be in the group fxserver: lab-tx points at one host."
  }

  validation {
    condition     = alltrue([for h in values(var.hosts) : h.protect if contains(h.groups, "db")])
    error_message = "Every host in the group db must have protect = true, so that its data disk cannot be deleted by a destroy."
  }

  validation {
    condition = (
      alltrue([for h in values(var.hosts) : h.vm_id >= 110 && h.vm_id <= 119]) &&
      length(distinct([for h in values(var.hosts) : h.vm_id])) == length(var.hosts)
    )
    error_message = "Each host needs its own VM ID from 110 to 119."
  }

  validation {
    condition     = length(distinct([for h in values(var.hosts) : split("/", h.ipv4_cidr)[0]])) == length(var.hosts)
    error_message = "Each host needs its own IPv4 address."
  }
}
