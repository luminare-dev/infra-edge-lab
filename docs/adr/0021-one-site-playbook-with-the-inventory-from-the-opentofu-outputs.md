# 0021. One site playbook for every environment, with the inventory from the OpenTofu outputs

- **Status:** accepted
- **Date:** 2026-10-22

## Context

OpenTofu creates the hosts of an environment (containers, Proxmox VE virtual machines or cloud
servers); Ansible then has to configure them with the roles of `luminare.infra_edge`,
`luminare.gameserver`, `prometheus.prometheus` and this repository. The environments differ in
their hosts, their secrets and whether they have a tunnel, but they should run the same
configuration, so that a run of `local` on a pull request says something about `lab` and `demo`.

## Considered options

1. One playbook, `ansible/playbooks/site.yml`, that assigns roles to the inventory groups of the
   `hosts` output (`edge`, `db`, `fxserver`, `monitoring`, `docker_hosts`); an inventory per
   environment rendered from that output; the values of each environment in its own `group_vars`.
2. A playbook per environment.
3. A dynamic inventory plugin that reads the OpenTofu state.

## Decision

Chosen option: 1.

- `scripts/render_inventory.py` turns `tofu output -json` into
  `ansible/inventories/<env>/hosts.yml` (git-ignored): each host with `ansible_host`,
  `ansible_connection` and `host_ip`, and every group, also when it is empty. It refuses an output
  of another shape before it writes anything, and it needs no state access and no credentials
  beyond `tofu output`.
- `site.yml` runs, in this order: the base hardening on every host (so the firewall layout with
  `/etc/nftables.d` exists before any drop-in), Docker on `monitoring` and `docker_hosts`,
  node_exporter on every host, the tunnel connector (only when a tunnel token is present) and
  nginx on `edge`, MariaDB on `db`, the game server with txAdmin and the deploy target on
  `fxserver` (one host at a time, stopping at the first failure), Prometheus with the
  observability pack on `monitoring`, and the backups last on every host.
- Prometheus comes from the `prometheus` role of `prometheus.prometheus` (0.30.2, pinned in
  `ansible/requirements.yml`), which `luminare.gameserver.gameserver_observability` adds its jobs
  and rules to. Before that role runs, `site.yml` downloads the archive into the role's cache
  folder and stops unless it matches the sha256 pinned in the inventory (`site_prometheus_sha256`);
  the role then checks it against the release's `sha256sums.txt`.
- `task configure` fetches the tunnel token for the `tunnel_id` output with
  `scripts/tunnel_token.py` inside `sops exec-env` and hands it to this one playbook run only
  ([ADR 0011](0011-remotely-managed-tunnel-and-its-token.md)).
- `playbooks/smoke.yml` checks each service on its own host through the inventory's connection:
  every nginx site answers 200 on loopback, MariaDB answers `SELECT 1`, the game server answers
  `/info.json` with its build, and every Prometheus target is up.
- ansible-lint runs offline with the collection roles mocked (`.ansible-lint`); their own
  repositories lint and test them.

## Consequences

- Good: the same playbook, roles and order run in every environment; an environment differs only
  in its inventory values.
- Good: the inventory does not depend on the substrate; adding a host is a change of the OpenTofu
  `hosts` variable only.
- Bad: only `local` ships its `group_vars` at this version; `lab`, `demo` and `showcase` need
  theirs (with their secrets in `*.sops.yaml` files) before `task configure` can run there, and
  `demo` and `showcase` also need SSH through the tunnel.
- Bad: the observability role needs a Prometheus on the same host, so Prometheus is one more
  collection from Ansible Galaxy, pinned to one version.
