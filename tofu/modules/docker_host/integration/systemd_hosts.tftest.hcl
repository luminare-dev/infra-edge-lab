# Integration test of the docker_host module against a real Docker daemon: it builds the host
# image for both platforms, starts systemd containers and destroys everything again. It needs
# a local Docker daemon that allows privileged containers, and no other credentials. Run it with
#   tofu -chdir=tofu/modules/docker_host test -test-directory=integration
# (scripts/check_tofu.sh integration). Names start with lab-it-, so the test never touches the
# containers of a real environment on the same daemon.

provider "docker" {}

variables {
  env         = "local"
  name_prefix = "lab-it-"
  hosts = {
    edge-01 = { groups = ["edge", "monitoring"] }
    db-01   = { groups = ["db"] }
  }
}

run "boots_debian_hosts" {
  variables {
    platform = "debian13"
  }

  assert {
    condition     = length(output.hosts) == 2
    error_message = "Both hosts should be created."
  }

  assert {
    condition     = alltrue([for c in docker_container.host : c.must_run && c.exit_code == null])
    error_message = "Every container should be running (systemd booted and the health check passed)."
  }

  assert {
    condition     = output.hosts["edge-01"].ansible_host == "lab-it-local-edge-01"
    error_message = "ansible_host should be the container name."
  }

  assert {
    condition     = alltrue([for h in values(output.hosts) : can(cidrhost("${h.ip}/32", 0))])
    error_message = "Every host should have an IPv4 address in the container network."
  }

  assert {
    condition     = output.hosts["db-01"].groups == tolist(["db"]) && output.hosts["db-01"].connection == "community.docker.docker"
    error_message = "The hosts output should carry the groups and the connection plugin."
  }

  assert {
    condition     = startswith(output.image_name, "lab-it-systemd-host-debian13:")
    error_message = "The image should be built for Debian 13."
  }
}

run "boots_ubuntu_hosts" {
  variables {
    platform = "ubuntu2404"
  }

  assert {
    condition     = alltrue([for c in docker_container.host : c.must_run && c.exit_code == null])
    error_message = "Every Ubuntu container should be running (systemd booted and the health check passed)."
  }

  assert {
    condition     = startswith(output.image_name, "lab-it-systemd-host-ubuntu2404:")
    error_message = "The image should be built for Ubuntu 24.04."
  }
}
