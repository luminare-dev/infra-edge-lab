# Showcase environment

`tofu/envs/showcase` is the skeleton of one long-lived public game server: a cloud server that is
never thrown away, behind its own tunnel, with a DNS-only name for the players. This page is the
hand-over to whoever brings it up: what the environment creates, which values they set, how they
apply it, and the one name it shares with the rest of the zone. At this version the environment
is validated, tested with mocked providers and planned without network access; it has never been
applied ([README limitations](../README.md#limitations)).

## What it creates

| Part | Value | Where it is set |
|---|---|---|
| Cloud server | one host, default `edge-01` in the groups `edge`, `db` and `fxserver`; type `cx23`, image `debian-13`, location `nbg1` (or `fsn1`); x86-64 only | `hosts`, `server_type`, `image`, `location` in `tofu/envs/showcase/variables.tf` |
| Protection | delete and rebuild protection of the server and delete protection of its primary IPv4 address, always on (a fixed value, not a variable) | `tofu/envs/showcase/main.tf`, [ADR 0014](adr/0014-one-root-module-per-environment.md) |
| Primary IPv4 address | kept when the server is replaced, so that `play` stays valid; billed while it exists, also when unassigned | `hcloud_vm` with `use_primary_ip = true` |
| Cloud firewall | ping; the game port 30120 for TCP and UDP only on a host in `fxserver`; never SSH | `hcloud_vm`, `game_port_open` |
| Tunnel `show-edge` | `show-web` (public, nginx on `127.0.0.1:8080`), `show-ssh` (SSH for machines, Access with a service token), `show-tx` (the game server's admin panel on port 40120, Access login; only with a host in `fxserver`), `show-status` (a status page on another host, Access login; only with `status_origin`) | `tofu/envs/showcase/main.tf`, [tofu/envs/README.md](../tofu/envs/README.md#hostnames) |
| `play` | DNS-only A record of the primary IPv4 address: players connect to `play.<zone>` on port 30120 directly, because a tunnel cannot carry UDP | `address_records` of `cf_tunnel` in `tofu/envs/showcase/main.tf` |

The host gets the same playbook as every environment (`ansible/playbooks/site.yml`): the base
hardening, the tunnel connector and nginx, MariaDB, the game server with txAdmin and the deploy
target, node_exporter and the backups. Ansible reaches it only through `show-ssh`
([configuration](configuration.md#playbooks-and-inventories)).

## Values to set

OpenTofu reads these from `secrets/showcase.enc.env` (the keys of
[secrets/env.example](../secrets/env.example)); the read-only plans of CI read
`secrets/showcase-ci.enc.env`:

| Value | Notes |
|---|---|
| `TF_VAR_zone`, `TF_VAR_account_id`, `TF_VAR_zone_id`, `TF_VAR_access_team_name` | the zone and the Cloudflare account; the zone is never written into the repository |
| `TF_VAR_allowed_emails` | who may log in to `show-tx` and `show-status` (JSON list) |
| `TF_VAR_ssh_public_key`, `SSH_PRIVATE_KEY_B64` | the admin key; the private key only for the `apply` workflow |
| `CLOUDFLARE_API_TOKEN`, `HCLOUD_TOKEN` | a zone-limited Cloudflare token with the permissions that `task preflight ENV=showcase` prints, and a token of a cloud project that holds nothing but this lab |
| `AWS_ENDPOINT_URL_S3`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `TF_VAR_state_passphrase` | the state bucket and the state passphrase ([ADR 0013](adr/0013-encrypted-state-in-r2-with-a-lock-file.md)) |

Variables of the environment with a default: `hosts`, `server_type`, `location`, `image`,
`tunnel_name` (`show-edge`), `status_origin` (`null`: no `show-status`), `allowed_idps`. Change
them in a `*.tfvars` file that stays out of git, or with `TF_VAR_*`.

Ansible needs `ansible/inventories/showcase/group_vars/`, which this version does not have.
Write it after the `demo` values, with every secret in a `*.sops.yaml` file
([ADR 0006](adr/0006-sops-and-age-for-secrets.md)):

- the game server of `luminare.gameserver`: the build and the sha256 of its archive, the license
  key (secret), the mode (`plain` or `txadmin`), the number of slots and, for txAdmin, its own
  values; see that collection's documentation;
- the database and its accounts (`mariadb_databases`, passwords secret);
- the backups: an off-host repository (`restic_backup_repository`), its password and the
  credentials of its backend, all secret ([ADR 0027](adr/0027-restic-for-the-backups-of-every-host.md));
- where the monitoring runs: Prometheus and the status page watch the showcase from another host,
  so `status_origin` and the observability targets point at that host.

## Apply

1. Create the encrypted files and the GitHub environment `showcase` (required reviewer) as in
   the [runbook](runbook.md#procedure-turn-on-the-cloud-workflows).
2. Run `task preflight ENV=showcase`. It refuses when the zone holds a record named `show-*` or
   `play` that this repository did not create (see below).
3. Apply from the workstation with `task up ENV=showcase` (it asks before the apply), or run the
   `apply` workflow with `env = showcase`, which plans, checks the plan against the zone, waits for
   the reviewer, applies exactly that plan, then configures and smoke-tests the host through
   `show-ssh`.
4. Check `play.<zone>` with `dig +short` and a game client on port 30120.

`task destroy` and `task rebuild` refuse `showcase`. Taking it down is a deliberate manual step:
change the fixed protection in `tofu/envs/showcase/main.tf` in a reviewed change, apply it, then
destroy.

## The name `play`

`play` is the only name outside `show-*` that `showcase` may write (the guard pattern
`^(show-[a-z0-9-]+|play)$`, [ADR 0009](adr/0009-guard-rails-for-a-shared-dns-zone.md)), and the
only DNS-only record of this repository. It publishes the server's IPv4 address, which UDP game
traffic needs; the provider's basic DDoS protection is all that stands in front of it.

The same name may be wanted elsewhere in the zone, for example for a web page for players. The
zone can hold only one record set under `play`, so:

- before the first apply, the preflight refuses an existing `play` record that this repository
  did not create; remove that record first, or
- choose another name for the game address: change the label in `address_records` in
  `tofu/envs/showcase/main.tf`, the showcase pattern in `cf_tunnel`, `cf_access_app` and
  `scripts/cloudflare_api.py`, and their tests, together with a new ADR that supersedes the name
  rules of ADR 0009. A page for players then lives under another name, outside this repository.

## Before and after

Until the showcase exists, test on `demo`: it is thrown away after each use, has no `play` record
and is never protected. Once it exists, `drift` plans it every night and opens an issue when it
differs from the code ([ADR 0023](adr/0023-gated-cloud-workflows-with-read-only-plans-and-reviewed-applies.md)).
