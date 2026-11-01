# One Proxmox VE virtual machine, a full clone of the cloud-init template. The provider talks to
# the API only (token in PROXMOX_VE_API_TOKEN); there is no ssh block in the provider
# configuration, because nothing here uploads snippets or files. Protection uses Proxmox VE's
# own flag, which Terraform understands too.

resource "proxmox_virtual_environment_vm" "this" {
  name        = var.name
  node_name   = var.node_name
  vm_id       = var.vm_id
  pool_id     = var.pool_id
  description = "Managed by OpenTofu (infra-edge-lab, env ${var.env})."
  # Proxmox VE stores tags sorted; sorting here keeps the plan free of order-only changes.
  tags       = sort(distinct(concat(["managed-by-tofu", "env-${var.env}"], var.tags)))
  protection = var.protect
  on_boot    = true
  started    = true

  clone {
    vm_id = var.template_vm_id
    full  = true
  }

  agent {
    enabled = true
  }

  cpu {
    cores = var.cores
    type  = "x86-64-v2-AES"
  }

  memory {
    dedicated = var.memory
  }

  disk {
    datastore_id = var.datastore_id
    interface    = "scsi0"
    size         = var.disk_gb
  }

  network_device {
    bridge = var.bridge
  }

  initialization {
    datastore_id = var.datastore_id

    ip_config {
      ipv4 {
        address = var.ipv4_cidr
        gateway = var.gateway
      }
    }

    user_account {
      username = var.admin_user
      keys     = var.ssh_keys
    }
  }
}
