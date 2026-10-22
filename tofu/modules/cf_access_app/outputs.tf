output "aud_tags" {
  description = "Audience tag of each application, keyed by hostname label; the tunnel ingress uses it in origin_request.access.aud_tag."
  value       = { for name, app in cloudflare_zero_trust_access_application.this : name => app.aud }
}

output "app_ids" {
  description = "ID of each application, keyed by hostname label."
  value       = { for name, app in cloudflare_zero_trust_access_application.this : name => app.id }
}

output "hostnames" {
  description = "Fully qualified hostname of each application, keyed by hostname label."
  value       = { for name, app in cloudflare_zero_trust_access_application.this : name => app.domain }
}

output "service_token_client_ids" {
  description = "Client ID (header CF-Access-Client-Id) of each service token, keyed by hostname label."
  value       = { for name, token in cloudflare_zero_trust_access_service_token.this : name => token.client_id }
}

output "service_token_client_secrets" {
  description = "Client secret (header CF-Access-Client-Secret) of each service token, keyed by hostname label. Cloudflare shows it once; it is kept in the encrypted state only."
  value       = { for name, token in cloudflare_zero_trust_access_service_token.this : name => token.client_secret }
  sensitive   = true
}
