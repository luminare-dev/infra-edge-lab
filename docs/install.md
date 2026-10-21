# Installation

This page sets up a workstation for working on the repository. Tested on 2026-10-21 on Linux
x86_64 with the versions in [toolchain.md](toolchain.md); the Python part was also tested in the
`python:3.12-slim` and `python:3.13-slim` containers.

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| Git | any current version | |
| Python | 3.12 or 3.13, with the `venv` module | Debian and Ubuntu: package `python3-venv` |
| go-task | 3.54.0 | runs `task lint`, `task test`, `task tofu` and `task molecule` |
| OpenTofu, gitleaks, actionlint | as in [toolchain.md](toolchain.md) | needed by `task lint` |
| OpenTofu, TFLint, Trivy | as in [toolchain.md](toolchain.md) | needed by `task tofu` (Trivy for its `iac` step); on Linux x86_64, `bash scripts/install_tofu_tools.sh ~/.local/bin tofu tflint trivy` installs them after checking their sha256 |
| Docker Engine | allows privileged containers | needed by the `integration` step of `task tofu` (the `docker_host` module boots containers with systemd) and by `task molecule` (the role scenarios); about 2 GB of free memory for the docker and monitoring scenarios, which keep Docker's storage inside the test container on tmpfs |
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

To run the playbooks against real hosts later, install the collections of
[ansible/requirements.yml](../ansible/requirements.yml) (the luminare collections from their git
tags, the community collections at the pinned versions) into `ansible/collections`:

```bash
cd ansible && ../.venv/bin/ansible-galaxy collection install -r requirements.yml
```

This needs the tagged repositories `luminare-dev/ansible-collection-infra_edge` and
`luminare-dev/ansible-collection-gameserver` to be reachable; the tests of this repository do not.

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

To try an environment without any account, initialise and plan `local` (it needs the Docker
daemon only when it is applied):

```bash
export TF_VAR_state_passphrase="$(openssl rand -base64 32)"
task init ENV=local
task plan ENV=local
```

## Uninstall

Delete the clone. Inside it, the tasks create `.venv/` (Python tools), `.task/` (go-task's
checksum cache), `tofu/modules/*/.terraform/` and `tofu/envs/*/.terraform/` (provider
downloads), and an environment with a local state keeps `terraform.tfstate` (and
`backend_override.tf` after `BACKEND=local`) in its folder. Before deleting a state, destroy what
it holds (`tofu -chdir=tofu/envs/local destroy` with the same passphrase). The `docker_host`
integration test removes its containers, network and image when it ends, and every Molecule
scenario removes its containers; the Molecule images `molecule_local/lab-molecule-debian13` and
`molecule_local/lab-molecule-ubuntu2404` and the base images `debian:trixie` and `ubuntu:24.04`
stay in the Docker image store (`docker image rm` removes them). `ansible/collections/` holds the
collections installed from `ansible/requirements.yml`. Outside it, download caches in your home directory remain: pip's
(`~/.cache/pip`, written by `task venv` and `task test`), npm's (`~/.npm`, where
`npx markdownlint-cli2` in `task lint` keeps the package), and Molecule's and ansible-lint's
working files (`~/.ansible/tmp`, `~/.cache/ansible-compat`). They may also hold files of other
projects, so delete them only if nothing else needs them.
