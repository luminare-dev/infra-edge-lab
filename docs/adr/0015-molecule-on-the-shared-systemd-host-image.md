# 0015. Molecule on the shared systemd host image

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The roles kept in this repository (`monitoring`, `docker`, `deploy_target`) manage services, so
their tests need hosts with systemd as PID 1, on Debian 13 and Ubuntu 24.04, on every pull
request and without credentials. Two of them run Docker on the host they configure. Several
projects run Molecule on one Docker daemon at the same time, and this repository already builds
a host image for the `docker_host` module
([ADR 0010](0010-systemd-containers-as-a-local-substrate.md)).

## Considered options

1. Molecule with the Docker driver, building `images/systemd-host/Dockerfile` (base images pinned
   by digest) for both platforms.
2. Molecule with prebuilt community images (for example the `docker-*-ansible` images).
3. Molecule with virtual machines (Vagrant or a cloud driver).

## Decision

Chosen option: 1, because the roles are then tested on exactly the image the `local`
environment runs, and every base layer is pinned and updated by Dependabot.

- `.config/molecule/config.yml` holds the driver, both platforms (build argument `BASE`), the
  provisioner and the sequence `dependency, destroy, syntax, create, prepare, converge,
  idempotence, verify, destroy`; each `ansible/roles/<role>/molecule/default/molecule.yml` only
  names its scenario.
- Instances are privileged, share the host cgroup namespace, mount `/sys/fs/cgroup` read-write
  and get tmpfs on `/run` and `/run/lock`. `/var/lib/docker` and `/var/lib/containerd` are tmpfs
  too (with `exec`), because Docker's overlay storage cannot stack on the instance's own overlay
  root; this is what lets the docker and monitoring scenarios run real containers.
- Instance names are `lab-<role>-debian13` and `lab-<role>-ubuntu2404`, so they never clash with
  other roles or projects on a shared daemon.
- The community collections come from the hash-pinned `ansible` package of
  `requirements-test.txt`; the dependency step is disabled and nothing is downloaded from Ansible
  Galaxy ([ADR 0016](0016-collections-from-git-tags-and-one-pinned-bundle.md)).
- The image masks `systemd-networkd-wait-online.service`: in a container the network exists
  before systemd starts, and the unit would otherwise hold every service ordered after
  `network-online.target` (Docker, node_exporter) for two minutes.
- In CI a plan job lists the roles with a scenario, a role × platform matrix runs
  `molecule test --platform-name lab-<role>-<platform>` (45-minute timeout), and an aggregate job
  named `molecule` reports one result. The scenarios run on pull requests, on demand and weekly.

## Consequences

- Good: one image for the substrate and the tests; a new role needs only its scenario.
- Good: the scenarios test what a host really does (SSH logins with restricted keys, published
  container ports, a firewall reload that restarts Docker), not only file contents.
- Bad: containers share the runner's kernel, so the boot order, loaded input firewall rules and
  real network interfaces are not proven; such checks are listed as limitations.
- Bad: the `molecule` check is not one of the required checks of the `main` ruleset, so a failing
  scenario does not block a merge by itself.
