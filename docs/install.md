# Installation

This page sets up a workstation for working on the repository and for running its environments.
Tested on 2026-10-21 and 2026-10-22 on Linux x86_64 with the versions in
[toolchain.md](toolchain.md); the Python part was also tested in the `python:3.12-slim` and
`python:3.13-slim` containers.

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| Git | any current version | |
| Python | 3.12 or 3.13, with the `venv` module | Debian and Ubuntu: package `python3-venv` |
| go-task | 3.54.0 | runs `task lint`, `task test`, `task tofu`, `task molecule`, `task e2e:local` and the environment tasks |
| OpenTofu, gitleaks, actionlint | as in [toolchain.md](toolchain.md) | needed by `task lint` |
| OpenTofu, TFLint, Trivy | as in [toolchain.md](toolchain.md) | needed by `task tofu` (Trivy for its `iac` step), OpenTofu also by `task e2e:local` and the environment tasks; on Linux x86_64, `bash scripts/install_tofu_tools.sh ~/.local/bin tofu tflint trivy` installs them after checking their sha256 |
| Docker Engine | allows privileged containers | needed by the `integration` step of `task tofu` (the `docker_host` module boots containers with systemd), by `task molecule` (the role scenarios) and by the `local` environment (`task e2e:local`, `task up ENV=local`); about 2 GB of free memory for the docker and monitoring scenarios and for the monitoring host of `local`, which keep Docker's storage inside the container on tmpfs |
| OpenSSH client | any current version | `ssh-keygen` creates the throwaway key of the `local` environment and of `task e2e:tunnel`, whose SSH check also needs `ssh` |
| SOPS, age | as in [toolchain.md](toolchain.md) | read the encrypted files in `secrets/`; `task dns-backup` encrypts the zone copy with age |
| curl | any current version | `task e2e:tunnel` checks `demo-web` with it and downloads the pinned cloudflared |
| cloudflared | as in [toolchain.md](toolchain.md) | on the PATH for `task configure` and `task smoke` of a cloud server in `demo` or `showcase`, which Ansible reaches through the tunnel with `cloudflared access ssh` |
| Network access | outbound HTTPS | PyPI (the hash-pinned Python tools), GitHub (the luminare collections and the release downloads of node_exporter and Prometheus), Ansible Galaxy, Docker Hub (base images, Uptime Kuma) and the package mirrors of Debian, Ubuntu and Docker inside the hosts |
| Node.js | 24.22.0 | runs markdownlint-cli2 in `task lint` |

Install every binary only after its sha256 matches the value in [toolchain.md](toolchain.md).
The Python tools come from the hash-pinned requirements files; nothing is installed system-wide.

## Install

```bash
git clone https://github.com/luminare-dev/infra-edge-lab.git
cd infra-edge-lab
task venv
```

`task venv` creates `.venv` and installs `requirements-dev.txt` and `requirements-test.txt` with
`pip install --require-hashes --only-binary=:all:`. `requirements-test.txt` includes the
`ansible` package, which brings the community collections that the roles, ansible-lint and
Molecule use, so the tests need nothing from Ansible Galaxy.

To run the playbooks, install the collections of
[ansible/requirements.yml](../ansible/requirements.yml) into `ansible/collections`:

```bash
task collections
```

`luminare.infra_edge` and `luminare.gameserver` are cloned from their public GitHub repositories
(`luminare-dev/ansible-collection-infra_edge`, `luminare-dev/ansible-collection-gameserver`) at
the release tags pinned in that file; `devsec.hardening` and `prometheus.prometheus` come from
Ansible Galaxy at exact versions, and the other community collections from the `ansible` package
of the virtual environment. `task e2e:local` runs the same install itself. The unit tests and
ansible-lint need none of them.

## Keys for the environments with credentials

`local` needs no key and no account. Before working on `lab`, `demo` or `showcase`, create your
age key and the encrypted files of the environment as described in
[configuration.md](configuration.md#secrets); for `lab`, also the Proxmox VE users of the
[runbook](runbook.md#procedure-set-up-the-proxmox-ve-users-of-the-lab).

## Verify the release download

Every release has a `SHA256SUMS` file and a build provenance attestation:

```bash
sha256sum -c SHA256SUMS
gh attestation verify infra-edge-lab-<version>.tar.gz --repo luminare-dev/infra-edge-lab
```

## Check that it works

```bash
task test
```

The unit tests end with a line that starts with `OK` (a test that needs an optional tool, such
as markdownlint-cli2, that is not on the `PATH` is counted as skipped), and ansible-lint ends with
`Passed: 0 failure(s), 0 warning(s)` and the production profile. `task lint` then runs every
repository check; each one prints no finding. `task tofu` runs the OpenTofu checks; every
`tofu test` ends with `Success!` and every validation with `The configuration is valid.` The
OpenTofu checks download the providers named in the lock files into `.terraform/` of each
module and environment, one copy per directory: about 1.5 GB unpacked, because the Cloudflare
provider (about 190 MB) is used by three modules and three environments. With
`TF_PLUGIN_CACHE_DIR` set to a directory, every provider is stored there once, about 320 MB in
all.

`task molecule ROLE=<role>` runs a role's Molecule scenario on both platforms (Debian 13 and
Ubuntu 24.04, one after the other); each ends with `Executed: Successful` for every step, and the
idempotence step reports `changed=0`. Add `PLATFORM=debian13` or `PLATFORM=ubuntu2404` to run one
platform only.

To try an environment without any account, rebuild `local` from nothing and throw it away
again; this is what CI's `e2e-local` workflow runs:

```bash
task e2e:local
```

It creates `edge-01`, `db-01` and `fx-01` as containers, configures them twice with
`ansible/playbooks/site.yml` (the second run must change nothing), plans again (no changes),
smoke-tests them, backs each one up and tests the restore, destroys them, and ends with a table
of its steps and their times
(`Result: passed`). To keep the environment for a look inside, build it step by step instead,
with one passphrase for the whole session:

```bash
export TF_VAR_state_passphrase="$(openssl rand -base64 32)"
task collections
task up ENV=local
docker exec -it lab-local-edge-01 bash
task destroy ENV=local
```

## Uninstall

Delete the clone. Inside it, the tasks create `.venv/` (Python tools), `.task/` (go-task's
checksum cache), `tofu/modules/*/.terraform/` and `tofu/envs/*/.terraform/` (provider
downloads), and an environment with a local state keeps `terraform.tfstate` (and
`backend_override.tf` after `BACKEND=local`) in its folder. Before deleting a state, destroy what
it holds (`task destroy ENV=local` with the same passphrase, which also deletes the empty state of
`local`, `ansible/inventories/local/hosts.yml` and the generated secrets in
`ansible/inventories/local/.generated/`). The `docker_host`
integration test removes its containers, network and image when it ends, and every Molecule
scenario removes its containers; the Molecule images `molecule_local/lab-molecule-debian13` and
`molecule_local/lab-molecule-ubuntu2404` and the base images `debian:trixie` and `ubuntu:24.04`
stay in the Docker image store (`docker image rm` removes them); the destroy of `local` removes
its image `lab-systemd-host-*` too. The Prometheus archive of the `local` environment is cached in
`ansible/inventories/local/.generated/` and goes with it. `ansible/collections/` holds the
collections installed from `ansible/requirements.yml`. Outside it, download caches in your home directory remain: pip's
(`~/.cache/pip`, written by `task venv` and `task test`), npm's (`~/.npm`, where
`npx markdownlint-cli2` in `task lint` keeps the package), and Molecule's and ansible-lint's
working files (`~/.ansible/tmp`, `~/.cache/ansible-compat`). They may also hold files of other
projects, so delete them only if nothing else needs them.
