# Inputs of the local environment: systemd containers on the local Docker daemon, no cloud
# account and no secret (docs/adr/0014). The state passphrase is declared in encryption.tofu.

variable "hosts" {
  description = "Hosts to create, keyed by host name, with the inventory groups of each host (edge, db, fxserver, monitoring, docker_hosts)."
  type = map(object({
    groups = list(string)
  }))
  # The hosts and groups of the lab environment (tofu/envs/lab), so that the playbook runs here
  # as it runs there: the tunnel connector, web server and monitoring on edge-01, the database on
  # db-01 and the game server on fx-01.
  default = {
    edge-01 = { groups = ["edge", "monitoring"] }
    db-01   = { groups = ["db"] }
    fx-01   = { groups = ["fxserver"] }
  }
}

variable "platform" {
  description = "Operating system of every host: debian13 (Debian 13) or ubuntu2404 (Ubuntu 24.04)."
  type        = string
  default     = "debian13"
}

variable "name_prefix" {
  description = "Prefix of every container, network and image name on the Docker daemon."
  type        = string
  default     = "lab-"
}

variable "subnet" {
  description = "IPv4 subnet of the container network, for example 192.0.2.0/24. Null lets the Docker daemon pick a free one."
  type        = string
  default     = null
}

variable "keep_image" {
  description = "Keep the built host image after a destroy, so that the next apply starts faster."
  type        = bool
  default     = false
}
