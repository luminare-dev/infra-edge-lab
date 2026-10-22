# Inputs of the pve_vm module: one virtual machine cloned from a cloud-init template.

variable "name" {
  description = "Name of the virtual machine, for example edge-01."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,62}$", var.name))
    error_message = "The name must start with a letter and hold only lower-case letters, digits and hyphens (at most 63 characters)."
  }
}

variable "env" {
  description = "Environment of the virtual machine; it becomes the tag env-<env>."
  type        = string
  default     = "lab"

  validation {
    condition     = contains(["lab", "demo", "showcase"], var.env)
    error_message = "The env must be one of lab, demo or showcase."
  }
}

variable "node_name" {
  description = "Proxmox VE node that runs the virtual machine and holds the template."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9-]*$", var.node_name))
    error_message = "The node_name must be a Proxmox VE node name (letters, digits and hyphens)."
  }
}

variable "vm_id" {
  description = "Proxmox VE VM ID; the lab uses 110 to 119."
  type        = number

  validation {
    condition     = var.vm_id >= 100 && var.vm_id <= 999999999 && floor(var.vm_id) == var.vm_id
    error_message = "The vm_id must be a whole number from 100 to 999999999."
  }
}

variable "template_vm_id" {
  description = "VM ID of the cloud-init template to clone (Debian 13 genericcloud with the QEMU guest agent)."
  type        = number
  default     = 9000

  validation {
    condition     = var.template_vm_id != var.vm_id
    error_message = "The vm_id must differ from the template_vm_id."
  }
}

variable "pool_id" {
  description = "Resource pool of the virtual machine; the API token's permissions are limited to this pool."
  type        = string
  default     = "lab"
}

variable "datastore_id" {
  description = "Datastore of the disk and of the cloud-init drive."
  type        = string
  default     = "local-lvm"
}

variable "bridge" {
  description = "Network bridge of the virtual machine's network device."
  type        = string
  default     = "vmbr0"
}

variable "cores" {
  description = "Number of CPU cores."
  type        = number
  default     = 1

  validation {
    condition     = var.cores >= 1 && var.cores <= 16 && floor(var.cores) == var.cores
    error_message = "The cores must be a whole number from 1 to 16."
  }
}

variable "memory" {
  description = "Memory in MiB."
  type        = number
  default     = 2048

  validation {
    condition     = var.memory >= 512 && floor(var.memory) == var.memory
    error_message = "The memory must be a whole number of MiB, at least 512."
  }
}

variable "disk_gb" {
  description = "Size of the system disk in GiB, at least the size of the template image (the Debian genericcloud image is about 3 GiB)."
  type        = number
  default     = 8

  validation {
    condition     = var.disk_gb >= 4 && floor(var.disk_gb) == var.disk_gb
    error_message = "The disk_gb must be a whole number of GiB, at least 4."
  }
}

variable "ipv4_cidr" {
  description = "Static IPv4 address with prefix length, for example 192.0.2.11/24."
  type        = string

  validation {
    condition     = can(regex("^(\\d{1,3}\\.){3}\\d{1,3}/\\d{1,2}$", var.ipv4_cidr)) && can(cidrhost(var.ipv4_cidr, 0))
    error_message = "The ipv4_cidr must be an IPv4 address with a prefix length, for example 192.0.2.11/24."
  }
}

variable "gateway" {
  description = "IPv4 default gateway; it must be in the subnet of ipv4_cidr."
  type        = string

  validation {
    condition = (
      can(regex("^(\\d{1,3}\\.){3}\\d{1,3}$", var.gateway)) &&
      try(cidrhost("${var.gateway}/${split("/", var.ipv4_cidr)[1]}", 0) == cidrhost(var.ipv4_cidr, 0), false)
    )
    error_message = "The gateway must be an IPv4 address in the subnet of ipv4_cidr."
  }
}

variable "admin_user" {
  description = "Login user that cloud-init creates for Ansible."
  type        = string
  default     = "ansible"

  validation {
    condition     = can(regex("^[a-z_][a-z0-9_-]{0,31}$", var.admin_user)) && var.admin_user != "root"
    error_message = "The admin_user must be a valid Linux user name other than root."
  }
}

variable "ssh_keys" {
  description = "Public keys of the admin user."
  type        = list(string)

  validation {
    condition     = length(var.ssh_keys) > 0
    error_message = "At least one SSH public key is needed; the template allows no password login."
  }
}

variable "tags" {
  description = "Extra Proxmox VE tags; managed-by-tofu and env-<env> are always set."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for t in var.tags : can(regex("^[a-z0-9][a-z0-9_-]*$", t))])
    error_message = "Each tag must be lower-case letters, digits, hyphens and underscores."
  }
}

variable "protect" {
  description = "Sets the Proxmox VE protection flag, which blocks removing the virtual machine and its disks."
  type        = bool
  default     = false
}
