# The hosts map has the same shape in every environment, so the inventory
# renderer does not depend on the substrate.

output "hosts" {
  description = "Hosts for the Ansible inventory, keyed by host name: ansible_host (what Ansible connects to: the container name), connection (the Ansible connection plugin), groups and ip (address in the container network)."
  value = {
    for name, c in docker_container.host : name => {
      ansible_host = c.name
      connection   = "community.docker.docker"
      groups       = var.hosts[name].groups
      ip           = one([for n in c.network_data : n.ip_address if n.network_name == docker_network.this.name])
    }
  }
}

output "network_name" {
  description = "Name of the container network."
  value       = docker_network.this.name
}

output "image_name" {
  description = "Name and tag of the built host image."
  value       = docker_image.host.name
}
