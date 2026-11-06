# Identifiers, names and addresses. The tunnel token is never an output; the
# service token secrets are marked sensitive and are kept in the encrypted state only.

output "hosts" {
  description = "Hosts for the Ansible inventory, keyed by host name, in the shape of every environment: ansible_host (the static address), connection (ansible.builtin.ssh), groups and ip."
  value = {
    for name, vm in module.vm : name => {
      ansible_host = vm.ipv4
      connection   = "ansible.builtin.ssh"
      groups       = var.hosts[name].groups
      ip           = vm.ipv4
    }
  }
}

output "protection" {
  description = "Whether the Proxmox VE protection flag is set, keyed by host name."
  value       = { for name, vm in module.vm : name => vm.protection }
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
  description = "Client secret (header CF-Access-Client-Secret) of each service token, keyed by application; read it with tofu output -json and keep it in the SOPS file of CI."
  value       = module.access.service_token_client_secrets
  sensitive   = true
}
