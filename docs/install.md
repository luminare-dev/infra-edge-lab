# Installation

This page sets up a workstation for working on the repository. Tested on 2026-10-21 on Linux
x86_64 with the versions in [toolchain.md](toolchain.md); the Python part was also tested in the
`python:3.12-slim` and `python:3.13-slim` containers.

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| Git | any current version | |
| Python | 3.12 or 3.13, with the `venv` module | Debian and Ubuntu: package `python3-venv` |
| go-task | 3.54.0 | runs `task lint` and `task test` |
| OpenTofu, gitleaks, actionlint | as in [toolchain.md](toolchain.md) | needed by `task lint` |
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
repository check; each one prints no finding.

## Uninstall

Delete the clone. Inside it, the tasks create `.venv/` (Python tools) and `.task/` (go-task's
checksum cache). Outside it, two download caches in your home directory remain: pip's
(`~/.cache/pip`, written by `task venv` and `task test`) and npm's (`~/.npm`, where
`npx markdownlint-cli2` in `task lint` keeps the package). They may also hold files of other
projects, so delete them only if nothing else needs them.
