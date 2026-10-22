# Environments

One root module per environment, each with its own state, providers, names and tests, built from
the modules in [../modules](../modules)
([ADR 0014](../../docs/adr/0014-one-root-module-per-environment.md)).

| Environment | Hosts | Modules | DNS names | Protection | State |
|---|---|---|---|---|---|
| `local` | systemd containers on the local Docker daemon: `edge-01`, `db-01`, `fx-01` | `docker_host` | none (no Cloudflare) | none | local file, removed by `task destroy` |
| `lab` | Proxmox VE virtual machines | `pve_vm`, `cf_tunnel`, `cf_access_app` | `lab-*` | every host in the group `db` | R2 |
| `demo` | one cloud server (`substrate = "hcloud"`) or one container (`substrate = "docker"`) | `hcloud_vm` or `docker_host`, `cf_tunnel`, `cf_access_app` | `demo-*` | never | R2 |
| `showcase` | one cloud server with a primary IPv4 address (skeleton) | `hcloud_vm`, `cf_tunnel`, `cf_access_app` | `show-*`, `play` | always | R2 |

Every file of an environment: `versions.tf` (OpenTofu version and providers), `main.tf` (provider
configuration, from environment variables only, and the module calls), `variables.tf`,
`outputs.tf`, `backend.tf`, `encryption.tofu` (the same in every environment) and the committed
`.terraform.lock.hcl`, plus `tests/` with the guard tests.

## Hostnames

The tunnel connector runs on the host in the group `edge`. Hostnames behind Access need a login
(one-time PIN to a listed e-mail address) or a service token (machines); cloudflared also
rejects a request without a valid Access token for each web hostname behind Access.

| Environment | Hostname | Origin | Access |
|---|---|---|---|
| `lab` | `lab-demo` | `http://127.0.0.1:8080` on the edge host | public |
| `lab` | `lab-status` | `http://127.0.0.1:3001` on the edge host | login |
| `lab` | `lab-tx` (only with a host in the group `fxserver`) | port 40120 of that host | login |
| `lab` | `lab-pve` | `https://<pve_ip>:8006` (self-signed, `no_tls_verify`) | login |
| `lab` | `lab-pveapi` | `https://<pve_ip>:8006` | service token (CI) |
| `demo` | `demo-web` | `http://127.0.0.1:8080` on the edge host | service token |
| `demo` | `demo-ssh` | `ssh://localhost:22` | service token (SSH application) |
| `demo` | `demo-tx` (only in the group `fxserver`) | `http://localhost:40120` | login |
| `showcase` | `show-web` | `http://127.0.0.1:8080` on the edge host | public |
| `showcase` | `show-ssh` | `ssh://localhost:22` | service token (SSH application) |
| `showcase` | `show-tx` (only in the group `fxserver`) | `http://localhost:40120` | login |
| `showcase` | `show-status` (only with `status_origin`) | `status_origin` | login |
| `showcase` | `play` | DNS-only A record of the primary IPv4 address (UDP game traffic) | none |

## Working with an environment

```bash
export TF_VAR_state_passphrase="$(openssl rand -base64 32)"   # local only: a new one per run
task init ENV=local
task plan ENV=local
task test ENV=lab                                             # mocked guard tests, no credentials
```

- `task init` and `task plan` run [scripts/tofu_env.sh](../../scripts/tofu_env.sh). When
  `secrets/<env>.enc.env` exists (or the file named by `SECRETS`, for example
  `SECRETS=secrets/lab-ci.enc.env` for a read-only plan), they run under `sops exec-env`, so the
  credentials and the state passphrase exist only in the environment of that one command
  ([secrets/README.md](../../secrets/README.md)).
- `task init ENV=<env> BACKEND=local` keeps the state of `lab`, `demo` or `showcase` in
  `tofu/envs/<env>/terraform.tfstate` instead of R2, still encrypted: it writes the git-ignored
  `backend_override.tf`. `task init ENV=<env>` without `BACKEND=local` removes the file again.
  Both run `tofu init -reconfigure`, which never copies a state between the two backends.
- `task plan` always sets `fetch_tunnel_token = false`: a plan never reads the tunnel token, so
  it works with a read-only Cloudflare token
  ([ADR 0011](../../docs/adr/0011-remotely-managed-tunnel-and-its-token.md)).
- Arguments after `--` go to OpenTofu, for example `task plan ENV=lab -- -out=lab.tfplan`
  (the plan file is encrypted and git-ignored).
- The R2 endpoint and keys come from `AWS_ENDPOINT_URL_S3`, `AWS_ACCESS_KEY_ID` and
  `AWS_SECRET_ACCESS_KEY` ([ADR 0013](../../docs/adr/0013-encrypted-state-in-r2-with-a-lock-file.md)).
  Without `AWS_ENDPOINT_URL_S3` the S3 backend sends its requests to AWS, so `task init` and
  `task plan` refuse to use the remote backend without it.
- `task up ENV=<env>` runs init, apply, inventory, configure and smoke, `task destroy ENV=<env>`
  destroys, and `task rebuild ENV=<env>` does both in a row, each with the same passphrase as the
  init ([runbook](../../docs/runbook.md#procedure-rebuild-an-environment-from-nothing)).
  `task destroy` and `task rebuild` refuse `showcase`. For `lab`, `demo` and `showcase`,
  `task up` runs `task preflight` and `task dns-backup` before the apply and stops if either
  fails ([ADR 0024](../../docs/adr/0024-a-tunnel-test-guarded-by-a-zone-preflight-a-comparison-and-a-sweeper.md)).
  The `local` environment needs a Docker daemon that allows privileged containers; it creates the
  containers `lab-local-edge-01`, `lab-local-db-01` and `lab-local-fx-01` and the network
  `lab-local`, and `task e2e:local` builds, checks and destroys it in one go.
- `task e2e:tunnel` plans and applies a copy of `demo` with `substrate = "docker"`,
  `tunnel_name = "demo-e2e"` and `name_prefix = "lab-e2e-"` (container `lab-e2e-demo-edge-01`,
  network `lab-e2e-demo`), with its state in its own work folder, and always destroys it again
  ([runbook](../../docs/runbook.md#failure-the-tunnel-test-fails)).
- Every plan of `lab`, `demo` and `showcase` shows the Cloudflare provider's warning "Resource
  Destruction Considerations" for the tunnel configuration: the provider has no delete call for
  it. The configuration is stored under its tunnel, and a destroy deletes the tunnel.

## Inputs

Every environment needs `state_passphrase` (`TF_VAR_state_passphrase`, at least 16 characters).

| Input | `local` | `lab` | `demo` | `showcase` | Description |
|---|---|---|---|---|---|
| `zone`, `account_id`, `zone_id` | | required | required | required | DNS zone (never written in the code), Cloudflare account and zone IDs. |
| `access_team_name` | | required | required | required | Team name of the Zero Trust organization. |
| `allowed_emails` | | required | `[]` (needed with `fxserver`) | required | Who may log in to the applications for people. |
| `allowed_idps` | | `[]` | `[]` | `[]` | Identity providers offered at login; empty means all. |
| `tunnel_name` | | `lab-edge` | `demo-edge` | `show-edge` | Name of the tunnel. |
| `hosts` | `edge-01`, `db-01`, `fx-01` | `edge-01`, `db-01` (protected), `fx-01` | `edge-01` (`edge`, `db`) | `edge-01` (`edge`, `db`, `fxserver`) | Hosts and their inventory groups; `lab` also sets `vm_id` (110 to 119), `ipv4_cidr`, sizes and `protect`. |
| `ssh_keys` / `ssh_public_key` | | `ssh_keys` required | `ssh_public_key`, required with `hcloud` | `ssh_public_key` required | Public key(s) of the admin user. |
| `node_name`, `gateway`, `pve_ip` | | `pve`, `192.0.2.1`, `192.0.2.2` | | | Proxmox VE node, default gateway and API address (documentation addresses by default). |
| `substrate` | | | `hcloud` | | `hcloud` or `docker`. |
| `server_type`, `location`, `image` | | | `cx23`, `nbg1`, `debian-13` | `cx23`, `nbg1`, `debian-13` | Cloud server settings. |
| `fetch_tunnel_token` | | | `false` | `false` | Read the tunnel token for the first boot (needs tunnel write permission). |
| `enable_ci_ssh_fw`, `ci_ssh_source_ips` | | | `false`, `[]` | | SSH firewall for one CI runner. |
| `status_origin` | | | | `null` | Origin of `show-status`; null leaves it out. |
| `platform`, `name_prefix` | `debian13`, `lab-` | | `debian13`, `lab-` (with `docker`) | | Container image and name prefix. |
| `subnet`, `keep_image` | `null`, `false` | | | | Container network and image settings. |

## Outputs

| Output | Environments | Description |
|---|---|---|
| `hosts` | all | Inventory hosts keyed by name: `ansible_host`, `connection`, `groups`, `ip`. Containers use `community.docker.docker`; lab hosts their address; cloud servers `<env>-ssh.<zone>` through the tunnel. |
| `network_name` | `local` | Name of the container network. |
| `substrate` | `demo` | `hcloud` or `docker`. |
| `protection` | `lab`, `demo`, `showcase` | Protection flags per host. |
| `tunnel_id` | `lab`, `demo`, `showcase` | ID of the tunnel; the tunnel token is never an output. |
| `dns_records` | `lab`, `demo`, `showcase` | Every record by hostname with `type`, `proxied` and `comment`. |
| `ingress` | `lab`, `demo`, `showcase` | Ingress rules without the catch-all: `hostname`, `service`, `access_required`. |
| `access_hostnames`, `service_token_client_ids` | `lab`, `demo`, `showcase` | Access applications and the client IDs of their service tokens. |
| `service_token_client_secrets` | `lab`, `demo`, `showcase` | Client secrets, sensitive (kept in the encrypted state only). |

## Tests

`tests/env_guard.tftest.hcl` in each environment plans the whole root module against mocked
providers, without credentials: every DNS name has the environment's prefix, the records are
proxied CNAMEs (and the DNS-only A record `play` in `showcase`), never MX or TXT; which hostnames
sit behind Access and which use service tokens; `lab` protects its database host, `demo` is never
protected and `showcase` always is; and the shape of `hosts`. `tests/test_tofu.py` checks the
backend, the encryption file and the lock files. Run one environment with `task test ENV=<env>`,
all of them with `task tofu STEPS=test`.
