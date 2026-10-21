# Unit tests of the docker_host module with a mocked Docker provider: no daemon, no network and
# no credentials, so they run on every pull request. integration/systemd_hosts.tftest.hcl runs
# the same module against a real Docker daemon.

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
  env = "local"
  hosts = {
    edge-01 = { groups = ["edge", "monitoring"] }
    db-01   = { groups = ["db"] }
  }
}

run "containers_can_run_systemd" {
  command = plan

  assert {
    condition = alltrue([
      for c in docker_container.host :
      c.privileged && c.cgroupns_mode == "host" && c.command == tolist(["/lib/systemd/systemd"])
    ])
    error_message = "Every container should be privileged, share the host cgroup namespace and run systemd as PID 1."
  }

  assert {
    condition = alltrue([
      for c in docker_container.host :
      c.tmpfs == tomap({ "/run" = "rw", "/run/lock" = "rw" }) && c.stop_signal == "SIGRTMIN+3"
    ])
    error_message = "Every container should have tmpfs on /run and /run/lock and stop with systemd's signal."
  }

  assert {
    condition = alltrue([
      for c in docker_container.host : anytrue([
        for v in c.volumes : v.host_path == "/sys/fs/cgroup" && v.container_path == "/sys/fs/cgroup" && v.read_only == false
      ])
    ])
    error_message = "Every container should mount the cgroup tree writable."
  }

  assert {
    condition     = alltrue([for c in docker_container.host : length(c.ports) == 0 && c.publish_all_ports != true])
    error_message = "No container may publish a port."
  }

  assert {
    condition     = alltrue([for c in docker_container.host : c.wait && c.must_run])
    error_message = "The apply should wait until systemd has booted in every container."
  }
}

run "names_carry_the_prefix" {
  command = plan

  assert {
    condition     = docker_container.host["edge-01"].name == "lab-local-edge-01" && docker_container.host["edge-01"].hostname == "edge-01"
    error_message = "Containers should be named <prefix><env>-<host> and use the host name as hostname."
  }

  assert {
    condition     = docker_network.this.name == "lab-local"
    error_message = "The network should be named <prefix><env>."
  }

  assert {
    condition     = startswith(docker_image.host.name, "lab-systemd-host-debian13:")
    error_message = "The image should be named <prefix>systemd-host-<platform>:<hash>."
  }
}

run "other_prefix_and_env" {
  command = plan

  variables {
    env         = "demo"
    name_prefix = "lab-e2e-"
  }

  assert {
    condition     = docker_container.host["db-01"].name == "lab-e2e-demo-db-01" && docker_network.this.name == "lab-e2e-demo"
    error_message = "The prefix and the env should be part of every name."
  }
}

run "image_is_built_from_the_repository_dockerfile" {
  command = plan

  assert {
    condition = (
      endswith(one(docker_image.host.build).context, "images/systemd-host") &&
      one(docker_image.host.build).dockerfile == "Dockerfile" &&
      one(docker_image.host.build).build_args == tomap({ BASE = "debian13" })
    )
    error_message = "The image should be built from images/systemd-host/Dockerfile with BASE=debian13."
  }

  assert {
    condition     = docker_image.host.keep_locally == false
    error_message = "The image should be removed with the hosts by default."
  }
}

run "ubuntu_platform" {
  command = plan

  variables {
    platform = "ubuntu2404"
  }

  assert {
    condition     = one(docker_image.host.build).build_args == tomap({ BASE = "ubuntu2404" })
    error_message = "platform = ubuntu2404 should build the Ubuntu 24.04 stage."
  }

  assert {
    condition     = startswith(docker_image.host.name, "lab-systemd-host-ubuntu2404:")
    error_message = "The platform should be part of the image name, so both images can exist side by side."
  }
}

run "labels" {
  command = plan

  assert {
    condition = alltrue([
      for c in docker_container.host :
      contains([for l in c.labels : "${l.label}=${l.value}"], "env=local") &&
      contains([for l in c.labels : "${l.label}=${l.value}"], "managed-by=tofu")
    ])
    error_message = "Every container should carry the env and managed-by labels."
  }

  assert {
    condition     = contains([for l in docker_container.host["edge-01"].labels : "${l.label}=${l.value}"], "inventory-groups=edge,monitoring")
    error_message = "Every container should carry its inventory groups as a label."
  }

  assert {
    condition     = contains([for l in docker_network.this.labels : "${l.label}=${l.value}"], "managed-by=tofu")
    error_message = "The network should carry the managed-by label."
  }
}

run "hosts_output_shape" {
  assert {
    condition     = keys(output.hosts) == ["db-01", "edge-01"]
    error_message = "The hosts output should be keyed by host name."
  }

  assert {
    condition = output.hosts["edge-01"] == {
      ansible_host = "lab-local-edge-01"
      connection   = "community.docker.docker"
      groups       = tolist(["edge", "monitoring"])
      ip           = "192.0.2.10"
    }
    error_message = "Each host should have exactly ansible_host, connection, groups and ip."
  }
}

run "rejects_vm_envs" {
  command = plan

  variables {
    env = "lab"
  }

  expect_failures = [var.env]
}

run "rejects_unknown_groups" {
  command = plan

  variables {
    hosts = { edge-01 = { groups = ["web"] } }
  }

  expect_failures = [var.hosts]
}

run "rejects_hosts_without_groups" {
  command = plan

  variables {
    hosts = { edge-01 = { groups = [] } }
  }

  expect_failures = [var.hosts]
}

run "rejects_unknown_platform" {
  command = plan

  variables {
    platform = "debian12"
  }

  expect_failures = [var.platform]
}

run "rejects_prefix_without_hyphen" {
  command = plan

  variables {
    name_prefix = "lab"
  }

  expect_failures = [var.name_prefix]
}
