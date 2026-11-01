# Name and record-type rules for the shared DNS zone. The zone also holds
# records that this repository must never create or change: the website, mail (MX, SPF, DKIM,
# DMARC, MTA-STS) and other sites. The variable validations in variables.tf and the
# precondition in main.tf use these values; the cf_access_app module has the same name rules,
# and tests/zone_guard.tftest.hcl covers them (the denylist only together with the prefix rule,
# see the comments there).

locals {
  # First-level labels an environment may use. A dotted name (x.lab-demo) is never allowed: it
  # would also fall outside the edge certificate, which covers the apex and one level below it.
  name_patterns = {
    lab      = "^lab-[a-z0-9-]+$"
    demo     = "^demo-[a-z0-9-]+$"
    showcase = "^(show-[a-z0-9-]+|play)$"
  }
  name_pattern = lookup(local.name_patterns, var.env, "^$")

  # Names of other records in the zone: a second layer. None of them matches a prefix above, so
  # the prefix rule rejects them too; this list still rejects them, with its own message, if a
  # prefix is ever widened. The same holds for every label that contains "_domainkey".
  reserved_names = ["", "@", "www", "mx", "scripts", "triage", "_dmarc", "mta-sts", "_mta-sts"]

  # Tunnel names carry the prefix of their environment, like the DNS names.
  tunnel_prefix = lookup({ lab = "lab-", demo = "demo-", showcase = "show-" }, var.env, "-")

  # The only record types this module creates: CNAME to the tunnel and, in showcase only,
  # DNS-only A/AAAA records for traffic a tunnel cannot carry. Never MX, TXT or anything else.
  address_record_types = ["A", "AAAA"]
  address_record_envs  = ["showcase"]
}
