# Guard tests of the whole demo environment with mocked providers:
# no cloud account, no Docker daemon and no credentials, so they run on every pull request,
# forks included. The zone, the addresses and the key are documentation values.

mock_provider "cloudflare" {}

mock_provider "hcloud" {
  # The API uses numeric IDs, and the server refers to its firewalls by number.
  mock_resource "hcloud_firewall" {
    defaults = {
      id = "1001"
    }
  }

  mock_resource "hcloud_ssh_key" {
    defaults = {
      id = "3001"
    }
  }

  mock_resource "hcloud_server" {
    defaults = {
      ipv4_address = "203.0.113.30"
    }
  }
}

mock_provider "docker" {
  mock_resource "docker_container" {
    defaults = {
      network_data = [{
        network_name              = "lab-demo"
        ip_address                = "192.0.2.10"
        ip_prefix_length          = 24
        gateway                   = "192.0.2.1"
        global_ipv6_address       = ""
        global_ipv6_prefix_length = 0
        ipv6_gateway              = ""
        mac_address               = "02:42:c0:00:02:0a"
      }]
    }
  }
}

variables {
  zone             = "example.com"
  account_id       = "0123456789abcdef0123456789abcdef"
  zone_id          = "fedcba9876543210fedcba9876543210"
  access_team_name = "example-team"
  ssh_public_key   = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample operator@example.com"
  # Not a secret: the mocked plan never writes a state.
  state_passphrase = "mocked-plan-passphrase"
}

run "dns_names_have_the_demo_prefix" {
  command = plan

  assert {
    condition     = keys(output.dns_records) == ["demo-ssh.example.com", "demo-web.example.com"]
    error_message = "The demo should have exactly demo-web and demo-ssh without a game server."
  }

  assert {
    condition     = alltrue([for name in keys(output.dns_records) : can(regex("^demo-[a-z0-9-]+\\.example\\.com$", name))])
    error_message = "Every DNS name of the demo should be a first-level demo-* name in the zone."
  }
}

run "only_proxied_cnames_with_the_comment" {
  command = plan

  assert {
    condition     = alltrue([for r in values(output.dns_records) : r.type == "CNAME" && r.proxied])
    error_message = "The demo should create proxied CNAME records only: no A, MX or TXT record."
  }

  assert {
    condition     = alltrue([for r in values(output.dns_records) : r.comment == "managed-by-tofu env=demo"])
    error_message = "Every record should carry the comment managed-by-tofu env=demo."
  }
}

run "every_hostname_is_behind_access" {
  command = plan

  assert {
    condition     = sort(keys(output.access_hostnames)) == tolist(["demo-ssh", "demo-web"])
    error_message = "demo-web and demo-ssh should be Access applications."
  }

  assert {
    condition     = sort(keys(output.service_token_client_ids)) == tolist(["demo-ssh", "demo-web"])
    error_message = "demo-web and demo-ssh should use service tokens (machines)."
  }

  assert {
    condition = { for r in output.ingress : r.hostname => [r.service, r.access_required] } == {
      "demo-web.example.com" = ["http://127.0.0.1:8080", true]
      "demo-ssh.example.com" = ["ssh://localhost:22", false]
    }
    error_message = "demo-web should require an Access token at cloudflared, and demo-ssh should go to the local SSH server."
  }
}

run "hcloud_server_is_never_protected" {
  command = plan

  assert {
    condition     = output.protection == { "edge-01" = { delete = false, rebuild = false, primary_ip_delete = null } }
    error_message = "The demo server must not be protected and must not keep a primary IP."
  }

  assert {
    condition     = output.substrate == "hcloud"
    error_message = "The default substrate should be a cloud server."
  }

  assert {
    condition     = module.server["edge-01"].public_ports == ["icmp"]
    error_message = "A demo server without the group fxserver should open no port to the internet, ping only."
  }
}

run "hcloud_hosts_are_reached_through_the_tunnel" {
  command = plan

  assert {
    condition = output.hosts == {
      "edge-01" = {
        ansible_host = "demo-ssh.example.com"
        connection   = "ansible.builtin.ssh"
        groups       = tolist(["edge", "db"])
        ip           = "203.0.113.30"
      }
    }
    error_message = "On a cloud server, Ansible should connect to demo-ssh.<zone>."
  }
}

run "docker_substrate_uses_containers" {
  command = plan

  variables {
    substrate      = "docker"
    ssh_public_key = null
  }

  assert {
    condition = output.hosts == {
      "edge-01" = {
        ansible_host = "lab-demo-edge-01"
        connection   = "community.docker.docker"
        groups       = tolist(["edge", "db"])
        ip           = "192.0.2.10"
      }
    }
    error_message = "With substrate = docker, the host should be the container lab-demo-edge-01."
  }

  assert {
    condition     = output.protection == {}
    error_message = "With substrate = docker, no cloud server should exist."
  }

  assert {
    condition     = keys(output.dns_records) == ["demo-ssh.example.com", "demo-web.example.com"]
    error_message = "Both substrates should get the same names."
  }
}

run "game_server_adds_demo_tx_for_people" {
  command = plan

  variables {
    hosts          = { edge-01 = { groups = ["edge", "db", "fxserver"] } }
    allowed_emails = ["operator@example.com"]
  }

  assert {
    condition     = contains(keys(output.dns_records), "demo-tx.example.com")
    error_message = "A game server host should get demo-tx."
  }

  assert {
    condition     = contains([for r in output.ingress : r.hostname if r.access_required && r.service == "http://localhost:40120"], "demo-tx.example.com")
    error_message = "demo-tx should point at the local admin panel and require an Access token."
  }

  assert {
    condition     = !contains(keys(output.service_token_client_ids), "demo-tx")
    error_message = "demo-tx is for people (one-time PIN), not for a service token."
  }

  assert {
    condition     = toset(module.server["edge-01"].public_ports) == toset(["icmp", "tcp/30120", "udp/30120"])
    error_message = "A game server host should open the game port for TCP and UDP, which the tunnel cannot carry."
  }
}

run "rejects_another_substrate" {
  command = plan

  variables {
    substrate = "proxmox"
  }

  expect_failures = [var.substrate]
}

run "rejects_a_cloud_server_without_a_key" {
  command = plan

  variables {
    ssh_public_key = null
  }

  expect_failures = [var.ssh_public_key]
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

run "rejects_a_host_without_the_edge_group" {
  command = plan

  variables {
    hosts = { db-01 = { groups = ["db"] } }
  }

  expect_failures = [var.hosts]
}
