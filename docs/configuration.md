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

The options below change how the tasks, checks and tests run.

| Option | Type | Default | Description |
|---|---|---|---|
| `VENV` (Taskfile variable, `task lint VENV=path`) | path | `.venv` | Python virtual environment that `task venv`, `task lint` and `task test` use. |
| `TEST_VENV` (environment variable) | path | `$RUNNER_TEMP/venv-test` in CI, else `.venv` | Virtual environment into which `scripts/run_tests.sh` installs `requirements-test.txt` before it runs the unit tests. |
| `GITHUB_REPOSITORY` (environment variable) | `owner/name` | the `origin` remote | Repository name for the name check of `scripts/forbidden_words.py`; set it when the clone has no `origin` remote. |
| `STEPS` (Taskfile variable, `task tofu STEPS='fmt test'`) | list of steps | `all` | Steps of `scripts/check_tofu.sh`: `fmt`, `validate`, `tflint`, `iac` (Trivy), `test`, `integration` (needs Docker), `compat`, or `all`. |
| `TF_PLUGIN_CACHE_DIR` (environment variable) | path | unset; `$RUNNER_TEMP/tofu-plugin-cache` in CI | Shared provider cache for `scripts/check_tofu.sh`; the providers are still checked against each lock file. |
| `ENV` (Taskfile variable, `task init ENV=lab`) | `local`, `lab`, `demo` or `showcase` | none; required by `init` and `plan` | Environment under `tofu/envs/` for `task init`, `task plan` and `task test` (`task test` without `ENV` runs the unit tests). |
| `BACKEND` (Taskfile variable, `task init ENV=lab BACKEND=local`) | `remote` or `local` | `remote` | `local` keeps the state of `lab`, `demo` or `showcase` in a local file (still encrypted) through a git-ignored `backend_override.tf`; `remote` removes that file again. |
| `SECRETS` (environment variable) | path | `secrets/<env>.enc.env` | SOPS file that `task init` and `task plan` read with `sops exec-env` when it exists, for example `secrets/lab-ci.enc.env` for a read-only plan. |
| `TF_VAR_state_passphrase` (environment variable) | string, at least 16 characters | none; required | Passphrase of the state and plan encryption ([ADR 0013](adr/0013-encrypted-state-in-r2-with-a-lock-file.md)); from the SOPS file, or a random one per run for `local`. |
| Arguments after `--` (`task plan ENV=lab -- -out=lab.tfplan`) | OpenTofu arguments | none | Passed on to `tofu init` or `tofu plan`. |
| `ROLE` (Taskfile variable, `task molecule ROLE=docker`) | `docker`, `monitoring` or `deploy_target` | none; required by `molecule` | Role under `ansible/roles/` whose Molecule scenario `task molecule` runs. |
| `PLATFORM` (Taskfile variable, `task molecule ROLE=docker PLATFORM=debian13`) | `debian13` or `ubuntu2404` | both | Runs the scenario on one platform only, as one CI matrix job does. |

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
| `docker_restart_with_nftables` | bool | `true` | Add a docker.service drop-in (After= and PartOf=nftables.service), so that a restart of nftables.service, which flushes the whole ruleset, also restarts Docker and its rules. |
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

Secrets never go into this repository, an issue or a log. CI scans every commit with gitleaks; a
leaked secret is rotated first and removed from history second.

Credentials for an environment are kept in SOPS-encrypted dotenv files in `secrets/`
([ADR 0006](adr/0006-sops-and-age-for-secrets.md), [secrets/README.md](../secrets/README.md)).
At this version the repository ships none of them and no `.sops.yaml` yet. The keys a file can
hold:

| Key | Read by | Notes |
|---|---|---|
| `PROXMOX_VE_ENDPOINT`, `PROXMOX_VE_API_TOKEN`, `PROXMOX_VE_API_HEADERS` | bpg/proxmox provider | API token with privilege separation; extra headers for an access proxy in front of the API |
| `CLOUDFLARE_API_TOKEN`, `TF_VAR_account_id`, `TF_VAR_zone_id` | cloudflare/cloudflare provider | token limited to one zone |
| `TF_VAR_zone`, `TF_VAR_access_team_name`, `TF_VAR_allowed_emails` | `lab`, `demo`, `showcase` | the zone, the Zero Trust team name and who may log in (JSON list) |
| `TF_VAR_ssh_keys`, `TF_VAR_ssh_public_key` | `lab` (JSON list), `demo` and `showcase` (one key line) | public keys of the admin user |
| `HCLOUD_TOKEN` | hetznercloud/hcloud provider | token of a project that holds nothing but this lab |
| `AWS_ENDPOINT_URL_S3`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | S3-compatible state backend | the account's endpoint (`https://<account_id>.r2.cloudflarestorage.com`) and a token for the state bucket only |
| `TF_VAR_state_passphrase` | state and plan encryption | at least 16 characters; kept offline as well, since a lost passphrase means a lost state |

Secret Ansible variables go into `ansible/inventories/<env>/group_vars/*.sops.yaml`, encrypted
with SOPS as well: `ansible/ansible.cfg` enables the SOPS vars plugin of `community.sops`, which
decrypts them at run time without writing a decrypted copy. The roles of this repository need no
secret: `deploy_target` takes public keys only.

To create a file: generate an age key (`age-keygen -o ~/.config/sops/age/keys.txt`), add its
public key to the creation rules in `.sops.yaml` at the repository root (a committed file that
holds public keys only), then run `sops edit secrets/<env>.enc.env`.
Use the file only through `sops exec-env secrets/<env>.enc.env '<command>'`; `task init` and
`task plan` do this themselves when the file exists.
