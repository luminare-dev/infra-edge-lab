# Installation

This page sets up a workstation for working on the repository. Tested on 2026-10-21 on Linux
x86_64 with the versions in [toolchain.md](toolchain.md); the Python part was also tested in the
`python:3.12-slim` and `python:3.13-slim` containers.

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| Git | any current version | |
| Python | 3.12 or 3.13, with the `venv` module | Debian and Ubuntu: package `python3-venv` |
| go-task | 3.54.0 | runs `task lint`, `task test` and `task tofu` |
| OpenTofu, gitleaks, actionlint | as in [toolchain.md](toolchain.md) | needed by `task lint` |
| OpenTofu, TFLint, Trivy | as in [toolchain.md](toolchain.md) | needed by `task tofu` (Trivy for its `iac` step); on Linux x86_64, `bash scripts/install_tofu_tools.sh ~/.local/bin tofu tflint trivy` installs them after checking their sha256 |
| Docker Engine | allows privileged containers | needed by the `integration` step of `task tofu` (the `docker_host` module boots containers with systemd) |
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
`pip install --require-hashes --only-binary=:all:`.

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

The last line of the output starts with `OK`; a test that needs an optional tool, such as
markdownlint-cli2, that is not on the `PATH` is counted as skipped. `task lint` then runs every
repository check; each one prints no finding. `task tofu` runs the OpenTofu checks; every
`tofu test` ends with `Success!` and every validation with `The configuration is valid.` The
OpenTofu checks download the providers named in the lock files into `.terraform/` of each
module, one copy per module: about 700 MB unpacked, because the Cloudflare provider (about
190 MB) is used by three modules. With `TF_PLUGIN_CACHE_DIR` set to a directory, every provider
is stored there once, about 320 MB in all.

## Uninstall

Delete the clone. Inside it, the tasks create `.venv/` (Python tools), `.task/` (go-task's
checksum cache) and `tofu/modules/*/.terraform/` (provider downloads). The `docker_host`
integration test removes its containers, network and image when it ends; the base images
`debian:trixie` and `ubuntu:24.04` stay in the Docker image store (`docker image rm` removes
them). Outside it, two download caches in your home directory remain: pip's
(`~/.cache/pip`, written by `task venv` and `task test`) and npm's (`~/.npm`, where
`npx markdownlint-cli2` in `task lint` keeps the package). They may also hold files of other
projects, so delete them only if nothing else needs them.
