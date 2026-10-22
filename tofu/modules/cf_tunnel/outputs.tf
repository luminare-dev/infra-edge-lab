# Identifiers and names only. The tunnel token is deliberately not an output (docs/adr/0011).

output "tunnel_id" {
  description = "ID of the tunnel; the configure step uses it to fetch the tunnel token from the API."
  value       = cloudflare_zero_trust_tunnel_cloudflared.this.id
}

output "tunnel_name" {
  description = "Name of the tunnel."
  value       = cloudflare_zero_trust_tunnel_cloudflared.this.name
}

output "tunnel_cname" {
  description = "Target of the CNAME records: <tunnel_id>.cfargotunnel.com."
  value       = "${cloudflare_zero_trust_tunnel_cloudflared.this.id}.cfargotunnel.com"
}

output "hostnames" {
  description = "Fully qualified hostnames that point at the tunnel, sorted."
  value       = sort([for r in cloudflare_dns_record.tunnel : r.name])
}

output "address_hostnames" {
  description = "Fully qualified hostnames of the DNS-only A and AAAA records (showcase only), sorted."
  value       = sort([for r in cloudflare_dns_record.address : r.name])
}
