# Identifiers, names and addresses. The tunnel token is never an output (docs/adr/0011); the
# service token secrets are marked sensitive and are kept in the encrypted state only.

output "substrate" {
  description = "What runs the host: hcloud or docker."
  value       = var.substrate
}

output "hosts" {
  description = "Hosts for the Ansible inventory, keyed by host name, in the shape of every environment. On a cloud server Ansible connects to demo-ssh.<zone> through the tunnel (ansible.builtin.ssh); on a container through the Docker API (community.docker.docker)."
  value = merge(
    {
      for name, server in module.server : name => {
        ansible_host = "demo-ssh.${var.zone}"
        connection   = "ansible.builtin.ssh"
        groups       = var.hosts[name].groups
        ip           = server.ipv4
      }
    },
    try(module.containers[0].hosts, {}),
  )
}

output "protection" {
  description = "Protection flags of the cloud server, keyed by host name (empty with substrate = docker); the demo is never protected."
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
