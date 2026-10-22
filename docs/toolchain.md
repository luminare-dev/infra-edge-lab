# Toolchain

The tools used to work on this repository are pinned to one version each; the exception is
named below (the dependencies of markdownlint-cli2 in a local run). A downloaded binary is
installed only after its sha256 matches the checksum the tool's project publishes with the
release; Python packages are installed with `pip --require-hashes` from files that list the
sha256 of every distribution file on PyPI, and OpenTofu providers are checked against the
`.terraform.lock.hcl` of each module.
Workflow actions are pinned by commit SHA
([ADR 0002](adr/0002-pin-actions-and-downloaded-tools.md)); `python3 scripts/check_workflows.py --list`
prints them.

Versions and checksums were verified on 2026-10-21 for Linux x86_64 (the GitHub `ubuntu-24.04`
runner and the workstation). `tests/test_toolchain.py` fails when this page, the workflow inputs,
the requirements files and the README disagree.

## Binary tools

| Tool | Version | Purpose in this repository | File (linux amd64) | sha256 | Checksum source |
|---|---|---|---|---|---|
| OpenTofu | 1.13.1 | provisioning code in `tofu/` (CI `tofu`, `task tofu`; `task lint` runs `tofu fmt -check`) | `tofu_1.13.1_linux_amd64.tar.gz` | `378ada19d4bc70c43732004e8159be771b23b9a5afdf059e5f8a2b3fa2c70a69` | `tofu_1.13.1_SHA256SUMS` of the [release](https://github.com/opentofu/opentofu/releases/tag/v1.13.1), signed (`.sig`/`.pem` and `.gpgsig`) |
| TFLint | 0.64.0 | linter for `tofu/` with its bundled Terraform ruleset, configured in `.tflint.hcl` (CI `tofu`, `task tofu`) | `tflint_linux_amd64.zip` | `cca9d13e2e1d7a2c627af60ff899a3c9b74212899416aeb96ec764d2ef954537` | `checksums.txt` of the [release](https://github.com/terraform-linters/tflint/releases/tag/v0.64.0), keyless-signed (`.keyless.sig`, `.pem`) |
| Terraform | 1.16.6 | compatibility check only: `terraform validate` of `tofu/` ([ADR 0005](adr/0005-opentofu-instead-of-terraform.md)); downloaded into a throwaway directory by `scripts/check_tofu.sh compat` | `terraform_1.16.6_linux_amd64.zip` | `38034b38d03096399a7a1264a14561a8029b2b496fd1f169452656e53968f1b7` | `terraform_1.16.6_SHA256SUMS` of the [release](https://releases.hashicorp.com/terraform/1.16.6/), signed by HashiCorp's release key (`_SHA256SUMS.sig`; signature checked 2026-10-21) |
| go-task | 3.54.0 | `Taskfile.yml` (`task lint`, `task test`, `task tofu`) | `task_linux_amd64.tar.gz` | `680859dbb4d881a9c72d4d9a8f510825450849af8567deacd7302c01124416fb` | `task_checksums.txt` of the [release](https://github.com/go-task/task/releases/tag/v3.54.0) |
| gitleaks | 8.30.1 | secret scan of the full history (CI `secrets / gitleaks`, `task lint`) | `gitleaks_8.30.1_linux_x64.tar.gz` | `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb` | `gitleaks_8.30.1_checksums.txt` of the [release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1) |
| actionlint | 1.7.12 | workflow linter (CI `ci / lint-test`, `task lint`) | `actionlint_1.7.12_linux_amd64.tar.gz` | `8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8` | `actionlint_1.7.12_checksums.txt` of the [release](https://github.com/rhysd/actionlint/releases/tag/v1.7.12) |
| Trivy | 0.76.0 | IaC security scan of `tofu/` and `images/` (`trivy config` with the checks built into the release, offline; accepted findings with their reason in `.trivyignore.yaml`) (CI `tofu`, `task tofu`) | `trivy_0.76.0_Linux-64bit.tar.gz` | `e24b1c51293c1b15e4ba8d45bbc7891ba053f90278ec2698f3562c993e145fe7` | `trivy_0.76.0_checksums.txt` of the [release](https://github.com/aquasecurity/trivy/releases/tag/v0.76.0), Sigstore bundle (`.sigstore.json`) |
| SOPS | 3.13.3 | encrypts the dotenv files in `secrets/` | `sops-v3.13.3.linux.amd64` | `e5bec3346a873ae91d871550f3e698c1aad962aff462a080e40f25fde17fef6b` | `sops-v3.13.3.checksums.txt` of the [release](https://github.com/getsops/sops/releases/tag/v3.13.3), Sigstore bundle |
| age | 1.3.2 | keys for SOPS | `age-v1.3.2-linux-amd64.tar.gz` | `cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10` | asset digest of the [release](https://github.com/FiloSottile/age/releases/tag/v1.3.2) and its `.proof` file |
| Node.js | 24.22.0 | runs markdownlint-cli2 locally | `node-v24.22.0-linux-x64.tar.xz` | `cc2f601cee82d9a5a233302fe307abc600727035fd7d2c3a3571755989e95008` | [`SHASUMS256.txt`](https://nodejs.org/dist/v24.22.0/SHASUMS256.txt) (signed `SHASUMS256.txt.asc`) |

markdownlint-cli2 **0.23.2** is the version that CI's `DavidAnson/markdownlint-cli2-action`
v24.2.0 bundles. `task lint` runs it with `npx --yes markdownlint-cli2@0.23.2`; npm checks the
package against the registry's integrity value
(`sha512-eUhcnkSpzURo/o4htSqc7LPDszgOOTknhU4eY/sPHvMCLxnTCYscv1gw1/js/idmaZPisv9ECVEIORcllqjTUw==`).
That pins the package itself only: it names exact versions of its direct dependencies, but their
own dependencies resolve from semver ranges when npx installs them, and this repository keeps no
lock file for them. CI installs nothing from npm: the action runs the copy bundled in its
`dist/`, fixed by the action's commit SHA.

`scripts/install_tofu_tools.sh` holds the versions and sha256 values of OpenTofu, TFLint,
Terraform and Trivy for the CI job `tofu` and the compatibility check; `tests/test_tofu.py` and
`tests/test_toolchain.py` fail when they differ from the table above.

Install a binary only after the check passes, for example:

```bash
curl -fsSLO https://github.com/go-task/task/releases/download/v3.54.0/task_linux_amd64.tar.gz
echo "680859dbb4d881a9c72d4d9a8f510825450849af8567deacd7302c01124416fb  task_linux_amd64.tar.gz" | sha256sum -c -
tar -xzf task_linux_amd64.tar.gz task && install -m 0755 task ~/.local/bin/task
```

## OpenTofu providers and the host image

Each module under `tofu/modules/` and each environment under `tofu/envs/` pins its providers
with a version constraint in `versions.tf` and commits a `.terraform.lock.hcl` with package
checksums for `linux_amd64` and `darwin_arm64` and the registry's signed checksums of every
platform's archive ([ADR 0012](adr/0012-provider-pins-and-lock-files.md)). An environment locks
the same version and checksums as the modules it calls; `tests/test_tofu.py` checks this.
Versions were checked in the OpenTofu registry on 2026-10-21:

| Provider | Constraint | Locked | Newest release on 2026-10-21 | Note |
|---|---|---|---|---|
| `bpg/proxmox` | `~> 0.114.0` | 0.114.0 | 0.117.0 | below 1.0, so patch releases only; Dependabot proposes newer minor releases in a pull request of their own |
| `cloudflare/cloudflare` | `~> 5.25` | 5.28.1 | 5.28.1 | 5.28.1 distrusts certificate authorities revoked for compromise |
| `hetznercloud/hcloud` | `~> 1.69` | 1.70.0 | 1.70.0 | |
| `kreuzwerker/docker` | `~> 4.6` | 4.6.0 | 4.6.0 | |

`cloudflare` 5.28.1 was published at 2026-10-20 23:35 UTC, less than a day before it was locked
here, and so was taken without the 7-day cooldown that Dependabot keeps for version updates
([ADR 0007](adr/0007-dependabot-instead-of-renovate.md)). It is a security rebuild whose release
notes list no schema change: it is built with Go 1.27.3, which distrusts intermediate certificate
authorities revoked for compromise on the connection that carries the Cloudflare API token.
Dependabot skips the cooldown for security updates for the same reason; the tests pass with
5.28.1 and with 5.25.0.

`tofu test` and `tofu validate` also pass with the lowest version of each range
(`cloudflare` 5.25.0, `hcloud` 1.69.0), in the modules and in the environments. After a
constraint change, write the lock files again for both platforms, in every module and
environment that uses the provider:

```bash
tofu -chdir=tofu/modules/<module> providers lock -platform=linux_amd64 -platform=darwin_arm64
tofu -chdir=tofu/envs/<env> providers lock -platform=linux_amd64 -platform=darwin_arm64
```

`images/systemd-host/Dockerfile` (the host image of the `docker_host` module) starts from
`debian:trixie` and `ubuntu:24.04`, each pinned by digest (pulled and checked 2026-10-21).
Dependabot's `docker` ecosystem proposes new digests.

The hosts that `hcloud_vm` creates install cloudflared 2026.9.1 at first boot from its GitHub
release (`cloudflared-linux-amd64.deb`, sha256
`3be76adc4185d36a0bfb4c2dd8663292f0ed363797f2180333b513b43c81d419` from the release notes, the
same as GitHub's asset digest and the download checked on 2026-10-21). Cloudflare's package
repository lists only its newest release (2026.10.2 on 2026-10-21), so it cannot install a
pinned older version.

## Python

Python **3.12** is the `python3` of the `ubuntu-24.04` runner and the oldest version
ansible-core 2.21 supports. The hash-pinned install was also tested with Python 3.13.

The table names the file that pins each package instead of repeating its version, so a
Dependabot update of a requirements file needs no edit on this page. At this version
`scripts/run_tests.sh` installs the Ansible tools and checks their installed versions against
the pins; no playbook, role or Molecule scenario uses them yet.

| Package | Pinned in | Purpose |
|---|---|---|
| ansible-core | `requirements-test.in`, compiled into `requirements-test.txt` | Ansible controller |
| ansible-lint | `requirements-test.in`, compiled into `requirements-test.txt` | Ansible linter (production profile) |
| molecule | `requirements-test.in`, compiled into `requirements-test.txt` | role test framework |
| molecule-plugins (`docker` extra) | `requirements-test.in`, compiled into `requirements-test.txt` | Molecule Docker driver |
| yamllint | `requirements-dev.txt` | YAML lint (CI `ci / lint-test`, `task lint`) |
| zizmor | `requirements-dev.txt` | workflow security audit (CI `ci / lint-test`, `task lint`) |
| pip-tools | `pip-tools==7.5.2` in the compile command under [Updating a pin](#updating-a-pin) | compiles `requirements-test.txt`; not installed by the tasks |
| click | `click==8.2.1` in the same command | command-line library of pip-tools, held below 8.3 (see below) |

`requirements-test.txt` is generated from `requirements-test.in` by pip-compile and lists every
dependency with its hashes (45 packages when it was compiled on 2026-10-21).
`requirements-dev.txt` comes from the template and is pinned by hand. Install either file with
`pip install --require-hashes --only-binary=:all: -r <file>`; `scripts/run_tests.sh` and
`task venv` do this.

## Hooks before a commit

`.pre-commit-config.yaml` runs the quick checks as git hooks: end-of-file and trailing-whitespace
fixes, shellcheck, gitleaks on the staged changes, yamllint, the check that every
`secrets/*.enc.env` is encrypted (`sops filestatus`), `tofu fmt` and TFLint. It is optional; CI
runs the same checks in its own jobs. Install pre-commit (tested with 4.7.0, for example `pipx install pre-commit`), run
`task venv` and put `.venv/bin` on the PATH, then `pre-commit install`. The hooks of other
repositories are pinned to a commit SHA with the tag in a comment (`pre-commit autoupdate --freeze`
writes them so), and pre-commit installs them into its own cache on the first run:
pre-commit-hooks v6.0.0, shellcheck-py v0.11.0.1 (shellcheck 0.11.0) and the `gitleaks-system`
hook of gitleaks v8.30.1, which runs the gitleaks binary of the table above. The other hooks run
the tools of this page.

## Updating a pin

- **Python test tools:** Dependabot recompiles `requirements-test.txt` when a pinned package has
  a new release ([ADR 0007](adr/0007-dependabot-instead-of-renovate.md)). To change the pins by
  hand, edit `requirements-test.in` and compile with Python 3.12:

  ```bash
  docker run --rm -v "$PWD:/work" -w /work \
    python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 \
    sh -c 'pip install --quiet pip-tools==7.5.2 click==8.2.1 && pip-compile --generate-hashes --allow-unsafe --strip-extras --output-file=requirements-test.txt requirements-test.in'
  ```

  Keep click below 8.3 for pip-tools 7.5.2: with click 8.3 pip-tools writes a wrong
  `--no-index` option into the command line in the file header, which Dependabot reuses.
- **Binary tools:** once a month, read the new release's checksum file (and check its signature
  where the project signs it), then change the version and sha256 here and in every place that
  pins the same file (the `gitleaks-*` and `actionlint-*` inputs of the reusable workflows).
  Dependabot does not see these pins.
