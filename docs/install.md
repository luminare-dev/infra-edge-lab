# Installation

Sets up a Linux x86_64 workstation for the repository and its environments. Versions are in
[toolchain.md](toolchain.md).

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

The luminare collections are cloned from GitHub at the pinned release tags; `devsec.hardening`
and `prometheus.prometheus` come from Ansible Galaxy. The unit tests and ansible-lint need none of
them.

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

The unit tests end with `OK` (tests that need an optional tool that is missing are skipped) and
ansible-lint with `Passed: 0 failure(s), 0 warning(s)`. `task lint` runs the repository checks
and `task tofu` the OpenTofu checks. The providers take about 1.5 GB in the `.terraform/`
folders; set `TF_PLUGIN_CACHE_DIR` to share one copy (about 320 MB).

`task molecule ROLE=<role>` runs a role's Molecule scenario on both platforms (Debian 13 and
Ubuntu 24.04, one after the other); each ends with `Executed: Successful` for every step, and the
idempotence step reports `changed=0`. Add `PLATFORM=debian13` or `PLATFORM=ubuntu2404` to run one
platform only.

To try an environment without any account, rebuild `local` from nothing and throw it away
again; this is what CI's `e2e-local` workflow runs:

```bash
task e2e:local
```

It ends with `Result: passed`. To keep the environment for a look inside, build it step by step
instead, with one passphrase for the whole session:

```bash
export TF_VAR_state_passphrase="$(openssl rand -base64 32)"
task collections
task up ENV=local
docker exec -it lab-local-edge-01 bash
task destroy ENV=local
```

## Uninstall

Destroy what an environment holds first (`task destroy ENV=local` with the same passphrase), then
delete the clone. The Molecule and host images stay in Docker's image store (`docker image rm`),
and pip, npm and Ansible keep caches in your home directory (`~/.cache/pip`, `~/.npm`,
`~/.ansible/tmp`, `~/.cache/ansible-compat`).
