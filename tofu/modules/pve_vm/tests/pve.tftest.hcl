# Unit tests of the pve_vm module with a mocked Proxmox VE provider (no hypervisor, no token).
# The addresses are documentation values (192.0.2.0/24).

mock_provider "proxmox" {}

variables {
  name      = "edge-01"
  node_name = "pve"
  vm_id     = 110
  ipv4_cidr = "192.0.2.11/24"
  gateway   = "192.0.2.1"
  ssh_keys  = ["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample operator@example.com"]
}

run "full_clone_of_the_template" {
  command = plan

  assert {
    condition     = proxmox_virtual_environment_vm.this.clone[0].vm_id == 9000 && proxmox_virtual_environment_vm.this.clone[0].full == true
    error_message = "The virtual machine should be a full clone of template 9000."
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.agent[0].enabled == true
    error_message = "The QEMU guest agent should be enabled."
  }
}

run "pool_and_tags" {
  command = plan

  variables {
    tags = ["edge"]
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.pool_id == "lab"
    error_message = "The virtual machine should be in the pool lab (the token's permissions are limited to it)."
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.tags == tolist(["edge", "env-lab", "managed-by-tofu"])
    error_message = "The tags should hold managed-by-tofu, env-<env> and the extra tags, sorted."
  }
}

run "unprotected_by_default" {
  command = plan

  assert {
    condition     = proxmox_virtual_environment_vm.this.protection == false
    error_message = "protect should default to false."
  }
}

run "protection_follows_protect" {
  command = plan

  variables {
    name    = "db-01"
    vm_id   = 111
    protect = true
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this.protection == true
    error_message = "protect = true should set the Proxmox VE protection flag."
  }
}

run "sizes" {
  command = plan

  variables {
    cores   = 2
    memory  = 4096
    disk_gb = 20
  }

  assert {
    condition = (
      proxmox_virtual_environment_vm.this.cpu[0].cores == 2 &&
      proxmox_virtual_environment_vm.this.memory[0].dedicated == 4096 &&
      proxmox_virtual_environment_vm.this.disk[0].size == 20 &&
      proxmox_virtual_environment_vm.this.disk[0].interface == "scsi0"
    )
    error_message = "Cores, memory and the disk size should come from the inputs."
  }
}

run "cloud_init_user_and_address" {
  command = plan

  assert {
    condition = (
      proxmox_virtual_environment_vm.this.initialization[0].user_account[0].username == "ansible" &&
      proxmox_virtual_environment_vm.this.initialization[0].user_account[0].keys == tolist(var.ssh_keys)
    )
    error_message = "cloud-init should create the ansible user with the given keys."
  }

  assert {
    condition = (
      proxmox_virtual_environment_vm.this.initialization[0].ip_config[0].ipv4[0].address == "192.0.2.11/24" &&
      proxmox_virtual_environment_vm.this.initialization[0].ip_config[0].ipv4[0].gateway == "192.0.2.1"
    )
    error_message = "cloud-init should set the static address and the gateway."
  }

  assert {
    condition     = output.ipv4 == "192.0.2.11"
    error_message = "The ipv4 output should be the address without the prefix length."
  }
}

run "rejects_gateway_outside_the_subnet" {
  command = plan

  variables {
    gateway = "198.51.100.1"
  }

  expect_failures = [var.gateway]
}

run "rejects_address_without_prefix" {
  command = plan

  variables {
    ipv4_cidr = "192.0.2.11"
  }

  expect_failures = [var.ipv4_cidr]
}

run "rejects_the_template_id" {
  command = plan

  variables {
    vm_id = 9000
  }

  expect_failures = [var.template_vm_id]
}

run "rejects_reserved_vm_ids" {
  command = plan

  variables {
    vm_id = 99
  }

  expect_failures = [var.vm_id]
}

run "rejects_no_keys" {
  command = plan

  variables {
    ssh_keys = []
  }

  expect_failures = [var.ssh_keys]
}

run "rejects_root_as_admin" {
  command = plan

  variables {
    admin_user = "root"
  }

  expect_failures = [var.admin_user]
}
