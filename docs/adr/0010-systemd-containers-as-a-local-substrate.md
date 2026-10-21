# 0010. Systemd containers as a local substrate

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The environment is meant to run on Proxmox VE virtual machines (lab) and cloud servers (demo,
showcase). Neither is available to a contributor's workstation or to a CI runner without
credentials, yet the playbooks should be tested against real hosts on every change, including
fork pull requests.

## Considered options

1. Test only with Molecule, role by role.
2. Containers with systemd as PID 1, created by an OpenTofu module like any other host.
3. Virtual machines on the runner (nested virtualization).

## Decision

Chosen option: 2, the `docker_host` module, with the kreuzwerker/docker provider. It treats the
Docker daemon as one more substrate, so the path from OpenTofu outputs to the inventory and the
playbooks is the same as in the other environments.

- The image is built from `images/systemd-host/Dockerfile`, the image that Molecule scenarios of
  this repository can build as well, on Debian 13 or Ubuntu 24.04. Both base images are pinned
  by digest and updated by Dependabot.
- Containers are privileged, share the host's cgroup namespace and run systemd; a health check
  makes the apply wait until systemd has booted. No port is published.
- Names start with a prefix (default `lab-`), so the containers never collide with others on a
  shared daemon.
- The module's `hosts` output has the shape every environment returns
  (`ansible_host`, `connection`, `groups`, `ip`); for containers `connection` is
  `community.docker.docker` and `ansible_host` is the container name.
- An integration test (`tofu test -test-directory=integration`) builds both images and boots
  real containers on every pull request; the unit tests mock the provider.

## Consequences

- Good: the whole chain can run anywhere Docker allows privileged containers, without secrets.
- Bad: a container is not a virtual machine: the kernel, the firewall, the boot loader and some
  sysctls are the host's. Checks that need a real machine stay listed as limitations.
- Bad: privileged containers are only acceptable on a disposable or dedicated daemon.
