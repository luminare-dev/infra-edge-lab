# A host with systemd as PID 1 that stands in for a virtual machine: the docker_host module
# (tofu/modules/docker_host) builds it for the environments that run on Docker, and the Molecule
# scenarios of the roles in ansible/roles build the same file (.config/molecule/config.yml). The
# build argument BASE selects the operating system:
#   debian13   -> Debian 13 "trixie" (default)
#   ubuntu2404 -> Ubuntu 24.04 "noble"
# Both base images are pinned by digest (pulled and checked 2026-10-21); Dependabot's docker
# ecosystem proposes digest updates (.github/dependabot.yml). The file uses no Jinja syntax, so
# Molecule's template step leaves it unchanged.
ARG BASE=debian13

FROM debian:trixie@sha256:4c25275446ca371766b8b093c696782eabce06263fccacb8d5d813b3dc44b308 AS debian13
FROM ubuntu:25.10@sha256:7cc5e35f6567ee8c66d2abb4aab0fd866669e6207c237c3a8f0947a5c7f17092 AS ubuntu2404

# hadolint ignore=DL3006
FROM ${BASE}

ENV container=docker \
    DEBIAN_FRONTEND=noninteractive

# What a managed host needs before Ansible's first task: systemd, Python with the apt bindings,
# sudo for become, iproute2 for the network facts and CA certificates for HTTPS downloads. Each
# role installs everything else, so a missing package shows up here and not first on a real
# host. Units that need hardware or a console are masked, so that systemd reports "running"
# once it has booted; /etc/machine-id is removed, so each container gets its own. Docker sets up
# the network before systemd starts, so systemd-networkd-wait-online is masked as well: it would
# find no interface to wait for and hold every unit ordered after network-online.target (Docker,
# node_exporter) for two minutes before it fails. The base images' /usr/sbin/policy-rc.d, which
# stops packages from starting their services, is removed: a package installed by a role starts
# its service as it does on a virtual machine. The package lists stay in the image: the roles
# refresh them only when they are older than an hour (apt's cache_valid_time), and apt judges
# that by the time the lists folder changed, so a folder emptied at build time would look fresh
# and leave a freshly built host with no package lists at all.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        iproute2 \
        python3 \
        python3-apt \
        sudo \
        systemd \
        systemd-sysv \
    && apt-get clean \
    && rm -f /etc/machine-id /var/lib/dbus/machine-id /usr/sbin/policy-rc.d \
    && systemctl mask getty.target console-getty.service systemd-firstboot.service \
        systemd-udevd.service systemd-udev-trigger.service systemd-modules-load.service \
        systemd-networkd-wait-online.service

# Healthy once systemd has finished booting ("degraded" means booted with a failed unit). The
# docker_host module waits for this, so a host that cannot boot fails the apply, not the first
# playbook run.
HEALTHCHECK --interval=2s --timeout=5s --start-period=60s --retries=30 \
    CMD state="$(systemctl is-system-running)"; [ "$state" = running ] || [ "$state" = degraded ]

STOPSIGNAL SIGRTMIN+3
CMD ["/lib/systemd/systemd"]
