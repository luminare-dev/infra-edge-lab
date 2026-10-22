# Guard tests of the whole showcase environment with mocked providers (docs/adr/0009,
# docs/adr/0014): no cloud account and no credentials, so they run on every pull request, forks
# included. The zone, the addresses and the key are documentation values.

mock_provider "cloudflare" {}

mock_provider "hcloud" {
  # The API uses numeric IDs, and the server refers to its firewalls and primary IP by number.
  mock_resource "hcloud_firewall" {
    defaults = {
      id = "1001"
    }
  }

  mock_resource "hcloud_primary_ip" {
    defaults = {
      id         = 2001
      ip_address = "203.0.113.20"
    }
  }

  mock_resource "hcloud_ssh_key" {
    defaults = {
      id = "3001"
    }
  }

  mock_resource "hcloud_server" {
    defaults = {
      ipv4_address = "203.0.113.20"
    }
  }
}

variables {
  zone             = "example.com"
  account_id       = "0123456789abcdef0123456789abcdef"
  zone_id          = "fedcba9876543210fedcba9876543210"
  access_team_name = "example-team"
  allowed_emails   = ["operator@example.com"]
  ssh_public_key   = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample operator@example.com"
  # Not a secret: the mocked plan never writes a state.
  state_passphrase = "mocked-plan-passphrase"
}

run "everything_is_protected" {
  command = plan

  assert {
    condition     = output.protection == { "edge-01" = { delete = true, rebuild = true, primary_ip_delete = true } }
    error_message = "The showcase server must have delete and rebuild protection, and its primary IP delete protection."
  }
}

run "dns_names_have_the_showcase_prefix" {
  command = plan

  assert {
    condition     = keys(output.dns_records) == ["play.example.com", "show-ssh.example.com", "show-tx.example.com", "show-web.example.com"]
    error_message = "The showcase should have exactly show-web, show-ssh, show-tx and play by default."
  }

  assert {
    condition     = alltrue([for name in keys(output.dns_records) : can(regex("^(show-[a-z0-9-]+|play)\\.example\\.com$", name))])
    error_message = "Every DNS name of the showcase should be a first-level show-* name or play in the zone."
  }
}

run "record_types" {
  command = plan

  assert {
    condition     = alltrue([for name, r in output.dns_records : r.type == "CNAME" && r.proxied if name != "play.example.com"])
    error_message = "Every tunnel name should be a proxied CNAME."
  }

  assert {
    condition     = output.dns_records["play.example.com"] == { type = "A", proxied = false, comment = "managed-by-tofu env=showcase" }
    error_message = "play should be a DNS-only A record: a tunnel cannot carry the game traffic over UDP."
  }

  assert {
    condition     = alltrue([for r in values(output.dns_records) : contains(["CNAME", "A"], r.type) && r.comment == "managed-by-tofu env=showcase"])
    error_message = "The showcase should create no MX, TXT or other record type, and every record should carry the comment."
  }
}

run "access_rules" {
  command = plan

  assert {
    condition     = sort(keys(output.access_hostnames)) == tolist(["show-ssh", "show-tx"])
    error_message = "show-ssh and show-tx should be Access applications by default; show-web is public."
  }

  assert {
    condition     = keys(output.service_token_client_ids) == ["show-ssh"]
    error_message = "Only show-ssh (machines) should use a service token."
  }

  assert {
    condition     = [for r in output.ingress : r.hostname if r.access_required] == ["show-tx.example.com"]
    error_message = "show-tx should require an Access token at cloudflared."
  }
}

run "hosts_are_reached_through_the_tunnel" {
  command = plan

  assert {
    condition = output.hosts == {
      "edge-01" = {
        ansible_host = "show-ssh.example.com"
        connection   = "ansible.builtin.ssh"
        groups       = tolist(["edge", "db", "fxserver"])
        ip           = "203.0.113.20"
      }
    }
    error_message = "Ansible should connect to show-ssh.<zone>."
  }
}

run "game_port_open_on_the_game_server_only" {
  command = plan

  assert {
    condition     = toset(module.server["edge-01"].public_ports) == toset(["icmp", "tcp/30120", "udp/30120"])
    error_message = "The game server host should open the game port for TCP and UDP (play points at it)."
  }
}

run "no_game_port_without_a_game_server" {
  command = plan

  variables {
    hosts = { edge-01 = { groups = ["edge", "db"] } }
  }

  assert {
    condition     = module.server["edge-01"].public_ports == ["icmp"]
    error_message = "A host without the group fxserver should open no port to the internet, ping only."
  }
}

run "status_page_with_an_origin" {
  command = plan

  variables {
    status_origin = "http://192.0.2.50:3001"
  }

  assert {
    condition     = contains(keys(output.dns_records), "show-status.example.com") && contains(keys(output.access_hostnames), "show-status")
    error_message = "With a status_origin, show-status should exist behind Access."
  }

  assert {
    condition     = contains([for r in output.ingress : r.hostname if r.access_required && r.service == "http://192.0.2.50:3001"], "show-status.example.com")
    error_message = "show-status should point at the status_origin and require an Access token."
  }
}

run "rejects_two_hosts" {
  command = plan

  variables {
    hosts = {
      edge-01 = { groups = ["edge"] }
      db-01   = { groups = ["db"] }
    }
  }

  expect_failures = [var.hosts]
}

run "rejects_a_status_origin_that_is_not_web" {
  command = plan

  variables {
    status_origin = "ssh://192.0.2.50:22"
  }

  expect_failures = [var.status_origin]
}
