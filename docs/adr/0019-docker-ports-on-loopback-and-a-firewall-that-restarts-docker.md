# 0019. Docker with ports on loopback, and a firewall reload that restarts Docker

- **Status:** accepted
- **Date:** 2026-10-21

## Context

Docker writes its own packet filter rules for its networks and published ports. They take effect
before the host firewall's input rules, so a port published with `-p 8080:80` is reachable from
everywhere even when the firewall drops all other input. The base role of
`luminare.infra_edge` owns `/etc/nftables.conf`: it starts with `flush ruleset` (which also
removes Docker's rules), drops forwarded traffic by default and includes
`/etc/nftables.d/*.nft`, where other roles add accept rules. Game servers must not run Docker at
all.

## Considered options

1. `"ip": "127.0.0.1"` as the daemon's default address of published ports, a drop-in with
   forward accept rules for Docker's bridges, and a `docker.service` drop-in with
   `PartOf=nftables.service`.
2. `"iptables": false` and all container rules written by hand into the host firewall.
3. Rules in Docker's `DOCKER-USER` chain that filter published ports.

## Decision

Chosen option: 1.

- The daemon's default address is loopback (or another loopback or private address); a public
  address is refused. A service is reached through the tunnel or a reverse proxy on the host.
- `/etc/nftables.d/60-docker.nft` accepts forwarding from `docker0` and `br-*`, replies to them,
  and connections that Docker translated to a published port (`ct status dnat`), and nothing
  else. These are forward rules, while the other drop-ins hold input rules, because the base
  ruleset's forward policy drop would cut every container off; the number 60 places the file
  after the input drop-ins (20 to 50). Like every drop-in, it holds accept rules only and is
  checked with `nft --check` together with `/etc/nftables.conf`.
- `PartOf=nftables.service` and `After=nftables.service` make systemd restart Docker whenever the
  firewall is restarted, so Docker adds its rules again; `live-restore` keeps the containers
  running meanwhile. Molecule tests this sequence.
- Hosts in `docker_forbidden_groups` (default `fxserver`) refuse the role.

Option 2 gives up Docker's own network handling and breaks with every new network. Option 3
leaves the default address at `0.0.0.0` and depends on the filter staying correct for each port.

## Consequences

- Good: a container port is never public by accident, and a firewall change on a Docker host no
  longer leaves the containers without network.
- Bad: every restart of `nftables.service` restarts Docker as well (the containers keep running).
- Bad: a container that must be reachable from other hosts needs a private address or a proxy;
  the role offers no public option.
