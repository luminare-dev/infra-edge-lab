# Identifiers and addresses only. The tunnel token is never an output (docs/adr/0011).

output "server_id" {
  description = "ID of the server."
  value       = hcloud_server.this.id
}

output "name" {
  description = "Name of the server."
  value       = hcloud_server.this.name
}

output "ipv4" {
  description = "Public IPv4 address of the server."
  value       = hcloud_server.this.ipv4_address
}

output "ipv6" {
  description = "Public IPv6 address of the server."
  value       = hcloud_server.this.ipv6_address
}

output "firewall_id" {
  description = "ID of the public firewall (ping, and the game port on a game server)."
  value       = hcloud_firewall.public.id
}

output "public_ports" {
  description = "What the public firewall lets in from the internet: \"icmp\" and, on a game server, \"tcp/<game_port>\" and \"udp/<game_port>\"."
  value       = [for r in hcloud_firewall.public.rule : r.protocol == "icmp" ? "icmp" : "${r.protocol}/${r.port}"]
}

output "ci_ssh_firewall_id" {
  description = "ID of the CI SSH firewall, or null when enable_ci_ssh_fw is false."
  value       = one(hcloud_firewall.ci_ssh[*].id)
}

output "primary_ip_id" {
  description = "ID of the primary IPv4 address, or null when use_primary_ip is false."
  value       = one(hcloud_primary_ip.ipv4[*].id)
}

output "protection" {
  description = "Protection flags: delete and rebuild protection of the server, and delete protection of the primary IP (null without one)."
  value = {
    delete            = hcloud_server.this.delete_protection
    rebuild           = hcloud_server.this.rebuild_protection
    primary_ip_delete = one(hcloud_primary_ip.ipv4[*].delete_protection)
  }
}
