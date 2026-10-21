# hcloud_vm

One Hetzner Cloud server for the `demo` and `showcase` environments, with its SSH key, a
firewall and, optionally, a primary IPv4 address that outlives the server.

- x86-64 server types only (default `cx23`); the Arm types (`cax*`) are rejected, because the
  game server workload does not run on Arm. Locations `nbg1` (default) and `fsn1`, image
  `debian-13`.
- The public firewall allows ping and, with `game_port_open = true` (a game server), the game
  port (default 30120) for TCP and UDP; any other server has no open port. **No public SSH:**
  Ansible reaches the server through the tunnel. The optional CI firewall
  (`enable_ci_ssh_fw`) allows port 22 from listed ranges only, each at most one site's network
  (IPv4 `/24`, IPv6 `/48` or narrower); CI changes its rules at run time, so OpenTofu ignores
  them after creation.
- `protect` sets `delete_protection` and `rebuild_protection` together (the provider requires
  them to be equal) and protects the primary IP; `showcase` must be protected.
- cloud-init creates the `ansible` user with the key (no password, no root login) and installs
  the pinned cloudflared release from its GitHub release, only after its sha256 matches. The
  package repository of cloudflared serves its newest release only, so it cannot install a
  pinned version.
- With `fetch_tunnel_token = true` the module reads the tunnel token (this needs a Cloudflare API
  token with tunnel write permission), writes it to `/etc/cloudflared/token` (mode 0600, owner
  `cloudflared`) at first boot and starts cloudflared with `--token-file`. The token is then in
  the server's user data at Hetzner and in the encrypted state; it is never an output
  ([ADR 0011](../../../docs/adr/0011-remotely-managed-tunnel-and-its-token.md)). Read-only plans
  leave it `false`; `user_data` changes are ignored after creation, so such a plan does not
  replace the server.
- The module adds `ssh_public_key` to the project as an SSH key for the server. Hetzner Cloud
  accepts each public key only once per project, so when `demo` and `showcase` share a project
  and an operator key, the second environment cannot create it again: create the key once
  (`hcloud ssh-key create`) and pass its ID in `ssh_key_ids` to every environment of that
  project. The module then creates no key; cloud-init still installs `ssh_public_key` for the
  admin user.
- Every resource is labelled `env=<env>` and `managed-by=tofu`.

## Usage

```hcl
module "server" {
  source = "../../modules/hcloud_vm"

  name               = "demo-fx-01"
  env                = "demo"
  ssh_public_key     = var.ssh_public_key
  game_port_open     = true
  fetch_tunnel_token = var.fetch_tunnel_token
  account_id         = var.account_id
  tunnel_id          = module.tunnel.tunnel_id
}
```

The hcloud provider reads its token from `HCLOUD_TOKEN`: a token of a project that holds nothing
but this lab.

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string | | Server name; prefix of the key, firewall and IP names. |
| `env` | string | | `demo` or `showcase`. |
| `server_type` | string | `"cx23"` | x86-64 server type; `cax*` is rejected. |
| `image` | string | `"debian-13"` | Operating system image. |
| `location` | string | `"nbg1"` | `nbg1` or `fsn1`. |
| `ssh_public_key` | string | | OpenSSH public key of the admin user. |
| `ssh_key_ids` | list(string) | `null` | IDs of existing SSH keys of the project, used instead of a key the module creates; set it when environments share a project and a key. |
| `admin_user` | string | `"ansible"` | Login user created by cloud-init (not `root`). |
| `protect` | bool | `false` | Delete and rebuild protection (both); required in `showcase`. |
| `labels` | map(string) | `{}` | Extra labels; `env` and `managed-by` are always set. |
| `game_port_open` | bool | `false` | Open `game_port` for TCP and UDP (a game server). |
| `game_port` | number | `30120` | Port opened for TCP and UDP with `game_port_open`. |
| `fetch_tunnel_token` | bool | `false` | Read the tunnel token and start cloudflared at first boot. |
| `account_id` | string | `null` | Cloudflare account ID; needed with `fetch_tunnel_token`. |
| `tunnel_id` | string | `null` | Tunnel ID; needed with `fetch_tunnel_token`. |
| `cloudflared_version` | string | `"2026.9.1"` | cloudflared release installed at first boot. |
| `cloudflared_deb_sha256` | string | the sha256 of `cloudflared-linux-amd64.deb` 2026.9.1 | Checksum the download must match. |
| `enable_ci_ssh_fw` | bool | `false` | Create the CI SSH firewall. |
| `ci_ssh_source_ips` | list(string) | `[]` | Ranges allowed to port 22 through the CI firewall: IPv4 `/24` or narrower, IPv6 `/48` or narrower. |
| `use_primary_ip` | bool | `false` | Keep a primary IPv4 across server replacements (it is billed while it exists). |

## Outputs

| Name | Description |
|---|---|
| `server_id` | ID of the server. |
| `name` | Name of the server. |
| `ipv4`, `ipv6` | Public addresses. |
| `firewall_id` | ID of the public firewall. |
| `public_ports` | What the public firewall lets in: `icmp`, plus `tcp/<game_port>` and `udp/<game_port>` with `game_port_open`. |
| `ci_ssh_firewall_id` | ID of the CI firewall, or null. |
| `primary_ip_id` | ID of the primary IP, or null. |
| `protection` | `delete` and `rebuild` protection of the server, `primary_ip_delete` of the primary IP (null without one). |

## Tests

`tests/hcloud.tftest.hcl` runs against mocked providers: equal protection flags, the firewall
rules (ping, the game port only with `game_port_open`, no public SSH, the CI firewall), the rejected server types, locations
and ranges, the labels, the token data source only with `fetch_tunnel_token`, the token file and
unit in the user data, the pinned and checked cloudflared download, the SSH key (created, or
reused by ID) and the primary IP.
