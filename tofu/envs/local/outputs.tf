# The hosts output has the same shape in every environment, so the inventory
# renderer does not depend on the substrate.

output "hosts" {
  description = "Hosts for the Ansible inventory, keyed by host name: ansible_host (the container name), connection (community.docker.docker), groups and ip."
  value       = module.hosts.hosts
}

output "network_name" {
  description = "Name of the container network."
  value       = module.hosts.network_name
}
