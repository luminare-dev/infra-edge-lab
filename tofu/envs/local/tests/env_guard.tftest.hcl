# Tests of the local environment with a mocked Docker provider: no daemon and no credentials.
# The local environment has no DNS, tunnel or cloud provider at all; tests/test_tofu.py checks
# that its versions.tf requires the Docker provider only.

mock_provider "docker" {
  mock_resource "docker_container" {
    defaults = {
      network_data = [{
        network_name              = "lab-local"
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
  # Not a secret: the mocked plan never writes a state.
  state_passphrase = "mocked-plan-passphrase"
}

run "default_hosts" {
  command = plan

  assert {
    condition = output.hosts == {
      "db-01" = {
        ansible_host = "lab-local-db-01"
        connection   = "community.docker.docker"
        groups       = tolist(["db"])
        ip           = "192.0.2.10"
      }
      "edge-01" = {
        ansible_host = "lab-local-edge-01"
        connection   = "community.docker.docker"
        groups       = tolist(["edge", "monitoring"])
        ip           = "192.0.2.10"
      }
      "fx-01" = {
        ansible_host = "lab-local-fx-01"
        connection   = "community.docker.docker"
        groups       = tolist(["fxserver"])
        ip           = "192.0.2.10"
      }
    }
    error_message = "The local environment should create edge-01, db-01 and fx-01 (the hosts and groups of the lab) as containers named lab-local-<host>."
  }

  assert {
    condition     = output.network_name == "lab-local"
    error_message = "The container network should be lab-local."
  }
}

run "own_hosts_and_platform" {
  command = plan

  variables {
    platform = "ubuntu2404"
    hosts = {
      edge-01 = { groups = ["edge"] }
      db-01   = { groups = ["db"] }
      fx-01   = { groups = ["fxserver"] }
    }
  }

  assert {
    condition     = keys(output.hosts) == ["db-01", "edge-01", "fx-01"]
    error_message = "The hosts map should decide which containers exist."
  }
}

run "rejects_a_short_state_passphrase" {
  command = plan

  variables {
    state_passphrase = "too-short"
  }

  expect_failures = [var.state_passphrase]
}
