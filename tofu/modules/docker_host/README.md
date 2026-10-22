# docker_host

Containers with systemd as PID 1 on a Docker daemon, standing in for the virtual machines of
the lab, so that the playbooks can run on a workstation or a CI runner without a hypervisor or
a cloud account ([ADR 0010](../../../docs/adr/0010-systemd-containers-as-a-local-substrate.md)).

- The image is built from [images/systemd-host/Dockerfile](../../../images/systemd-host/Dockerfile)
  of this repository, on Debian 13 (`platform = "debian13"`, default) or Ubuntu 24.04
  (`"ubuntu2404"`); both base images are pinned by digest. A change of the Dockerfile gives the
  image a new tag, so image and containers are rebuilt.
- Each container is privileged, shares the host's cgroup namespace with `/sys/fs/cgroup`
  writable, has tmpfs on `/run` and `/run/lock` and runs `/lib/systemd/systemd`. The apply waits
  until the image's health check reports that systemd has booted.
- Hosts in the groups `monitoring` and `docker_hosts` run Docker Engine themselves (the `docker`
  role), and Docker's overlay storage cannot stack on the container's own overlay root, so they
  also get tmpfs (with `exec`, `docker_storage_size` each) on `/var/lib/docker` and
  `/var/lib/containerd`, as the Molecule scenarios do.
- No port is published. Ansible connects through the Docker API (`community.docker.docker`).
- Container, network and image names start with `name_prefix` (default `lab-`), so they never
  collide with other containers on the same daemon: `lab-local-edge-01`, network `lab-local`.

The module builds a file outside its own folder, so use it from a checkout of this repository: a
relative `source` path, or a Git source of the repository with the `//tofu/modules/docker_host`
subdirectory.

## The hosts output

`hosts` has the shape that every environment returns, whatever runs the hosts, so the inventory
renderer does not depend on the substrate:

```hcl
hosts = {
  "edge-01" = {
    ansible_host = "lab-local-edge-01"         # what Ansible connects to
    connection   = "community.docker.docker"   # the Ansible connection plugin
    groups       = ["edge", "monitoring"]      # inventory groups
    ip           = "192.0.2.10"                # address in the container network
  }
}
```

## Usage

```hcl
module "hosts" {
  source = "../../modules/docker_host"

  env = "local"
  hosts = {
    edge-01 = { groups = ["edge", "monitoring"] }
    db-01   = { groups = ["db"] }
  }
}
```

The docker provider uses the local daemon (`DOCKER_HOST` or the default socket). The daemon must
allow privileged containers.

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `env` | string | | `local` or `demo`. |
| `hosts` | map(object) | | Host name → `{ groups }`; groups from `edge`, `db`, `fxserver`, `monitoring`, `docker_hosts`. |
| `platform` | string | `"debian13"` | `debian13` or `ubuntu2404`. |
| `name_prefix` | string | `"lab-"` | Prefix of every name; ends with a hyphen. |
| `subnet` | string | `null` | IPv4 subnet of the network; null lets Docker pick one. |
| `keep_image` | bool | `false` | Keep the image after destroy. |
| `wait_timeout` | number | `120` | Seconds to wait for systemd to boot. |
| `docker_storage_size` | string | `"2g"` | Size limit of each Docker storage tmpfs of the hosts in `monitoring` and `docker_hosts`. |

## Outputs

| Name | Description |
|---|---|
| `hosts` | Inventory hosts, see above. |
| `network_name` | Name of the container network. |
| `image_name` | Name and tag of the built image. |

## Tests

- `tests/docker_host.tftest.hcl` runs against a mocked provider: the container settings that
  systemd needs, the Docker storage tmpfs of the hosts that run Docker, no published port, names,
  labels, the image build and the shape of `hosts`.
- `integration/systemd_hosts.tftest.hcl` runs against the real Docker daemon: it builds the
  image for both platforms, boots two hosts per platform and destroys everything again (names
  start with `lab-it-`). Run it with `scripts/check_tofu.sh integration`.
