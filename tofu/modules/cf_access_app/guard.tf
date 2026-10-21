# Name rules for the shared DNS zone (docs/adr/0009), the same values as in the cf_tunnel
# module: an Access application is only created for a hostname that the tunnel module would
# accept as well. tests/access.tftest.hcl covers the rules here; the denylist is a second layer
# behind the prefix rule and is tested only together with it.

locals {
  name_patterns = {
    lab      = "^lab-[a-z0-9-]+$"
    demo     = "^demo-[a-z0-9-]+$"
    showcase = "^(show-[a-z0-9-]+|play)$"
  }
  name_pattern = lookup(local.name_patterns, var.env, "^$")

  reserved_names = ["", "@", "www", "mx", "scripts", "triage", "_dmarc", "mta-sts", "_mta-sts"]
}
