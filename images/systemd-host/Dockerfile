# A host with systemd as PID 1 that stands in for a virtual machine: the docker_host module
# (tofu/modules/docker_host) builds it for the environments that run on Docker, and a Molecule
# scenario can build the same file. The build argument BASE selects the operating system:
#   debian13   -> Debian 13 "trixie" (default)
#   ubuntu2404 -> Ubuntu 24.04 "noble"
# Both base images are pinned by digest (pulled and checked 2026-10-21); Dependabot's docker
# ecosystem proposes digest updates (.github/dependabot.yml). The file uses no Jinja syntax, so
# Molecule's template step leaves it unchanged.
ARG BASE=debian13

FROM debian:trixie@sha256:4c25275446ca371766b8b093c696782eabce06263fccacb8d5d813b3dc44b308 AS debian13
FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac AS ubuntu2404

# hadolint ignore=DL3006
FROM ${BASE}

ENV container=docker \
    DEBIAN_FRONTEND=noninteractive

# What a managed host needs before Ansible's first task: systemd, Python with the apt bindings,
# sudo for become, iproute2 for the network facts and CA certificates for HTTPS downloads. Each
# role installs everything else, so a missing package shows up here and not first on a real
# host. Units that need hardware or a console are masked, so that systemd reports "running"
# once it has booted; /etc/machine-id is removed, so each container gets its own.
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
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/machine-id /var/lib/dbus/machine-id \
    && systemctl mask getty.target console-getty.service systemd-firstboot.service \
        systemd-udevd.service systemd-udev-trigger.service systemd-modules-load.service

# Healthy once systemd has finished booting ("degraded" means booted with a failed unit). The
# docker_host module waits for this, so a host that cannot boot fails the apply, not the first
# playbook run.
HEALTHCHECK --interval=2s --timeout=5s --start-period=60s --retries=30 \
    CMD state="$(systemctl is-system-running)"; [ "$state" = running ] || [ "$state" = degraded ]

STOPSIGNAL SIGRTMIN+3
CMD ["/lib/systemd/systemd"]
