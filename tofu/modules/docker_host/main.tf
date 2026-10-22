# Containers with systemd as PID 1 on a Docker daemon, standing in for the virtual machines of
# the lab (docs/adr/0010). The image is built from images/systemd-host/Dockerfile of this
# repository, whose base images are pinned by digest. Ansible reaches the containers through the
# Docker API (connection community.docker.docker), so no SSH server and no published port is
# needed.

locals {
  # The build context of the shared host image. A change of the Dockerfile or of the platform
  # gives the image a new tag, so the image and the containers are rebuilt.
  context    = "${path.module}/../../../images/systemd-host"
  image_hash = sha256("${var.platform}\n${filesha256("${local.context}/Dockerfile")}")
  image_name = "${var.name_prefix}systemd-host-${var.platform}:${substr(local.image_hash, 0, 12)}"

  network_name = "${var.name_prefix}${var.env}"

  labels = {
    env        = var.env
    managed-by = "tofu"
  }
}

resource "docker_image" "host" {
  name         = local.image_name
  keep_locally = var.keep_image

  build {
    context    = local.context
    dockerfile = "Dockerfile"
    build_args = {
      BASE = var.platform
    }
    label = local.labels
  }
}

resource "docker_network" "this" {
  name   = local.network_name
  driver = "bridge"

  dynamic "ipam_config" {
    for_each = var.subnet == null ? [] : [var.subnet]

    content {
      subnet = ipam_config.value
    }
  }

  dynamic "labels" {
    for_each = local.labels

    content {
      label = labels.key
      value = labels.value
    }
  }
}

resource "docker_container" "host" {
  for_each = var.hosts

  name     = "${var.name_prefix}${var.env}-${each.key}"
  hostname = each.key
  image    = docker_image.host.image_id

  # What systemd needs in a container: a privileged container in the host's cgroup namespace
  # with the cgroup tree writable, and tmpfs on /run and /run/lock. No port is published.
  privileged    = true
  cgroupns_mode = "host"
  command       = ["/lib/systemd/systemd"]
  stop_signal   = "SIGRTMIN+3"
  tmpfs = {
    "/run"      = "rw"
    "/run/lock" = "rw"
  }

  volumes {
    host_path      = "/sys/fs/cgroup"
    container_path = "/sys/fs/cgroup"
    read_only      = false
  }

  networks_advanced {
    name    = docker_network.this.id
    aliases = [each.key]
  }

  # The apply waits until the image's health check reports that systemd has booted.
  must_run     = true
  restart      = "no"
  wait         = true
  wait_timeout = var.wait_timeout

  dynamic "labels" {
    for_each = merge(local.labels, { "inventory-groups" = join(",", each.value.groups) })

    content {
      label = labels.key
      value = labels.value
    }
  }
}
