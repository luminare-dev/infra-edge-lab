output "id" {
  description = "Resource ID of the virtual machine."
  value       = proxmox_virtual_environment_vm.this.id
}

output "vm_id" {
  description = "Proxmox VE VM ID."
  value       = proxmox_virtual_environment_vm.this.vm_id
}

output "name" {
  description = "Name of the virtual machine."
  value       = proxmox_virtual_environment_vm.this.name
}

output "ipv4" {
  description = "Static IPv4 address of the virtual machine, without the prefix length."
  value       = split("/", var.ipv4_cidr)[0]
}

output "protection" {
  description = "Whether the Proxmox VE protection flag is set on the virtual machine."
  value       = proxmox_virtual_environment_vm.this.protection
}
