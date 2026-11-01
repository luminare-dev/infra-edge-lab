# Guard tests of the whole lab environment with mocked providers:
# no hypervisor, no Cloudflare account and no credentials, so they run on every pull request,
# forks included. The zone, the addresses and the key are documentation values.

mock_provider "proxmox" {}

mock_provider "cloudflare" {}

variables {
  zone             = "example.com"
  account_id       = "0123456789abcdef0123456789abcdef"
  zone_id          = "fedcba9876543210fedcba9876543210"
  access_team_name = "example-team"
  allowed_emails   = ["operator@example.com"]
  ssh_keys         = ["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample operator@example.com"]
  # Not a secret: the mocked plan never writes a state.
  state_passphrase = "mocked-plan-passphrase"
}

run "dns_names_have_the_lab_prefix" {
  command = plan

  assert {
    condition = keys(output.dns_records) == [
      "lab-demo.example.com", "lab-pve.example.com", "lab-pveapi.example.com", "lab-status.example.com", "lab-tx.example.com",
    ]
    error_message = "The lab should have exactly lab-demo, lab-pve, lab-pveapi, lab-status and lab-tx."
  }

  assert {
    condition     = alltrue([for name in keys(output.dns_records) : can(regex("^lab-[a-z0-9-]+\\.example\\.com$", name))])
    error_message = "Every DNS name of the lab should be a first-level lab-* name in the zone."
  }
}

run "only_proxied_cnames_with_the_comment" {
  command = plan

  assert {
    condition     = alltrue([for r in values(output.dns_records) : r.type == "CNAME" && r.proxied])
    error_message = "The lab should create proxied CNAME records only: no A, MX or TXT record."
  }

  assert {
    condition     = alltrue([for r in values(output.dns_records) : r.comment == "managed-by-tofu env=lab"])
    error_message = "Every record should carry the comment managed-by-tofu env=lab."
  }
}

run "only_lab_demo_is_public" {
  command = plan

  assert {
    condition     = [for r in output.ingress : r.hostname if !r.access_required] == ["lab-demo.example.com"]
    error_message = "Every hostname except lab-demo should require an Access token at cloudflared."
  }

  assert {
    condition     = sort(keys(output.access_hostnames)) == tolist(["lab-pve", "lab-pveapi", "lab-status", "lab-tx"])
    error_message = "lab-pve, lab-pveapi, lab-status and lab-tx should be Access applications."
  }

  assert {
    condition     = keys(output.service_token_client_ids) == ["lab-pveapi"]
    error_message = "Only lab-pveapi (CI) should use a service token."
  }
}

run "ingress_origins" {
  command = plan

  assert {
    condition = { for r in output.ingress : r.hostname => r.service } == {
      "lab-demo.example.com"   = "http://127.0.0.1:8080"
      "lab-status.example.com" = "http://127.0.0.1:3001"
      "lab-tx.example.com"     = "http://192.0.2.13:40120"
      "lab-pve.example.com"    = "https://192.0.2.2:8006"
      "lab-pveapi.example.com" = "https://192.0.2.2:8006"
    }
    error_message = "The ingress rules should point at the edge host, the game server host and the Proxmox VE API."
  }
}

run "db_is_protected" {
  command = plan

  assert {
    condition     = output.protection == { "db-01" = true, "edge-01" = false, "fx-01" = false }
    error_message = "The database host, and only it, should have the Proxmox VE protection flag."
  }
}

run "hosts_output_shape" {
  command = plan

  assert {
    condition     = keys(output.hosts) == ["db-01", "edge-01", "fx-01"]
    error_message = "The hosts output should be keyed by host name."
  }

  assert {
    condition = output.hosts["edge-01"] == {
      ansible_host = "192.0.2.11"
      connection   = "ansible.builtin.ssh"
      groups       = tolist(["edge", "monitoring"])
      ip           = "192.0.2.11"
    }
    error_message = "Each host should have exactly ansible_host, connection, groups and ip."
  }
}

run "without_a_game_server_host_there_is_no_lab_tx" {
  command = plan

  variables {
    hosts = {
      edge-01 = { vm_id = 110, ipv4_cidr = "192.0.2.11/24", groups = ["edge", "monitoring"] }
      db-01   = { vm_id = 111, ipv4_cidr = "192.0.2.12/24", groups = ["db"], protect = true }
    }
  }

  assert {
    condition     = !contains(keys(output.dns_records), "lab-tx.example.com") && !contains(keys(output.access_hostnames), "lab-tx")
    error_message = "lab-tx should exist only while a host is in the group fxserver."
  }
}

run "rejects_an_unprotected_database_host" {
  command = plan

  variables {
    hosts = {
      edge-01 = { vm_id = 110, ipv4_cidr = "192.0.2.11/24", groups = ["edge"] }
      db-01   = { vm_id = 111, ipv4_cidr = "192.0.2.12/24", groups = ["db"] }
    }
  }

  expect_failures = [var.hosts]
}

run "rejects_two_edge_hosts" {
  command = plan

  variables {
    hosts = {
      edge-01 = { vm_id = 110, ipv4_cidr = "192.0.2.11/24", groups = ["edge"] }
      edge-02 = { vm_id = 111, ipv4_cidr = "192.0.2.12/24", groups = ["edge"] }
    }
  }

  expect_failures = [var.hosts]
}

run "rejects_vm_ids_outside_the_lab_range" {
  command = plan

  variables {
    hosts = {
      edge-01 = { vm_id = 120, ipv4_cidr = "192.0.2.11/24", groups = ["edge"] }
    }
  }

  expect_failures = [var.hosts]
}

run "rejects_a_repeated_address" {
  command = plan

  variables {
    hosts = {
      edge-01 = { vm_id = 110, ipv4_cidr = "192.0.2.11/24", groups = ["edge"] }
      web-01  = { vm_id = 111, ipv4_cidr = "192.0.2.11/24", groups = ["monitoring"] }
    }
  }

  expect_failures = [var.hosts]
}

run "rejects_a_short_state_passphrase" {
  command = plan

  variables {
    state_passphrase = "too-short"
  }

  expect_failures = [var.state_passphrase]
}
