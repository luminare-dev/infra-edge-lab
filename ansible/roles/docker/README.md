# docker role

Docker Engine from Docker's own APT repository for the hosts that run containers (the monitoring
host with Uptime Kuma, other application hosts), never for a game server. Docker writes its own
packet filter rules for published ports, which bypass the host firewall, so the role makes
loopback the default address of every published port and keeps the firewall of the
`luminare.infra_edge` base role working next to Docker
([ADR 0019](../../../docs/adr/0019-docker-ports-on-loopback-and-a-firewall-that-restarts-docker.md)).

## Requirements

- Managed host: Debian 13 or Ubuntu 24.04 on x86_64 or arm64, reached as root or with
  `become: true`. The role stops before any change on another platform, on a host in
  `docker_forbidden_groups` (default `fxserver`) and when a distribution package that conflicts
  with Docker's packages (`docker.io`, `containerd`, `runc`, `podman-docker`, ...) is installed.
- Network access from the host to `download.docker.com`.
- With the base role's firewall (`/etc/nftables.d` exists): `/etc/nftables.conf` and `nft`.

## Example playbook

```yaml
- name: Container hosts
  hosts: docker_hosts
  become: true
  roles:
    - role: docker
```

## Controls

| Control | How | Checked in Molecule |
|---|---|---|
| Published ports on loopback | `"ip": "127.0.0.1"` in `/etc/docker/daemon.json` (or another loopback or private address from `docker_default_bind_ip`; public addresses are refused); the file is in place before the package starts Docker for the first time | a container started with `-p 8080:80` listens on `127.0.0.1:8080` only and answers there; a documentation address is refused |
| No Docker on game servers | the role stops on hosts in `docker_forbidden_groups` | the role refuses a host in a forbidden group |
| Packages from Docker, signed | deb822 source with `Signed-By: /etc/apt/keyrings/docker.asc`; the key file is checked against a pinned sha256 (fingerprint `9DC8 5822 9FC7 DD38 854A E2D8 8D81 803C 0EBF CD88`) | key checksum and mode, source file |
| Daemon settings checked | `dockerd --validate` on every run; logs to journald, live restore on | `docker info`: logging driver journald, live restore enabled |
| Firewall keeps working | `/etc/nftables.d/60-docker.nft` accepts forwarding for Docker's bridges (outgoing connections, replies, and connections to published ports only), checked with `nft --check` together with `/etc/nftables.conf` | without the drop-in a container cannot reach the outside, with it it can |
| Firewall reload restores Docker's rules | a `docker.service` drop-in with `PartOf=nftables.service` and `After=nftables.service`: the `flush ruleset` of a firewall reload also removes Docker's rules, so systemd restarts Docker, which adds them again; with live restore the containers keep running | after a restart of `nftables.service`, Docker was restarted, its tables are back and the container answers again |
| Docker users | `docker_users` are added to the `docker` group (root-equivalent); users that do not exist are an error, never created | group membership |
| Docker modules work | `python3-requests` for the `community.docker` modules | used by the monitoring role's scenario |

## Variables

The table is generated from [`meta/argument_specs.yml`](meta/argument_specs.yml), which Ansible
also uses to check the variables when the role starts.

<!-- argument-specs:docker:begin -->
| Variable | Type | Default | Description |
|---|---|---|---|
| `docker_forbidden_groups` | list of str | `["fxserver"]` | Inventory groups whose hosts must not run Docker. The role stops before any change on a host in one of them. |
| `docker_apt_repository_url` | str | `https://download.docker.com/linux` | Base URL of Docker's APT repository; the role appends the distribution (debian or ubuntu) for the repository and its signing key. |
| `docker_apt_key_checksum` | str | `sha256:1500c1f56fa9e26b9b8f42452a553675796ade0807cdce11975eb98170b3a570` | Checksum of Docker's repository signing key file (fingerprint 9DC8 5822 9FC7 DD38 854A E2D8 8D81 803C 0EBF CD88); the download fails when the file differs. |
| `docker_packages` | list of str | `["docker-ce", "docker-ce-cli", "containerd.io", "docker-buildx-plugin", "docker-compose-plugin"]` | Packages to install from Docker's repository. |
| `docker_default_bind_ip` | str | `127.0.0.1` | Default address of published container ports ("ip" in /etc/docker/daemon.json). Must be a loopback or private address (127.0.0.0/8 or ::1, the RFC 1918 networks, the RFC 6598 shared address space or an IPv6 unique local address in fc00::/7); the role refuses any other. |
| `docker_daemon_options` | dict | `{"log-driver": "journald", "live-restore": true}` | Settings for /etc/docker/daemon.json. The key "ip" is always replaced by docker_default_bind_ip. The file is checked with "dockerd --validate". |
| `docker_users` | list of str | `[]` | Existing users to add to the docker group. Membership allows root access to the host through the Docker API; keep the list empty unless a user needs it. |
| `docker_restart_with_nftables` | bool | `true` | Add a docker.service drop-in (After= and PartOf=nftables.service), so that a restart of nftables.service, which flushes the whole ruleset, also restarts Docker and its rules. |
| `docker_firewall_manage` | bool | `false` | Write the forward rules (/etc/nftables.d/60-docker.nft) even when /etc/nftables.d does not exist yet. Without it, the file is written only when the directory exists. |
| `docker_firewall_reload` | bool | `true` | Restart nftables.service after the forward rules changed. Molecule sets it to false and restarts the service in its verify step instead. |
<!-- argument-specs:docker:end -->

## Limitations

- Docker runs inside a privileged container in Molecule (storage on tmpfs); the boot order with
  `nftables.service` on a real machine and the forward rules on a host with real interfaces are
  not tested.
- The role installs the newest packages of Docker's `stable` channel on the first run and does
  not upgrade them later; the unattended upgrades of the base role take security updates from the
  distribution only, unless Docker's repository is added to their origins. Pin versions in
  `docker_packages` (`docker-ce=5:...`) when a host must stay on one release.
