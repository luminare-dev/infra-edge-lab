# Unit tests of the hcloud_vm module with mocked providers: no cloud account, no token, no
# network. The key and the addresses are documentation values.

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
}

mock_provider "cloudflare" {
  mock_data "cloudflare_zero_trust_tunnel_cloudflared_token" {
    defaults = {
      token = "mock-tunnel-token"
    }
  }
}

variables {
  name           = "demo-fx-01"
  env            = "demo"
  ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample operator@example.com"
}

run "defaults" {
  command = plan

  assert {
    condition = (
      hcloud_server.this.server_type == "cx23" &&
      hcloud_server.this.image == "debian-13" &&
      hcloud_server.this.location == "nbg1"
    )
    error_message = "The defaults should be a cx23 server with Debian 13 in nbg1."
  }

  assert {
    condition     = hcloud_server.this.delete_protection == false && hcloud_server.this.rebuild_protection == false
    error_message = "A demo server should not be protected by default."
  }

  assert {
    condition     = output.protection == { delete = false, rebuild = false, primary_ip_delete = null }
    error_message = "The protection output should report both server flags off and no primary IP."
  }
}

run "protection_flags_are_equal" {
  command = plan

  variables {
    env     = "showcase"
    name    = "show-fx-01"
    protect = true
  }

  assert {
    condition     = hcloud_server.this.delete_protection == hcloud_server.this.rebuild_protection
    error_message = "delete_protection and rebuild_protection must be equal."
  }

  assert {
    condition     = hcloud_server.this.delete_protection == true
    error_message = "protect = true should turn on delete protection."
  }

  assert {
    condition     = output.protection.delete == true && output.protection.rebuild == true
    error_message = "The protection output should report both server flags."
  }
}

run "showcase_must_be_protected" {
  command = plan

  variables {
    env  = "showcase"
    name = "show-fx-01"
  }

  expect_failures = [var.protect]
}

run "only_ping_by_default" {
  command = plan

  assert {
    condition     = length(hcloud_firewall.public.rule) == 1 && one(hcloud_firewall.public.rule).protocol == "icmp"
    error_message = "Without game_port_open the public firewall should allow ping only: a server that runs no game server opens no port."
  }

  assert {
    condition     = output.public_ports == ["icmp"]
    error_message = "The public_ports output should list ping only."
  }
}

run "game_port_open_for_tcp_and_udp" {
  command = plan

  variables {
    game_port_open = true
  }

  assert {
    condition = alltrue([
      for proto in ["tcp", "udp"] : anytrue([
        for r in hcloud_firewall.public.rule :
        r.direction == "in" && r.protocol == proto && r.port == "30120" && contains(r.source_ips, "0.0.0.0/0") && contains(r.source_ips, "::/0")
      ])
    ])
    error_message = "The public firewall should open 30120 for TCP and UDP from everywhere."
  }

  assert {
    condition     = anytrue([for r in hcloud_firewall.public.rule : r.protocol == "icmp"])
    error_message = "The public firewall should allow ping."
  }

  assert {
    condition     = length(hcloud_firewall.public.rule) == 3
    error_message = "The public firewall should hold exactly the game port (TCP, UDP) and ping."
  }

  assert {
    condition     = toset(output.public_ports) == toset(["tcp/30120", "udp/30120", "icmp"])
    error_message = "The public_ports output should list the game port for TCP and UDP, and ping."
  }
}

run "no_public_ssh" {
  command = plan

  variables {
    game_port_open = true
  }

  assert {
    condition     = alltrue([for r in hcloud_firewall.public.rule : r.protocol != "tcp" || r.port == "30120"])
    error_message = "Every TCP rule of the public firewall should open the game port only, so port 22 is never open."
  }

  assert {
    condition     = length(hcloud_firewall.ci_ssh) == 0
    error_message = "No SSH firewall should exist unless enable_ci_ssh_fw is set."
  }
}

run "ci_ssh_only_from_the_listed_runner" {
  command = plan

  variables {
    enable_ci_ssh_fw  = true
    ci_ssh_source_ips = ["198.51.100.7/32"]
  }

  assert {
    condition = (
      length(hcloud_firewall.ci_ssh[0].rule) == 1 &&
      one(hcloud_firewall.ci_ssh[0].rule).port == "22" &&
      one(hcloud_firewall.ci_ssh[0].rule).source_ips == toset(["198.51.100.7/32"])
    )
    error_message = "The CI firewall should allow SSH from the listed runner only."
  }
}

run "ci_ssh_firewall_starts_empty" {
  command = plan

  variables {
    enable_ci_ssh_fw = true
  }

  assert {
    condition     = length(hcloud_firewall.ci_ssh[0].rule) == 0
    error_message = "Without source ranges the CI firewall should hold no rule until CI adds the runner."
  }
}

run "ci_ssh_allows_one_site_network" {
  command = plan

  variables {
    enable_ci_ssh_fw  = true
    ci_ssh_source_ips = ["198.51.100.0/24", "2001:db8:1::/48"]
  }

  assert {
    condition     = one(hcloud_firewall.ci_ssh[0].rule).source_ips == toset(["198.51.100.0/24", "2001:db8:1::/48"])
    error_message = "The CI firewall should accept an IPv4 /24 and an IPv6 /48."
  }
}

run "rejects_ssh_from_everywhere" {
  command = plan

  variables {
    enable_ci_ssh_fw  = true
    ci_ssh_source_ips = ["0.0.0.0/0"]
  }

  expect_failures = [var.ci_ssh_source_ips]
}

# Two /1 ranges together cover the whole IPv4 or IPv6 internet, so a /1 is rejected like a /0.
run "rejects_ssh_from_half_the_ipv4_internet" {
  command = plan

  variables {
    enable_ci_ssh_fw  = true
    ci_ssh_source_ips = ["0.0.0.0/1"]
  }

  expect_failures = [var.ci_ssh_source_ips]
}

run "rejects_ssh_from_half_the_ipv6_internet" {
  command = plan

  variables {
    enable_ci_ssh_fw  = true
    ci_ssh_source_ips = ["::/1"]
  }

  expect_failures = [var.ci_ssh_source_ips]
}

run "rejects_ipv4_range_wider_than_24" {
  command = plan

  variables {
    enable_ci_ssh_fw  = true
    ci_ssh_source_ips = ["192.0.2.0/23"]
  }

  expect_failures = [var.ci_ssh_source_ips]
}

run "rejects_ipv6_range_wider_than_48" {
  command = plan

  variables {
    enable_ci_ssh_fw  = true
    ci_ssh_source_ips = ["2001:db8::/47"]
  }

  expect_failures = [var.ci_ssh_source_ips]
}

run "rejects_ssh_source_without_prefix_length" {
  command = plan

  variables {
    enable_ci_ssh_fw  = true
    ci_ssh_source_ips = ["198.51.100.7"]
  }

  expect_failures = [var.ci_ssh_source_ips]
}

run "rejects_arm_server_type" {
  command = plan

  variables {
    server_type = "cax11"
  }

  expect_failures = [var.server_type]
}

run "rejects_other_locations" {
  command = plan

  variables {
    location = "hel1"
  }

  expect_failures = [var.location]
}

run "rejects_lab" {
  command = plan

  variables {
    env = "lab"
  }

  expect_failures = [var.env]
}

run "labels" {
  command = plan

  variables {
    labels = { env = "other", role = "fx" }
  }

  assert {
    condition = alltrue([
      for l in [hcloud_server.this.labels, hcloud_firewall.public.labels, hcloud_ssh_key.this[0].labels] :
      l["env"] == "demo" && l["managed-by"] == "tofu" && l["role"] == "fx"
    ])
    error_message = "Every resource should carry env=<env> and managed-by=tofu (not overridable) plus the extra labels."
  }
}

run "no_token_without_the_flag" {
  command = plan

  assert {
    condition     = length(data.cloudflare_zero_trust_tunnel_cloudflared_token.this) == 0
    error_message = "The token data source must not be read when fetch_tunnel_token is false (read-only plans)."
  }

  assert {
    condition     = !contains(keys(yamldecode(trimprefix(hcloud_server.this.user_data, "#cloud-config\n"))), "write_files")
    error_message = "Without the token no token file and no unit should be written."
  }
}

run "token_only_in_first_boot_user_data" {
  variables {
    fetch_tunnel_token = true
    account_id         = "0123456789abcdef0123456789abcdef"
    tunnel_id          = "00000000-0000-4000-8000-000000000000"
  }

  assert {
    condition     = length(data.cloudflare_zero_trust_tunnel_cloudflared_token.this) == 1
    error_message = "The token data source should be read when fetch_tunnel_token is true."
  }

  assert {
    condition = anytrue([
      for f in yamldecode(trimprefix(hcloud_server.this.user_data, "#cloud-config\n")).write_files :
      f.path == "/etc/cloudflared/token" && f.permissions == "0600" && f.owner == "cloudflared:cloudflared" && f.content == "mock-tunnel-token"
    ])
    error_message = "The token should be written to a 0600 file of the cloudflared user."
  }

  assert {
    condition = anytrue([
      for f in yamldecode(trimprefix(hcloud_server.this.user_data, "#cloud-config\n")).write_files :
      f.path == "/etc/systemd/system/cloudflared.service" && strcontains(f.content, "--token-file /etc/cloudflared/token") && !strcontains(f.content, "mock-tunnel-token")
    ])
    error_message = "The unit should read the token from the file, never from its command line."
  }

  assert {
    condition = alltrue([
      for v in [output.server_id, output.name, output.ipv4, output.ipv6, output.firewall_id] : !strcontains(tostring(v), "mock-tunnel-token")
    ])
    error_message = "No output may contain the tunnel token."
  }
}

run "rejects_token_fetch_without_ids" {
  command = plan

  variables {
    fetch_tunnel_token = true
  }

  expect_failures = [var.fetch_tunnel_token]
}

run "cloud_init_allows_keys_only" {
  command = plan

  assert {
    condition = (
      yamldecode(trimprefix(hcloud_server.this.user_data, "#cloud-config\n")).ssh_pwauth == false &&
      yamldecode(trimprefix(hcloud_server.this.user_data, "#cloud-config\n")).disable_root == true
    )
    error_message = "cloud-init should turn off password logins and root login."
  }

  assert {
    condition = anytrue([
      for u in yamldecode(trimprefix(hcloud_server.this.user_data, "#cloud-config\n")).users :
      u.name == "ansible" && u.lock_passwd == true && u.ssh_authorized_keys == [var.ssh_public_key]
    ])
    error_message = "cloud-init should create the ansible user with the key and a locked password."
  }
}

run "creates_the_ssh_key_by_default" {
  command = plan

  assert {
    condition     = length(hcloud_ssh_key.this) == 1 && hcloud_ssh_key.this[0].public_key == var.ssh_public_key
    error_message = "Without ssh_key_ids the module should create one SSH key from ssh_public_key."
  }

  assert {
    condition     = length(hcloud_server.this.ssh_keys) == 1 && contains(hcloud_server.this.ssh_keys, hcloud_ssh_key.this[0].id)
    error_message = "The server should get the SSH key that the module creates."
  }
}

# Hetzner Cloud accepts each public key once per project, so a second environment in the same
# project passes the ID of the existing key instead of creating it again.
run "reuses_existing_ssh_keys" {
  command = plan

  variables {
    ssh_key_ids = ["4242"]
  }

  assert {
    condition     = length(hcloud_ssh_key.this) == 0
    error_message = "With ssh_key_ids the module should create no SSH key."
  }

  assert {
    condition     = length(hcloud_server.this.ssh_keys) == 1 && contains(hcloud_server.this.ssh_keys, "4242")
    error_message = "The server should get the given SSH key IDs."
  }

  assert {
    condition = anytrue([
      for u in yamldecode(trimprefix(hcloud_server.this.user_data, "#cloud-config\n")).users :
      u.name == "ansible" && u.ssh_authorized_keys == [var.ssh_public_key]
    ])
    error_message = "cloud-init should still install ssh_public_key for the admin user."
  }
}

run "rejects_empty_ssh_key_ids" {
  command = plan

  variables {
    ssh_key_ids = []
  }

  expect_failures = [var.ssh_key_ids]
}

run "rejects_ssh_key_names_as_ids" {
  command = plan

  variables {
    ssh_key_ids = ["operator"]
  }

  expect_failures = [var.ssh_key_ids]
}

run "cloudflared_is_pinned_and_checked" {
  command = plan

  assert {
    condition = (
      strcontains(hcloud_server.this.user_data, "releases/download/2026.9.1/cloudflared-linux-amd64.deb") &&
      strcontains(hcloud_server.this.user_data, "3be76adc4185d36a0bfb4c2dd8663292f0ed363797f2180333b513b43c81d419") &&
      strcontains(hcloud_server.this.user_data, "sha256sum -c -")
    )
    error_message = "cloud-init should install the pinned cloudflared release only after its sha256 matches."
  }

  assert {
    condition     = startswith(yamldecode(trimprefix(hcloud_server.this.user_data, "#cloud-config\n")).runcmd[0][2], "set -eu; ")
    error_message = "The install command should stop at the first failure (a wrong checksum must not install)."
  }
}

run "primary_ip_survives_the_server" {
  command = plan

  variables {
    env            = "showcase"
    name           = "show-fx-01"
    protect        = true
    use_primary_ip = true
  }

  assert {
    condition     = hcloud_primary_ip.ipv4[0].auto_delete == false
    error_message = "The primary IP must not be deleted with the server."
  }

  assert {
    condition     = hcloud_primary_ip.ipv4[0].delete_protection == true
    error_message = "The primary IP of a protected server should be protected as well."
  }

  assert {
    condition     = output.protection.primary_ip_delete == true
    error_message = "The protection output should report the delete protection of the primary IP."
  }

  assert {
    condition     = hcloud_primary_ip.ipv4[0].location == hcloud_server.this.location
    error_message = "The primary IP should be in the location of the server."
  }
}

run "no_primary_ip_by_default" {
  command = plan

  assert {
    condition     = length(hcloud_primary_ip.ipv4) == 0
    error_message = "demo should not keep a billed primary IP."
  }
}
