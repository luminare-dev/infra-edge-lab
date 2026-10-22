# Inputs of the hcloud_vm module: one cloud server with its SSH key (created here or an existing
# one), firewalls and, optionally, a primary IPv4 address that outlives the server.

variable "name" {
  description = "Server name; also the prefix of the names of the firewalls, the primary IP and the SSH key the module creates."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,62}$", var.name))
    error_message = "The name must start with a letter and hold only lower-case letters, digits and hyphens (at most 63 characters)."
  }
}

variable "env" {
  description = "Environment of the server: demo (thrown away after use) or showcase (long-lived)."
  type        = string

  validation {
    condition     = contains(["demo", "showcase"], var.env)
    error_message = "The env must be demo or showcase; the lab runs on Proxmox VE (pve_vm module)."
  }
}

variable "server_type" {
  description = "Server type. x86-64 types only: the Arm types (cax*) cannot run the game server workload."
  type        = string
  default     = "cx23"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.server_type)) && !startswith(var.server_type, "cax")
    error_message = "The server_type must be an x86-64 type such as cx23; Arm types (cax*) are not supported."
  }
}

variable "image" {
  description = "Operating system image."
  type        = string
  default     = "debian-13"
}

variable "location" {
  description = "Location of the server and of its primary IP: nbg1 or fsn1."
  type        = string
  default     = "nbg1"

  validation {
    condition     = contains(["nbg1", "fsn1"], var.location)
    error_message = "The location must be nbg1 or fsn1."
  }
}

variable "ssh_public_key" {
  description = "Public key of the admin user that Ansible logs in as. cloud-init installs it for that user; unless ssh_key_ids is set, the module also adds it to the project as an SSH key."
  type        = string

  validation {
    condition     = can(regex("^(ssh-ed25519|ecdsa-sha2-nistp(256|384|521)|ssh-rsa) [A-Za-z0-9+/]+={0,3}( [^\\n]*)?$", var.ssh_public_key))
    error_message = "The ssh_public_key must be one OpenSSH public key line (ssh-ed25519, ecdsa-sha2-nistp* or ssh-rsa)."
  }
}

# Hetzner Cloud accepts each public key only once per project, so a second environment in the
# same project with the same key cannot create it again.
variable "ssh_key_ids" {
  description = "IDs of SSH keys that already exist in the project, given to the server instead of a key the module creates from ssh_public_key. Set it when several environments share one project and one operator key: create the key once and pass its ID to each of them. null (the default) creates the key."
  type        = list(string)
  default     = null

  validation {
    condition     = var.ssh_key_ids == null || (length(var.ssh_key_ids) > 0 && alltrue([for id in var.ssh_key_ids : can(regex("^[1-9][0-9]*$", id))]))
    error_message = "The ssh_key_ids must be null or a non-empty list of numeric SSH key IDs, for example [\"1234567\"]."
  }
}

variable "admin_user" {
  description = "Login user that cloud-init creates for Ansible (key login only, sudo without password)."
  type        = string
  default     = "ansible"

  validation {
    condition     = can(regex("^[a-z_][a-z0-9_-]{0,31}$", var.admin_user)) && var.admin_user != "root"
    error_message = "The admin_user must be a valid Linux user name other than root."
  }
}

variable "protect" {
  description = "Turns on delete and rebuild protection of the server together (and delete protection of the primary IP). Required for showcase."
  type        = bool
  default     = false

  validation {
    condition     = var.env != "showcase" || var.protect
    error_message = "A showcase server must be protected: set protect = true."
  }
}

variable "labels" {
  description = "Extra labels for every resource. The module always sets env and managed-by, and they cannot be overridden."
  type        = map(string)
  default     = {}
}

variable "game_port_open" {
  description = "Open game_port to the internet for TCP and UDP: true for a game server, whose game traffic a tunnel cannot carry. false (the default) leaves ping as the only inbound rule."
  type        = bool
  default     = false
}

variable "game_port" {
  description = "Port opened to the internet for TCP and UDP when game_port_open is true."
  type        = number
  default     = 30120

  validation {
    condition     = var.game_port >= 1024 && var.game_port <= 65535 && floor(var.game_port) == var.game_port
    error_message = "The game_port must be a whole number from 1024 to 65535."
  }
}

variable "fetch_tunnel_token" {
  description = "Read the tunnel token at plan time and start cloudflared with it at first boot. It needs a Cloudflare API token with tunnel write permission, so read-only plans leave it false."
  type        = bool
  default     = false

  validation {
    condition     = !var.fetch_tunnel_token || (var.account_id != null && var.tunnel_id != null)
    error_message = "With fetch_tunnel_token = true, account_id and tunnel_id must be set."
  }
}

variable "account_id" {
  description = "Cloudflare account ID of the tunnel; needed only with fetch_tunnel_token = true."
  type        = string
  default     = null
}

variable "tunnel_id" {
  description = "ID of the tunnel the server connects to (output tunnel_id of the cf_tunnel module); needed only with fetch_tunnel_token = true."
  type        = string
  default     = null
}

variable "cloudflared_version" {
  description = "cloudflared release installed at first boot from its GitHub release (.deb for amd64)."
  type        = string
  default     = "2026.9.1"

  validation {
    condition     = can(regex("^[0-9]{4}\\.[0-9]{1,2}\\.[0-9]+$", var.cloudflared_version))
    error_message = "The cloudflared_version must look like 2026.9.1."
  }
}

variable "cloudflared_deb_sha256" {
  description = "sha256 of cloudflared-linux-amd64.deb of cloudflared_version, as listed in the release notes; cloud-init installs the package only if it matches."
  type        = string
  default     = "3be76adc4185d36a0bfb4c2dd8663292f0ed363797f2180333b513b43c81d419"

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.cloudflared_deb_sha256))
    error_message = "The cloudflared_deb_sha256 must be 64 lower-case hexadecimal characters."
  }
}

variable "enable_ci_ssh_fw" {
  description = "Create the extra firewall for SSH from a CI runner, a fallback for the first Ansible run without the tunnel. CI edits its rules at run time, so OpenTofu ignores later rule changes."
  type        = bool
  default     = false
}

variable "ci_ssh_source_ips" {
  description = "Source ranges that the CI firewall lets reach port 22 when it is created, for example [\"198.51.100.7/32\"]. Each range is at most one site's network: IPv4 /24 or narrower, IPv6 /48 or narrower."
  type        = list(string)
  default     = []

  # A prefix length limit instead of a /0 check: two /1 ranges would open SSH to the whole
  # internet as well.
  validation {
    condition = alltrue([
      for c in var.ci_ssh_source_ips :
      can(cidrhost(c, 0)) && try(tonumber(split("/", c)[1]) >= (strcontains(c, ":") ? 48 : 24), false)
    ])
    error_message = "Each ci_ssh_source_ips entry must be a CIDR range of /24 or narrower (IPv4) or /48 or narrower (IPv6); SSH is never open to large parts of the internet."
  }
}

variable "use_primary_ip" {
  description = "Give the server a primary IPv4 address that is kept when the server is replaced (for a stable DNS-only record in showcase). It is billed while it exists, even when unassigned."
  type        = bool
  default     = false
}
