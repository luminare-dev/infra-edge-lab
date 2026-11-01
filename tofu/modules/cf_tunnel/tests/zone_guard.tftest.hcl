# Shared-zone guard of the cf_tunnel module. The provider is mocked: no
# credentials and no network, so the tests run on every pull request, forks included. The zone
# and the addresses are documentation values (example.com, 192.0.2.0/24, 203.0.113.0/24).

mock_provider "cloudflare" {}

variables {
  account_id  = "0123456789abcdef0123456789abcdef"
  zone_id     = "fedcba9876543210fedcba9876543210"
  zone        = "example.com"
  env         = "lab"
  tunnel_name = "lab-edge"
  dns_names   = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi"]
  ingress = [
    { hostname = "lab-demo.example.com", service = "http://127.0.0.1:8080" },
    { hostname = "lab-status.example.com", service = "http://127.0.0.1:3001" },
    {
      hostname = "lab-tx.example.com"
      service  = "http://192.0.2.13:40120"
      origin_request = {
        access = { team_name = "example-team", aud_tag = ["aud-lab-tx"] }
      }
    },
    {
      hostname = "lab-pve.example.com"
      service  = "https://192.0.2.2:8006"
      origin_request = {
        no_tls_verify = true
        access        = { team_name = "example-team", aud_tag = ["aud-lab-pve"] }
      }
    },
    {
      hostname = "lab-pveapi.example.com"
      service  = "https://192.0.2.2:8006"
      origin_request = {
        no_tls_verify = true
        access        = { team_name = "example-team", aud_tag = ["aud-lab-pveapi"] }
      }
    },
  ]
}

# --- names that are accepted --------------------------------------------------------------------

run "allows_lab_prefix" {
  command = plan

  assert {
    condition     = length(cloudflare_dns_record.tunnel) == 5
    error_message = "Every lab name should get one record."
  }

  assert {
    condition = alltrue([
      for r in cloudflare_dns_record.tunnel : startswith(r.name, "lab-") && endswith(r.name, ".example.com")
    ])
    error_message = "Every record in lab should be lab-*.<zone>."
  }

  assert {
    condition     = length(cloudflare_dns_record.address) == 0
    error_message = "No DNS-only record should exist outside showcase."
  }
}

run "allows_demo_prefix" {
  command = plan

  variables {
    env         = "demo"
    tunnel_name = "demo-e2e"
    dns_names   = ["demo-web", "demo-tx", "demo-ssh"]
    ingress = [
      { hostname = "demo-web.example.com", service = "http://127.0.0.1:80" },
      { hostname = "demo-tx.example.com", service = "http://localhost:40120" },
      { hostname = "demo-ssh.example.com", service = "ssh://localhost:22" },
    ]
  }

  assert {
    condition = (
      length(cloudflare_dns_record.tunnel) == 3 &&
      alltrue([for r in cloudflare_dns_record.tunnel : startswith(r.name, "demo-") && endswith(r.name, ".example.com")])
    )
    error_message = "Every record in demo should be demo-*.<zone>."
  }

  assert {
    condition     = alltrue([for r in cloudflare_dns_record.tunnel : r.comment == "managed-by-tofu env=demo"])
    error_message = "Every record in demo should carry the demo comment tag."
  }
}

run "allows_showcase_names_and_play" {
  command = plan

  variables {
    env         = "showcase"
    tunnel_name = "show-edge"
    dns_names   = ["show-web", "show-ssh"]
    ingress = [
      { hostname = "show-web.example.com", service = "http://127.0.0.1:80" },
      { hostname = "show-ssh.example.com", service = "ssh://localhost:22" },
    ]
    address_records = {
      play = { type = "A", content = "203.0.113.10" }
    }
  }

  assert {
    condition     = cloudflare_dns_record.address["play"].name == "play.example.com"
    error_message = "The play record should be created at play.<zone>."
  }

  assert {
    condition     = cloudflare_dns_record.address["play"].type == "A" && cloudflare_dns_record.address["play"].proxied == false
    error_message = "The play record should be a DNS-only A record (a tunnel cannot carry UDP)."
  }

  assert {
    condition     = cloudflare_dns_record.address["play"].comment == "managed-by-tofu env=showcase"
    error_message = "DNS-only records should carry the comment tag as well."
  }

  assert {
    condition = output.records == {
      "show-web.example.com" = { type = "CNAME", proxied = true, comment = "managed-by-tofu env=showcase" }
      "show-ssh.example.com" = { type = "CNAME", proxied = true, comment = "managed-by-tofu env=showcase" }
      "play.example.com"     = { type = "A", proxied = false, comment = "managed-by-tofu env=showcase" }
    }
    error_message = "The records output should list every record with its type, proxy flag and comment."
  }
}

# --- names that are rejected --------------------------------------------------------------------
# Each run adds the name under test to the valid lab names, so that the plan fails on that name
# alone (the ingress rules of the defaults stay valid). A reserved name fails two validations of
# var.dns_names, the prefix rule and the denylist, and expect_failures names the variable only:
# these runs show that each name is rejected, not which of the two rules rejected it. The run
# "denylist_is_a_second_layer" below checks the content of the denylist.

run "rejects_www" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", "www"]
  }

  expect_failures = [var.dns_names]
}

run "rejects_apex_at" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", "@"]
  }

  expect_failures = [var.dns_names]
}

run "rejects_apex_zone_name" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", "example.com"]
  }

  expect_failures = [var.dns_names]
}

run "rejects_empty_name" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", ""]
  }

  expect_failures = [var.dns_names]
}

run "rejects_triage" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", "triage"]
  }

  expect_failures = [var.dns_names]
}

run "rejects_scripts" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", "scripts"]
  }

  expect_failures = [var.dns_names]
}

run "rejects_mx_name" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", "mx"]
  }

  expect_failures = [var.dns_names]
}

run "rejects_dmarc" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", "_dmarc"]
  }

  expect_failures = [var.dns_names]
}

run "rejects_mta_sts" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", "mta-sts"]
  }

  expect_failures = [var.dns_names]
}

run "rejects_mta_sts_policy_record" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", "_mta-sts"]
  }

  expect_failures = [var.dns_names]
}

run "rejects_domainkey_label" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", "lab-s1_domainkey"]
  }

  expect_failures = [var.dns_names]
}

run "rejects_dotted_name" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", "x.lab-demo"]
  }

  expect_failures = [var.dns_names]
}

run "rejects_dotted_name_with_prefix" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", "lab-demo.www"]
  }

  expect_failures = [var.dns_names]
}

run "rejects_upper_case" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", "LAB-demo"]
  }

  expect_failures = [var.dns_names]
}

run "rejects_demo_in_lab" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", "demo-web"]
  }

  expect_failures = [var.dns_names]
}

run "rejects_lab_in_demo" {
  command = plan

  variables {
    env         = "demo"
    tunnel_name = "demo-e2e"
    dns_names   = ["demo-web", "lab-demo"]
    ingress     = [{ hostname = "demo-web.example.com", service = "http://127.0.0.1:80" }]
  }

  expect_failures = [var.dns_names]
}

run "rejects_play_outside_showcase" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", "play"]
  }

  expect_failures = [var.dns_names]
}

run "rejects_repeated_name" {
  command = plan

  variables {
    dns_names = ["lab-demo", "lab-status", "lab-tx", "lab-pve", "lab-pveapi", "lab-demo"]
  }

  expect_failures = [var.dns_names]
}

# The denylist is the second layer behind the prefix rule. It lists the names of the zone's site
# and mail records. No prefix of any environment matches one of them, so the prefix rule alone
# already rejects each of them, and no run can show the denylist rejecting a name on its own; it
# still rejects them if a prefix is ever widened. This run checks what the denylist holds and that
# the prefix rule covers every listed name.
run "denylist_is_a_second_layer" {
  command = plan

  assert {
    condition = alltrue([
      for n in ["", "@", "www", "mx", "scripts", "triage", "_dmarc", "mta-sts", "_mta-sts"] :
      contains(local.reserved_names, n)
    ])
    error_message = "The denylist should hold the apex, www, mx, scripts, triage, _dmarc, mta-sts and _mta-sts."
  }

  assert {
    condition = alltrue(flatten([
      for pattern in values(local.name_patterns) : [
        for n in concat(local.reserved_names, ["lab-s1_domainkey", "x.lab-demo"]) : !can(regex(pattern, n))
      ]
    ]))
    error_message = "No environment prefix should match a reserved, _domainkey or dotted name; if one does, the denylist is the only guard for it and needs a run of its own."
  }
}

# --- record types ---------------------------------------------------------------------------------

run "rejects_mx_record" {
  command = plan

  variables {
    env         = "showcase"
    tunnel_name = "show-edge"
    dns_names   = ["show-web"]
    ingress     = [{ hostname = "show-web.example.com", service = "http://127.0.0.1:80" }]
    # The content would be valid for AAAA, so only the record type is wrong.
    address_records = {
      play = { type = "MX", content = "2001:db8::10" }
    }
  }

  expect_failures = [var.address_records]
}

run "rejects_txt_record" {
  command = plan

  variables {
    env         = "showcase"
    tunnel_name = "show-edge"
    dns_names   = ["show-web"]
    ingress     = [{ hostname = "show-web.example.com", service = "http://127.0.0.1:80" }]
    address_records = {
      show-spf = { type = "TXT", content = "2001:db8::11" }
    }
  }

  expect_failures = [var.address_records]
}

run "rejects_address_records_outside_showcase" {
  command = plan

  variables {
    address_records = {
      lab-game = { type = "A", content = "203.0.113.10" }
    }
  }

  expect_failures = [var.address_records]
}

run "rejects_reserved_address_record" {
  command = plan

  variables {
    env         = "showcase"
    tunnel_name = "show-edge"
    dns_names   = ["show-web"]
    ingress     = [{ hostname = "show-web.example.com", service = "http://127.0.0.1:80" }]
    address_records = {
      www = { type = "A", content = "203.0.113.10" }
    }
  }

  expect_failures = [var.address_records]
}

run "rejects_address_that_does_not_match_the_type" {
  command = plan

  variables {
    env         = "showcase"
    tunnel_name = "show-edge"
    dns_names   = ["show-web"]
    ingress     = [{ hostname = "show-web.example.com", service = "http://127.0.0.1:80" }]
    address_records = {
      play = { type = "AAAA", content = "203.0.113.10" }
    }
  }

  expect_failures = [var.address_records]
}

# --- ingress and tunnel -------------------------------------------------------------------------

run "rejects_ingress_hostname_outside_the_prefix" {
  command = plan

  variables {
    ingress = [{ hostname = "www.example.com", service = "http://127.0.0.1:8080" }]
  }

  expect_failures = [var.ingress]
}

run "rejects_ingress_hostname_in_another_zone" {
  command = plan

  variables {
    ingress = [{ hostname = "lab-demo.example.net", service = "http://127.0.0.1:8080" }]
  }

  expect_failures = [var.ingress]
}

run "rejects_ingress_without_dns_record" {
  command = plan

  variables {
    dns_names = ["lab-demo"]
    ingress = [
      { hostname = "lab-demo.example.com", service = "http://127.0.0.1:8080" },
      { hostname = "lab-other.example.com", service = "http://127.0.0.1:8081" },
    ]
  }

  expect_failures = [var.ingress]
}

run "rejects_unsupported_service" {
  command = plan

  variables {
    dns_names = ["lab-demo"]
    ingress   = [{ hostname = "lab-demo.example.com", service = "ftp://127.0.0.1:21" }]
  }

  expect_failures = [var.ingress]
}

run "rejects_access_that_is_not_required" {
  command = plan

  variables {
    dns_names = ["lab-tx"]
    ingress = [{
      hostname = "lab-tx.example.com"
      service  = "http://192.0.2.13:40120"
      origin_request = {
        access = { required = false, team_name = "example-team", aud_tag = ["aud-lab-tx"] }
      }
    }]
  }

  expect_failures = [var.ingress]
}

run "rejects_tunnel_name_of_another_env" {
  command = plan

  variables {
    tunnel_name = "demo-edge"
  }

  expect_failures = [var.tunnel_name]
}

run "catch_all_last" {
  command = plan

  assert {
    condition     = length(cloudflare_zero_trust_tunnel_cloudflared_config.this.config.ingress) == 6
    error_message = "The module should append exactly one rule to the five given rules."
  }

  assert {
    condition = (
      cloudflare_zero_trust_tunnel_cloudflared_config.this.config.ingress[5].service == "http_status:404" &&
      cloudflare_zero_trust_tunnel_cloudflared_config.this.config.ingress[5].hostname == null &&
      cloudflare_zero_trust_tunnel_cloudflared_config.this.config.ingress[5].path == null
    )
    error_message = "The last ingress rule should be the catch-all http_status:404 without hostname or path."
  }

  assert {
    condition     = cloudflare_zero_trust_tunnel_cloudflared_config.this.config.ingress[0].hostname == "lab-demo.example.com"
    error_message = "The given rules should keep their order in front of the catch-all rule."
  }
}

run "access_protected_rules_require_the_token" {
  command = plan

  assert {
    condition = alltrue([
      for r in cloudflare_zero_trust_tunnel_cloudflared_config.this.config.ingress :
      r.origin_request.access.required == true && length(r.origin_request.access.aud_tag) == 1
      if try(r.origin_request.access, null) != null
    ])
    error_message = "Every Access-protected rule should set access.required = true with the audience tag of its app."
  }

  assert {
    condition = length([
      for r in cloudflare_zero_trust_tunnel_cloudflared_config.this.config.ingress : r
      if try(r.origin_request.access, null) != null
    ]) == 3
    error_message = "lab-tx, lab-pve and lab-pveapi should be protected by Access."
  }
}

run "all_records_cname_proxied" {
  assert {
    condition = alltrue([
      for r in cloudflare_dns_record.tunnel : r.type == "CNAME" && r.proxied == true && r.ttl == 1
    ])
    error_message = "Every tunnel record should be a proxied CNAME with automatic TTL."
  }

  assert {
    condition = alltrue([
      for r in cloudflare_dns_record.tunnel :
      r.content == "${cloudflare_zero_trust_tunnel_cloudflared.this.id}.cfargotunnel.com"
    ])
    error_message = "Every tunnel record should point at <tunnel_id>.cfargotunnel.com."
  }

  assert {
    condition     = output.tunnel_cname == "${cloudflare_zero_trust_tunnel_cloudflared.this.id}.cfargotunnel.com"
    error_message = "The tunnel_cname output should be the target of the records."
  }
}

run "comment_tag" {
  command = plan

  assert {
    condition     = alltrue([for r in cloudflare_dns_record.tunnel : r.comment == "managed-by-tofu env=lab"])
    error_message = "Every record should carry the comment managed-by-tofu env=lab."
  }
}

run "remotely_managed_tunnel" {
  command = plan

  assert {
    condition     = cloudflare_zero_trust_tunnel_cloudflared.this.config_src == "cloudflare"
    error_message = "The tunnel should be remotely managed (config_src = cloudflare)."
  }

  assert {
    condition     = cloudflare_zero_trust_tunnel_cloudflared.this.tunnel_secret == null
    error_message = "A remotely managed tunnel should not set a tunnel_secret."
  }

  assert {
    condition     = cloudflare_zero_trust_tunnel_cloudflared.this.name == "lab-edge"
    error_message = "The tunnel should use the given name."
  }
}
