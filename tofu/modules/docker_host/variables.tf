# Inputs of the docker_host module: containers with systemd as PID 1 that stand in for the
# virtual machines of the other environments (docs/adr/0010).

variable "env" {
  description = "Environment of the containers: local (no cloud account at all) or demo (the tunnel end-to-end test on a CI runner)."
  type        = string

  validation {
    condition     = contains(["local", "demo"], var.env)
    error_message = "The env must be local or demo; lab and showcase run on virtual machines."
  }
}

variable "hosts" {
  description = "Hosts to create, keyed by host name (the names of the lab, for example edge-01), with the inventory groups of each host."
  type = map(object({
    groups = list(string)
  }))

  validation {
    condition     = length(var.hosts) > 0
    error_message = "The hosts map must hold at least one host."
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
}

variable "platform" {
  description = "Operating system of every host: debian13 (Debian 13) or ubuntu2404 (Ubuntu 24.04). It selects the base image of images/systemd-host/Dockerfile."
  type        = string
  default     = "debian13"

  validation {
    condition     = contains(["debian13", "ubuntu2404"], var.platform)
    error_message = "The platform must be debian13 or ubuntu2404."
  }
}

variable "name_prefix" {
  description = "Prefix of every container, network and image name, so that they never collide with other containers on the same Docker daemon."
  type        = string
  default     = "lab-"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,30}-$", var.name_prefix))
    error_message = "The name_prefix must be lower-case letters, digits and hyphens, start with a letter and end with a hyphen, for example lab-."
  }
}

variable "subnet" {
  description = "IPv4 subnet of the container network, for example 192.0.2.0/24. Null lets the Docker daemon pick a free one."
  type        = string
  default     = null

  validation {
    condition     = var.subnet == null || can(regex("^(\\d{1,3}\\.){3}\\d{1,3}/\\d{1,2}$", var.subnet)) && can(cidrhost(var.subnet, 0))
    error_message = "The subnet must be null or an IPv4 range in CIDR notation, for example 192.0.2.0/24."
  }
}

variable "keep_image" {
  description = "Keep the built image when the hosts are destroyed, so that the next apply starts faster."
  type        = bool
  default     = false
}

variable "wait_timeout" {
  description = "Seconds to wait for systemd to finish booting in each container before the apply fails."
  type        = number
  default     = 120

  validation {
    condition     = var.wait_timeout >= 10 && floor(var.wait_timeout) == var.wait_timeout
    error_message = "The wait_timeout must be a whole number of seconds, at least 10."
  }
}

variable "docker_storage_size" {
  description = "Size limit of each of the two tmpfs mounts (/var/lib/docker, /var/lib/containerd) of the hosts in the groups monitoring and docker_hosts, which run Docker themselves, for example 2g."
  type        = string
  default     = "2g"

  validation {
    condition     = can(regex("^[1-9][0-9]*[kmg]$", var.docker_storage_size))
    error_message = "The docker_storage_size must be a whole number followed by k, m or g, for example 2g."
  }
}
