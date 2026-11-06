# Identifiers, names and addresses. The tunnel token is never an output; the
# service token secrets are marked sensitive and are kept in the encrypted state only.

output "hosts" {
  description = "Hosts for the Ansible inventory, keyed by host name, in the shape of every environment: Ansible connects to show-ssh.<zone> through the tunnel (ansible.builtin.ssh)."
  value = {
    for name, server in module.server : name => {
      ansible_host = "show-ssh.${var.zone}"
      connection   = "ansible.builtin.ssh"
      groups       = var.hosts[name].groups
      ip           = server.ipv4
    }
  }
}

output "protection" {
  description = "Protection flags of the server and its primary IP, keyed by host name; all of them are on."
  value       = { for name, server in module.server : name => server.protection }
}

output "tunnel_id" {
  description = "ID of the tunnel; the configure step fetches the tunnel token for it from the API."
  value       = module.tunnel.tunnel_id
}

output "dns_records" {
  description = "DNS records of the environment, keyed by hostname: type, proxied and comment."
  value       = module.tunnel.records
}

output "ingress" {
  description = "Ingress rules of the tunnel in order, without the catch-all rule: hostname, origin service and whether cloudflared requires an Access token."
  value = [
    for r in local.ingress : {
      hostname        = r.hostname
      service         = r.service
      access_required = try(r.origin_request.access.required, false)
    }
  ]
}

output "access_hostnames" {
  description = "Hostnames behind Cloudflare Access, keyed by application (hostname label)."
  value       = module.access.hostnames
}

output "service_token_client_ids" {
  description = "Client ID (header CF-Access-Client-Id) of each service token, keyed by application."
  value       = module.access.service_token_client_ids
}

output "service_token_client_secrets" {
  description = "Client secret (header CF-Access-Client-Secret) of each service token, keyed by application; read it with tofu output -json."
  value       = module.access.service_token_client_secrets
  sensitive   = true
}
