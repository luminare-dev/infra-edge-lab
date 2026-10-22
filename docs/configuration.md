# Configuration

The inputs and outputs of the four environments (`local`, `lab`, `demo`, `showcase`) are listed
in [tofu/envs/README.md](../tofu/envs/README.md), those of the OpenTofu modules in each module's
README: [pve_vm](../tofu/modules/pve_vm/README.md),
[hcloud_vm](../tofu/modules/hcloud_vm/README.md),
[cf_tunnel](../tofu/modules/cf_tunnel/README.md),
[cf_access_app](../tofu/modules/cf_access_app/README.md) and
[docker_host](../tofu/modules/docker_host/README.md). The zone is always an input (`zone`), never
a value in the code. An environment reads its inputs from `TF_VAR_*` environment variables (from
its SOPS file) or from a `*.auto.tfvars` file next to it, which git ignores; examples use
`example.com` and the documentation ranges.

## Variables per environment

What each environment needs before `task init`, `task plan` or `task up` can run there. The
defaults, the optional inputs and the outputs are in
[tofu/envs/README.md](../tofu/envs/README.md#inputs).

| Environment | OpenTofu inputs to set (`TF_VAR_<name>`) | Provider and backend credentials | Ansible values | Kept in |
|---|---|---|---|---|
| `local` | `state_passphrase` (`task e2e:local` makes a random one per run) | none | `ansible/inventories/local/group_vars/` (committed; the passwords are generated into `.generated/`) | nothing to keep |
| `lab` | `state_passphrase`, `zone`, `account_id`, `zone_id`, `access_team_name`, `allowed_emails`, `ssh_keys`; a real lab also overrides `hosts`, `node_name`, `gateway` and `pve_ip`, whose defaults are documentation values | `PROXMOX_VE_ENDPOINT`, `PROXMOX_VE_API_TOKEN` ([ADR 0025](adr/0025-proxmox-ve-api-tokens-with-least-privilege.md)), `PROXMOX_VE_API_HEADERS` (CI only, the service token of `lab-pveapi`), `CLOUDFLARE_API_TOKEN`, `AWS_ENDPOINT_URL_S3`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | none at this version: write `group_vars/`, with the secrets in `*.sops.yaml` files, before `task configure` | `secrets/lab.enc.env`; read-only tokens in `secrets/lab-ci.enc.env` |
| `demo` | `state_passphrase`, `zone`, `account_id`, `zone_id`, `access_team_name`; `ssh_public_key` with `substrate = "hcloud"` (the default); `allowed_emails` once a host is in `fxserver` | `CLOUDFLARE_API_TOKEN`, `HCLOUD_TOKEN` (with `hcloud`), `AWS_ENDPOINT_URL_S3`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | `ansible/inventories/demo/group_vars/` (committed; the backup password is generated into `.generated/`) | `secrets/demo.enc.env`; read-only tokens in `secrets/demo-ci.enc.env`; the tunnel test in `secrets/demo-e2e.enc.env` |
| `showcase` | `state_passphrase`, `zone`, `account_id`, `zone_id`, `access_team_name`, `allowed_emails`, `ssh_public_key`; `status_origin` for `show-status` | `CLOUDFLARE_API_TOKEN`, `HCLOUD_TOKEN`, `AWS_ENDPOINT_URL_S3`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | none at this version, as for `lab` | `secrets/showcase.enc.env`; read-only tokens in `secrets/showcase-ci.enc.env` |

`allowed_emails` is a JSON list (`["operator@example.com"]`), `ssh_keys` a JSON list of public key
lines and `ssh_public_key` one public key line. The zone is always an input, never a value in the
code.

## Tasks, checks and tests

The options below change how the tasks, checks and tests run.

| Option | Type | Default | Description |
|---|---|---|---|
| `VENV` (Taskfile variable, `task lint VENV=path`) | path | `.venv` | Python virtual environment that `task venv`, `task lint` and `task test` use. |
| `TEST_VENV` (environment variable) | path | `$RUNNER_TEMP/venv-test` in CI, else `.venv` | Virtual environment into which `scripts/run_tests.sh` installs `requirements-test.txt` before it runs the unit tests. |
| `GITHUB_REPOSITORY` (environment variable) | `owner/name` | the `origin` remote | Repository name for the name check of `scripts/forbidden_words.py`; set it when the clone has no `origin` remote. |
| `STEPS` (Taskfile variable, `task tofu STEPS='fmt test'`) | list of steps | `all` | Steps of `scripts/check_tofu.sh`: `fmt`, `validate`, `tflint`, `iac` (Trivy), `test`, `integration` (needs Docker), `compat`, or `all`. |
| `TF_PLUGIN_CACHE_DIR` (environment variable) | path | unset; `$RUNNER_TEMP/tofu-plugin-cache` in CI | Shared provider cache for `scripts/check_tofu.sh`; the providers are still checked against each lock file. |
| `ENV` (Taskfile variable, `task init ENV=lab`) | `local`, `lab`, `demo` or `showcase` | none; required by `init`, `plan`, `up`, `inventory`, `configure`, `smoke`, `restore-test`, `destroy`, `rebuild`, `preflight` and `dns-backup` | Environment under `tofu/envs/` and `ansible/inventories/` (`task test` without `ENV` runs the unit tests). `task destroy` and `task rebuild` refuse `showcase`; `task preflight` and `task dns-backup` take `lab`, `demo` or `showcase` (for `dns-backup` it selects the credentials only). |
| `BACKUP_NOW` (Taskfile variable, `task restore-test ENV=local BACKUP_NOW=1`) | any value or unset | unset | Takes the database dumps and a backup on every host before the restore test; unset, the test checks the newest nightly backup. |
| `AUTO_APPROVE` (environment variable, `AUTO_APPROVE=1 task up ENV=demo`) | `1` or unset | unset | Applies and destroys `lab`, `demo` or `showcase` without OpenTofu asking first; `local` never asks. |
| `TUNNEL_TOKEN` (environment variable) | string | unset | Token of the tunnel for `task configure` of `lab`, `demo` or `showcase`; when unset, the task fetches it for the `tunnel_id` output with `CLOUDFLARE_API_TOKEN` and `TF_VAR_account_id` from the SOPS file (`scripts/tunnel_token.py`). Always cleared for `local`. |
| `ANSIBLE_COLLECTIONS_PATH` (environment variable) | path | unset: `ansible/collections` (ansible.cfg) | Where the playbooks find the collections. `task e2e:local` installs `ansible/requirements.yml` only when it is unset; set it to a folder with collections installed from local checkouts to test those. |
| `E2E_LOG_DIR` (environment variable) | path | a temporary folder, removed at the end | Folder where `task e2e:local` keeps the output of both playbook runs. |
| `BACKEND` (Taskfile variable, `task init ENV=lab BACKEND=local`) | `remote` or `local` | `remote` | `local` keeps the state of `lab`, `demo` or `showcase` in a local file (still encrypted) through a git-ignored `backend_override.tf`; `remote` removes that file again. |
| `SECRETS` (environment variable) | path | `secrets/<env>.enc.env`; `secrets/demo-e2e.enc.env` for `task e2e:tunnel` | SOPS file that `task init`, `task plan`, `task preflight`, `task dns-backup`, `task sweep:demo` and `task e2e:tunnel` read with `sops exec-env` when it exists, for example `secrets/lab-ci.enc.env` for a read-only plan. Without the file the values come from the caller's environment. |
| `DNS_BACKUP_RECIPIENTS`, `DNS_BACKUP_RECIPIENTS_FILE` (environment variables) | age public keys separated by spaces, or a file of them | unset: the public key of `SOPS_AGE_KEY_FILE` or `~/.config/sops/age/keys.txt` | Who can decrypt the zone copy of `task dns-backup`. With the default the copy is decrypted once to prove that the key reads it. |
| `DNS_BACKUP_DIR` (environment variable) | path | `backups/dns` (git-ignored) | Folder of the zone copies (mode 0700, files 0600). |
| `E2E_TUNNEL_DIR` (environment variable) | path | `infra-edge-lab-e2e-tunnel` in `RUNNER_TEMP` or `TMPDIR` | Work folder of `task e2e:tunnel` (the copy of the environment, its state, logs and the throwaway key); removed at the end. A folder left by an interrupted run blocks the next run until `bash scripts/e2e_tunnel.sh cleanup`. |
| `CLOUDFLARED` (environment variable) | path | unset: the pinned release is downloaded and checked by sha256 | `cloudflared` binary for the SSH check of `task e2e:tunnel` (needed on a control node that is not Linux x86_64). |
| `CLOUD_ENVS_ENABLED` (repository variable) | `true` or unset | unset | Turns on the workflows `plan`, `apply`, `drift` and `e2e-tunnel`; unset, every job of them is skipped ([runbook](runbook.md#procedure-turn-on-the-cloud-workflows)). |
| `TF_VAR_state_passphrase` (environment variable) | string, at least 16 characters | none; required | Passphrase of the state and plan encryption ([ADR 0013](adr/0013-encrypted-state-in-r2-with-a-lock-file.md)); from the SOPS file, or a random one per run for `local`. |
| Arguments after `--` (`task plan ENV=lab -- -out=lab.tfplan`) | OpenTofu or ansible-playbook arguments | none | Passed on to `tofu init` or `tofu plan`, and with `task configure`, `task smoke`, `task restore-test`, `task up` and `task rebuild` to `ansible-playbook` (for example `-- --diff`). |
| `ROLE` (Taskfile variable, `task molecule ROLE=docker`) | `docker`, `monitoring` or `deploy_target` | none; required by `molecule` | Role under `ansible/roles/` whose Molecule scenario `task molecule` runs. |
| `PLATFORM` (Taskfile variable, `task molecule ROLE=docker PLATFORM=debian13`) | `debian13` or `ubuntu2404` | both | Runs the scenario on one platform only, as one CI matrix job does. |

## Playbooks and inventories

`ansible/playbooks/site.yml` configures every environment
([ADR 0021](adr/0021-one-site-playbook-with-the-inventory-from-the-opentofu-outputs.md)); run it
with `task configure ENV=<env>`. Its inventory is `ansible/inventories/<env>/`: `hosts.yml`, which
`task inventory ENV=<env>` writes from the environment's `hosts` output
(`scripts/render_inventory.py`), and the committed `group_vars/`.

| Inventory value | Set by | Description |
|---|---|---|
| groups `edge`, `db`, `fxserver`, `monitoring`, `docker_hosts` | `hosts.yml` (from the `groups` of each host in OpenTofu) | Which roles a host gets: `edge` the tunnel connector and nginx, `db` MariaDB, `fxserver` the game server, txAdmin and the deploy target, `monitoring` Docker with Uptime Kuma, Prometheus and the observability pack, `docker_hosts` Docker. Every host gets the base hardening, node_exporter and the backups. |
| `ansible_host`, `ansible_connection` | `hosts.yml` | What Ansible connects to and how: a container name with `community.docker.docker` in `local`, an address or the SSH hostname with `ansible.builtin.ssh` elsewhere. |
| `host_ip` | `hosts.yml` | The host's address in the environment's network; the `group_vars` of `local` use it for listen addresses and firewall sources between the hosts. |
| `ansible_user`, `ansible_ssh_common_args` | `hosts.yml`, for a cloud server of `demo` or `showcase` only | The automation user `ansible`, and SSH through the tunnel: `cloudflared access ssh --hostname %h` as ProxyCommand to `<env>-ssh` behind Access, with the host key kept in `.generated/known_hosts` next to the inventory (accepted on the first connection, removed by `task destroy`). `task configure` and `task smoke` put the service token of `demo-ssh` or `show-ssh` from the outputs into `TUNNEL_SERVICE_TOKEN_ID` and `TUNNEL_SERVICE_TOKEN_SECRET` for the run; `cloudflared` must be on the PATH. |
| `site_prometheus_sha256` | `group_vars` (monitoring) | sha256 of the linux-amd64 archive of `prometheus_version`. Before the `prometheus` role runs, `site.yml` downloads the archive into `prometheus_local_cache_path` on the control node and stops unless it matches; after the role it checks again that the archive the role unpacked is that file. Empty skips both checks. |
| role variables | `group_vars` | Every variable of the roles below and of the collections' roles. |

The `group_vars` of `local` set up the environment that `task e2e:local` tests: node_exporter on
`host_ip` for the monitoring host, MariaDB on `host_ip` for the game servers, nginx with the
Uptime Kuma page on `127.0.0.1:8081`, the fake game server build in txAdmin mode, txAdmin's port
open to the edge host only, Prometheus 3.15.0 on loopback with node_exporter of every host and
the observability jobs of every game server, and a backup repository in `/srv/restic-repo` on
each host. Their secrets are never in the files: `local_generated_dir`
(`ansible/inventories/local/.generated/`, git-ignored) holds passwords that the password lookup
generates on first use, the throwaway SSH key and the fake build, which
`playbooks/local_prepare.yml` creates. `task destroy ENV=local` deletes the folder.
The `group_vars` of `demo` are those of its one host, a cloud server or the container of
`task e2e:tunnel`: both users of the base role get the key in `TF_VAR_ssh_public_key`, SSH is
admitted from the host itself only (the tunnel connector on the host carries `demo-ssh` to
`ssh://localhost:22`), node_exporter and MariaDB listen on loopback, and the backup repository is
a folder on the host. Its one secret, the backup password, is generated next to the inventory:
in `ansible/inventories/demo/.generated/` (git-ignored), or in the work folder of the tunnel test,
which removes it at the end. `task e2e:tunnel` adds two values of its
own: the nginx site of `demo-web` on `127.0.0.1:8080` in front of its test page, and the marker
of the run (`playbooks/tunnel_e2e_prepare.yml`). `lab` and `showcase` have no `group_vars` at this
version: they need their own, with their secrets in `*.sops.yaml` files, before
`task configure` can run there.

## Roles

The roles in `ansible/roles/` are configured with Ansible variables, for example in
`ansible/inventories/<env>/group_vars/`. Each role checks its variables against its
`meta/argument_specs.yml` when it starts; the tables below are generated from those files
(`python3 tests/role_docs.py --write`), and each role's README explains the controls behind them.
The roles of the `luminare.infra_edge` and `luminare.gameserver` collections are documented in
their own repositories.

### docker

Docker Engine for container hosts, with published ports on loopback
([README](../ansible/roles/docker/README.md)).

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
| `docker_restart_with_nftables` | bool | `true` | Add a docker.service drop-in (After= and PartOf=nftables.service), so that a restart of nftables.service, which flushes the whole ruleset, also restarts Docker and its rules; it allows Docker 10 starts in 60 seconds, so that several firewall reloads in one run never leave Docker stopped. |
| `docker_firewall_manage` | bool | `false` | Write the forward rules (/etc/nftables.d/60-docker.nft) even when /etc/nftables.d does not exist yet. Without it, the file is written only when the directory exists. |
| `docker_firewall_reload` | bool | `true` | Restart nftables.service after the forward rules changed. Molecule sets it to false and restarts the service in its verify step instead. |
<!-- argument-specs:docker:end -->

### monitoring

node_exporter on loopback or a private address, and Uptime Kuma with a monitor checklist
([README](../ansible/roles/monitoring/README.md)).

<!-- argument-specs:monitoring:begin -->
| Variable | Type | Default | Description |
|---|---|---|---|
| `monitoring_node_exporter_enabled` | bool | `true` | Install and run node_exporter. |
| `monitoring_node_exporter_version` | str | `1.12.1` | node_exporter release to install. Change monitoring_node_exporter_checksums with it (from the release's sha256sums.txt). |
| `monitoring_node_exporter_checksums` | dict | `{"amd64": "b51d8a76aa2a9156a55d501aca6276fae09e262259a5e4e831d2c2222f084e63", "arm64": "ad35b605f9954b9f1ffddf5ba054bdc5a98d790b9eae5291e1eeb83f1ecbd0e7"}` | sha256 of the release archive for each architecture (amd64, arm64); the download fails when the archive differs. |
| `monitoring_node_exporter_download_url` | str | `https://github.com/prometheus/node_exporter/releases/download` | Base URL of the release archives; the role appends the release tag and the archive name of the version and architecture, as on the release page. |
| `monitoring_node_exporter_listen_address` | str | `127.0.0.1` | Address node_exporter listens on: loopback or a private address (127.0.0.0/8 or ::1, the RFC 1918 networks, the RFC 6598 shared address space or an IPv6 unique local address in fc00::/7). The role refuses any other, including 0.0.0.0 and ::. |
| `monitoring_node_exporter_port` | int | `9100` | TCP port of node_exporter. |
| `monitoring_node_exporter_textfile_dir` | str | `/var/lib/node_exporter/textfile` | Directory of the textfile collector: other jobs (for example a backup) write *.prom files here, and node_exporter exports their metrics. |
| `monitoring_node_exporter_extra_args` | list of str | `[]` | More command-line flags for node_exporter, for example --collector.systemd. Flags that set the listen address or the textfile directory are refused. |
| `monitoring_node_exporter_allowed_sources` | list of str | `[]` | IPv4 or IPv6 addresses or networks that may reach node_exporter (for example a Prometheus server), written as accept rules into /etc/nftables.d/50-monitoring.nft. Allowed only with a private (not loopback) listen address. Empty removes the drop-in. |
| `monitoring_firewall_manage` | bool | `false` | Write the drop-in even when /etc/nftables.d does not exist yet. Without it, the file is written only when the directory exists. |
| `monitoring_firewall_reload` | bool | `true` | Restart nftables.service after the drop-in changed. Molecule sets it to false (a container is no place to prove a loaded input ruleset; the drop-in is still validated). |
| `monitoring_uptime_kuma_enabled` | bool | `false` | Run Uptime Kuma in a container and render the monitor checklist. Needs Docker (the docker role). Place it on a host other than the ones it watches. |
| `monitoring_uptime_kuma_image` | str | `louislam/uptime-kuma:2.5.6-slim@sha256:5db97dbbef610276e1699f3ece586c3509c8fd35de75d45ff5109761a1b377dc` | Uptime Kuma image, pinned by digest. The slim variant has no embedded MariaDB and no browser engine; it stores its data in SQLite. |
| `monitoring_uptime_kuma_container_name` | str | `uptime-kuma` | Name of the Uptime Kuma container. |
| `monitoring_uptime_kuma_bind_address` | str | `127.0.0.1` | Address the Uptime Kuma port is published on: loopback or a private address, as for node_exporter. Reach it through a tunnel with access control, not from the internet. |
| `monitoring_uptime_kuma_port` | int | `3001` | Host port for the Uptime Kuma web interface (the container listens on 3001). |
| `monitoring_uptime_kuma_data_volume` | str | `uptime-kuma-data` | Docker volume that keeps the Uptime Kuma database (/app/data in the container). |
| `monitoring_uptime_kuma_checklist_path` | str | `/etc/uptime-kuma/monitors.md` | Where the role writes the checklist of monitors to create in Uptime Kuma (Markdown). |
| `monitoring_monitors` | list of dict | `[]` | Monitors for the checklist. Each item has name and type (http, keyword, port, ping, dns, push or smtp), the target (url for http and keyword, plus keyword; host for port, ping, dns and smtp, plus port for port and smtp) and optionally interval (seconds, at least 20, default 60), accepted_status_codes (default 200-299), upside_down (default false) and notes. Never put credentials into a monitor. |
| `monitoring_external_probes` | list of dict | `[]` | Read-only checks of hosts outside this environment, listed in their own section of the checklist. Same keys as monitoring_monitors, but only the types http, keyword, port and smtp, a host name (never an IP address) as target, no user name or password in a URL and an interval of at least 300 seconds. |
<!-- argument-specs:monitoring:end -->

### deploy_target

An upload-only SSH account and a path unit that runs a deploy script
([README](../ansible/roles/deploy_target/README.md)).

<!-- argument-specs:deploy_target:begin -->
| Variable | Type | Default | Description |
|---|---|---|---|
| `deploy_target_user` | str | `deploy` | Upload account. Its login shell is /bin/sh (sshd runs the forced command through the shell, so nologin would block it); it gets no sudo rights and no password. |
| `deploy_target_ssh_groups` | list of str | `["sshusers"]` | Groups for the upload account, created as system groups when missing. sshusers is the AllowGroups group of the luminare.infra_edge base role, without which SSH refuses the account. |
| `deploy_target_authorized_keys` | list of dict | `[]` | Public keys of the uploaders (for example a CI job). Each item has key (type and base64, ssh-ed25519, ecdsa-sha2-nistp256/384/521 or ssh-rsa), comment and optionally from (list of source address patterns for the from= option, for example 127.0.0.1 and ::1 when uploads come through a tunnel on the host). Every key gets restrict and the forced rrsync command; the file holds exactly these keys. |
| `deploy_target_rrsync_path` | str | `/usr/bin/rrsync` | rrsync from the rsync package (the role checks that it exists). |
| `deploy_target_rrsync_options` | list of str | `["-wo", "-no-del"]` | rrsync options of the forced command; -wo (write only) is required. Allowed: -wo, -no-del (no deletions), -no-lock, -no-overwrite, -munge (rsync --munge-links). |
| `deploy_target_spool_dir` | str | `/srv/luminare/incoming` | Spool directory, the only place the upload keys can write to. Owner deploy_target_user, group deploy_target_run_group, mode 2770 (new files inherit the group). |
| `deploy_target_run_user` | str | `fxserver` | User of the deploy service (the game server user). It must exist; the role does not create it. |
| `deploy_target_run_group` | str | `fxserver` | Group of the deploy service and of the spool directory. |
| `deploy_target_release_root` | str | `/opt/fxserver/releases` | Directory for unpacked releases, owned by deploy_target_run_user (mode 0750); passed to the script as DEPLOY_RELEASE_ROOT. |
| `deploy_target_script_src` | str | `""` | Deploy script on the control node, installed to deploy_target_script_dest (required; the script itself is not part of this role). See the role README for the environment it gets and what it must do with the files in the spool directory. |
| `deploy_target_script_dest` | str | `/usr/local/sbin/luminare-deploy` | Path of the installed deploy script (root-owned, mode 0755). |
| `deploy_target_unit_name` | str | `luminare-deploy` | Name of the systemd path and service units (the name plus .path and .service). |
| `deploy_target_keep_versions` | int | `3` | Releases to keep per resource; passed to the script as DEPLOY_KEEP_VERSIONS. |
| `deploy_target_reload_hook` | bool | `false` | Whether the script may call a reload hook after a deploy (staging only); passed as DEPLOY_RELOAD_HOOK (1 or 0). |
| `deploy_target_read_write_paths` | list of str | `[]` | More paths the sandboxed service may write to (absolute), for example the resources folder where the script links a release. The spool directory and the release root are always writable. |
| `deploy_target_packages` | list of str | `["rsync", "unzip"]` | Packages for uploads (rsync with rrsync) and for the deploy script (unzip). |
<!-- argument-specs:deploy_target:end -->

## Secrets

Secrets never go into this repository in clear text, nor into an issue or a log. CI scans every
commit with gitleaks; a leaked secret is rotated first and removed from history second.

Credentials and other secret values are kept in files encrypted with SOPS for age keys
([ADR 0006](adr/0006-sops-and-age-for-secrets.md)). **This repository ships no encrypted file,
no `.sops.yaml` and no age recipient**: each operator creates their own keys and files as
described below, and a fork never inherits anyone's recipients.

### Layout

| File | Holds | Decrypted by |
|---|---|---|
| `secrets/<env>.enc.env` (`lab`, `demo`, `showcase`) | the write credentials of the environment and its state passphrase (dotenv, one `KEY=value` per line) | the operator, the break-glass key; for `demo` and `showcase` also the GitHub environment of the same name (`apply`) |
| `secrets/<env>-ci.enc.env` | read-only tokens for plans, the state passphrase, a read-only key for the state bucket | the operator, the break-glass key and the GitHub environment `lab-plan` (`plan`, `drift`) |
| `secrets/demo-e2e.enc.env` | the Cloudflare token, account, zone and team values of the tunnel test; no cloud server token | the operator, the break-glass key and the GitHub environment `demo-e2e` |
| `ansible/inventories/<env>/group_vars/*.sops.yaml` | secret Ansible values of the environment (database, backup and admin passwords, the admin password hash) | the operator, the break-glass key; for `demo` and `showcase` also their GitHub environment |
| `.sops.yaml` at the repository root | the creation rules: which public keys may decrypt which file | public, committed; holds public keys only |

The keys a dotenv file can hold:

| Key | Read by | Notes |
|---|---|---|
| `PROXMOX_VE_ENDPOINT`, `PROXMOX_VE_API_TOKEN`, `PROXMOX_VE_API_HEADERS` | bpg/proxmox provider | API token with privilege separation ([ADR 0025](adr/0025-proxmox-ve-api-tokens-with-least-privilege.md)); extra headers for an access proxy in front of the API |
| `CLOUDFLARE_API_TOKEN`, `TF_VAR_account_id`, `TF_VAR_zone_id` | cloudflare/cloudflare provider; `task configure` (the tunnel token) | token limited to one zone; reading the tunnel token needs tunnel write permission |
| `TF_VAR_zone`, `TF_VAR_access_team_name`, `TF_VAR_allowed_emails` | `lab`, `demo`, `showcase` | the zone, the Zero Trust team name and who may log in (JSON list) |
| `TF_VAR_ssh_keys`, `TF_VAR_ssh_public_key` | `lab` (JSON list), `demo` and `showcase` (one key line) | public keys of the admin user |
| `SSH_PRIVATE_KEY_B64` | `task configure` and `task smoke` of `demo` and `showcase` (the `apply` workflow) | the private key of `TF_VAR_ssh_public_key` as one line of base64 (`base64 -w0 <key file>`), written to a private temporary file for the run; only in `secrets/<env>.enc.env` of the environments that the `apply` workflow configures. A workstation uses the operator's own key instead |
| `HCLOUD_TOKEN` | hetznercloud/hcloud provider | token of a project that holds nothing but this lab |
| `AWS_ENDPOINT_URL_S3`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | S3-compatible state backend | the account's endpoint (`https://<account_id>.r2.cloudflarestorage.com`) and a token for the state bucket only |
| `TF_VAR_state_passphrase` | state and plan encryption | at least 16 characters; kept offline as well, since a lost passphrase means a lost state |

[secrets/env.example](../secrets/env.example) lists the same keys without values. The roles of
this repository need no secret (`deploy_target` takes public keys only), and the `local`
environment generates its own throwaway secrets (see
[Playbooks and inventories](#playbooks-and-inventories)).

### Create the age keys

Each key is a pair: the private key (a line starting with `AGE-SECRET-KEY-1`) decrypts, the
public key (`age1…`) goes into `.sops.yaml`. `age-keygen -y <file>` prints the public key of a
private key file.

1. **Operator** (on the workstation, where SOPS looks for it by default):

   ```bash
   mkdir -p ~/.config/sops/age
   age-keygen -o ~/.config/sops/age/keys.txt
   chmod 600 ~/.config/sops/age/keys.txt
   ```

2. **Break-glass** (the copy that survives a lost workstation): create it the same way into a
   temporary file, note its public key, keep the private key offline only (printed, and in a
   password manager), then delete the file.
3. **One key per GitHub environment** that decrypts files (`lab-plan`, `demo`, `showcase`,
   `demo-e2e`): create it into a temporary file, put the whole private key line into that
   environment's secret `SOPS_AGE_KEY` (Settings, Environments), note the public key, then delete
   the file. Such a key never exists anywhere else
   ([runbook](runbook.md#procedure-turn-on-the-cloud-workflows)).

### Write `.sops.yaml`

This example gives every file of the layout above its recipients. Replace each `<…>` with the
public key of that name, keep the order of the rules (SOPS uses the first rule whose `path_regex`
matches), and commit the file:

```yaml
# Who can decrypt which file. Public age keys only; SOPS takes the first rule whose path_regex
# matches the path of the file, so the most specific rule comes first.
creation_rules:
  # Read-only credentials for plans in CI: the GitHub environment lab-plan (plan, drift).
  - path_regex: secrets/(lab|demo|showcase)-ci\.enc\.env$
    age: >-
      <operator>,
      <break-glass>,
      <lab-plan>
  # Write credentials of the lab: the workstation only, never CI.
  - path_regex: secrets/lab\.enc\.env$
    age: >-
      <operator>,
      <break-glass>
  # Write credentials of demo and showcase, and their secret inventory values: the GitHub
  # environment of the same name (apply, after the owner's review).
  - path_regex: (secrets/demo\.enc\.env|ansible/inventories/demo/group_vars/.*\.sops\.yaml)$
    age: >-
      <operator>,
      <break-glass>,
      <demo>
  - path_regex: (secrets/showcase\.enc\.env|ansible/inventories/showcase/group_vars/.*\.sops\.yaml)$
    age: >-
      <operator>,
      <break-glass>,
      <showcase>
  # The tunnel test: the GitHub environment demo-e2e.
  - path_regex: secrets/demo-e2e\.enc\.env$
    age: >-
      <operator>,
      <break-glass>,
      <demo-e2e>
  # Secret inventory values of the lab.
  - path_regex: ansible/inventories/lab/group_vars/.*\.sops\.yaml$
    age: >-
      <operator>,
      <break-glass>
```

The rules were tested on 2026-10-22 with SOPS 3.13.3 and age 1.3.2, with throwaway keys: each
file of the layout was decrypted by exactly the keys in the table above.

### Create and use a file

```bash
sops edit secrets/lab.enc.env                    # creates the file, or edits it
sops exec-env secrets/lab.enc.env 'tofu -chdir=tofu/envs/lab plan'
sops updatekeys secrets/lab.enc.env              # after a change of .sops.yaml
```

`sops edit` opens the decrypted content in the editor and writes it back encrypted; keep each
value on one line. Use a file only through `sops exec-env`, so the values exist in the
environment of that one command; `task init`, `task plan` and the other environment tasks do
this themselves when the file exists. Never write a decrypted copy to disk: `.gitignore` ignores
every other file in `secrets/` and every `*.dec.*` file, and a unit test fails if a committed
`*.enc.env` file holds a value that is not encrypted. Secret Ansible values go into
`ansible/inventories/<env>/group_vars/*.sops.yaml` (`sops edit` as above): the SOPS vars plugin
of `community.sops`, enabled in `ansible/ansible.cfg`, decrypts them at run time without writing
a decrypted copy.

To remove a recipient (a lost key, a GitHub environment that is gone), delete its public key from
`.sops.yaml`, run `sops updatekeys` on every file it could read, and rotate the credentials in
those files: the removed key may hold an old copy.
