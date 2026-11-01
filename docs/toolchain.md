# Toolchain

Every tool is pinned to one version. Binaries are installed only after their sha256 matches,
Python packages come from hash-pinned requirements files, and providers are checked against each
`.terraform.lock.hcl`. `tests/test_toolchain.py` fails when this page, the workflows, the
requirements files and the README disagree. The checksums are for Linux x86_64.

## Binary tools

| Tool | Version | Purpose in this repository | File (linux amd64) | sha256 | Checksum source |
|---|---|---|---|---|---|
| OpenTofu | 1.13.1 | provisioning code in `tofu/` (CI `tofu` and `e2e-local`, `task tofu`, the environment tasks; `task lint` runs `tofu fmt -check`) | `tofu_1.13.1_linux_amd64.tar.gz` | `378ada19d4bc70c43732004e8159be771b23b9a5afdf059e5f8a2b3fa2c70a69` | `tofu_1.13.1_SHA256SUMS` of the [release](https://github.com/opentofu/opentofu/releases/tag/v1.13.1), signed (`.sig`/`.pem` and `.gpgsig`) |
| TFLint | 0.64.0 | linter for `tofu/` with its bundled Terraform ruleset, configured in `.tflint.hcl` (CI `tofu`, `task tofu`) | `tflint_linux_amd64.zip` | `cca9d13e2e1d7a2c627af60ff899a3c9b74212899416aeb96ec764d2ef954537` | `checksums.txt` of the [release](https://github.com/terraform-linters/tflint/releases/tag/v0.64.0), keyless-signed (`.keyless.sig`, `.pem`) |
| Terraform | 1.16.6 | compatibility check only: `terraform validate` of `tofu/`; downloaded into a throwaway directory by `scripts/check_tofu.sh compat` | `terraform_1.16.6_linux_amd64.zip` | `38034b38d03096399a7a1264a14561a8029b2b496fd1f169452656e53968f1b7` | `terraform_1.16.6_SHA256SUMS` of the [release](https://releases.hashicorp.com/terraform/1.16.6/), signed by HashiCorp's release key (`_SHA256SUMS.sig`; signature checked 2026-10-21) |
| go-task | 3.54.0 | `Taskfile.yml` (`task lint`, `task test`, `task tofu`, `task e2e:local`; CI `e2e-local` downloads it with this sha256) | `task_linux_amd64.tar.gz` | `680859dbb4d881a9c72d4d9a8f510825450849af8567deacd7302c01124416fb` | `task_checksums.txt` of the [release](https://github.com/go-task/task/releases/tag/v3.54.0) |
| gitleaks | 8.30.1 | secret scan of the full history (CI `secrets / gitleaks`, `task lint`) | `gitleaks_8.30.1_linux_x64.tar.gz` | `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb` | `gitleaks_8.30.1_checksums.txt` of the [release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1) |
| actionlint | 1.7.12 | workflow linter (CI `ci / lint-test`, `task lint`) | `actionlint_1.7.12_linux_amd64.tar.gz` | `8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8` | `actionlint_1.7.12_checksums.txt` of the [release](https://github.com/rhysd/actionlint/releases/tag/v1.7.12) |
| Trivy | 0.76.0 | IaC security scan of `tofu/` and `images/` (`trivy config` with the checks built into the release, offline; accepted findings with their reason in `.trivyignore.yaml`) (CI `tofu`, `task tofu`) | `trivy_0.76.0_Linux-64bit.tar.gz` | `e24b1c51293c1b15e4ba8d45bbc7891ba053f90278ec2698f3562c993e145fe7` | `trivy_0.76.0_checksums.txt` of the [release](https://github.com/aquasecurity/trivy/releases/tag/v0.76.0), Sigstore bundle (`.sigstore.json`) |
| SOPS | 3.13.3 | encrypts the dotenv files in `secrets/`; the cloud workflows (plan, apply, drift, e2e-tunnel) download it with this sha256 to decrypt them | `sops-v3.13.3.linux.amd64` | `e5bec3346a873ae91d871550f3e698c1aad962aff462a080e40f25fde17fef6b` | `sops-v3.13.3.checksums.txt` of the [release](https://github.com/getsops/sops/releases/tag/v3.13.3), Sigstore bundle |
| age | 1.3.2 | keys for SOPS; encrypts the zone copies of `task dns-backup` | `age-v1.3.2-linux-amd64.tar.gz` | `cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10` | asset digest of the [release](https://github.com/FiloSottile/age/releases/tag/v1.3.2) and its `.proof` file |
| cloudflared | 2026.10.2 | `cloudflared access ssh` on the control node: the SSH check of `task e2e:tunnel` (`scripts/e2e_tunnel.sh` downloads it with this sha256), and SSH through the tunnel to a cloud server of `demo` or `showcase` (`task configure`, `task smoke`; the `apply` workflow downloads it with this sha256); the same release that the role `luminare.infra_edge.cloudflared` installs on the hosts | `cloudflared-linux-amd64` | `35fbdd2beb378436c7da377d7358cea8e33f9c94a6705d1d8036bf9b0d6d8005` | "SHA256 Checksums" in the notes of the [release](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.2), equal to GitHub's asset digest and the download checked on 2026-10-22 |
| Node.js | 24.22.0 | runs markdownlint-cli2 locally | `node-v24.22.0-linux-x64.tar.xz` | `cc2f601cee82d9a5a233302fe307abc600727035fd7d2c3a3571755989e95008` | [`SHASUMS256.txt`](https://nodejs.org/dist/v24.22.0/SHASUMS256.txt) (signed `SHASUMS256.txt.asc`) |

markdownlint-cli2 **0.23.2** is the version that CI's `DavidAnson/markdownlint-cli2-action`
v24.2.0 bundles. `task lint` runs it with `npx --yes markdownlint-cli2@0.23.2`; npm checks the
package against the registry's integrity value
(`sha512-eUhcnkSpzURo/o4htSqc7LPDszgOOTknhU4eY/sPHvMCLxnTCYscv1gw1/js/idmaZPisv9ECVEIORcllqjTUw==`).
CI runs the copy bundled in the action instead.

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
platform's archive. An environment locks the same versions as the modules it calls
(`tests/test_tofu.py` checks this).

| Provider | Constraint | Locked | Note |
|---|---|---|---|
| `bpg/proxmox` | `~> 0.114.0` | 0.114.0 | below 1.0, so patch releases only |
| `cloudflare/cloudflare` | `~> 5.25` | 5.28.1 | |
| `hetznercloud/hcloud` | `~> 1.69` | 1.70.0 | |
| `kreuzwerker/docker` | `~> 4.6` | 4.6.0 | |

`tofu test` and `tofu validate` also pass with the lowest version of each range
(`cloudflare` 5.25.0, `hcloud` 1.69.0), in the modules and in the environments. After a
constraint change, write the lock files again for both platforms, in every module and
environment that uses the provider:

```bash
tofu -chdir=tofu/modules/<module> providers lock -platform=linux_amd64 -platform=darwin_arm64
tofu -chdir=tofu/envs/<env> providers lock -platform=linux_amd64 -platform=darwin_arm64
```

`images/systemd-host/Dockerfile` (the host image of the `docker_host` module) starts from
`debian:trixie` and `ubuntu:24.04`, each pinned by digest.
Dependabot's `docker` ecosystem proposes new digests.

The hosts that `hcloud_vm` creates install cloudflared 2026.9.1 at first boot from its GitHub
release (`cloudflared-linux-amd64.deb`, sha256
`3be76adc4185d36a0bfb4c2dd8663292f0ed363797f2180333b513b43c81d419` from the release notes). Cloudflare's package
repository only has the newest release, so it cannot install a pinned version.

## What the roles download

The roles in `ansible/roles` download these files on the managed hosts, each checked against a
value pinned in the role. Dependabot does not see them; they are updated
by hand like the binary tools ([runbook](runbook.md#procedure-upgrade-node_exporter-or-uptime-kuma)).
`tests/test_ansible.py` fails when a checksum in the role defaults is missing on this page.

| What | Version | Pinned in | File or image | sha256 or digest | Checksum source |
|---|---|---|---|---|---|
| node_exporter | 1.12.1 | `monitoring` defaults | `node_exporter-1.12.1.linux-amd64.tar.gz` | `b51d8a76aa2a9156a55d501aca6276fae09e262259a5e4e831d2c2222f084e63` | `sha256sums.txt` of the [release](https://github.com/prometheus/node_exporter/releases/tag/v1.12.1), equal to GitHub's asset digest and the download |
| node_exporter | 1.12.1 | `monitoring` defaults | `node_exporter-1.12.1.linux-arm64.tar.gz` | `ad35b605f9954b9f1ffddf5ba054bdc5a98d790b9eae5291e1eeb83f1ecbd0e7` | the same |
| Uptime Kuma | 2.5.6 (`slim`) | `monitoring` defaults | `louislam/uptime-kuma:2.5.6-slim` | `sha256:5db97dbbef610276e1699f3ece586c3509c8fd35de75d45ff5109761a1b377dc` (image index, amd64 and arm64) | `docker buildx imagetools inspect` and Docker Hub |
| Docker's APT signing key | key `9DC8 5822 9FC7 DD38 854A E2D8 8D81 803C 0EBF CD88` | `docker` defaults | `https://download.docker.com/linux/{debian,ubuntu}/gpg` (the same file) | `1500c1f56fa9e26b9b8f42452a553675796ade0807cdce11975eb98170b3a570` | the downloaded file; fingerprint shown by `gpg --show-keys` |
| BusyBox (test image of the docker role's Molecule scenario) | 1.37 | `ansible/roles/docker/molecule/default/verify.yml` | `busybox:1.37` | `sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e` (image index) | `docker buildx imagetools inspect` |

Docker Engine itself comes from Docker's signed APT repository (newest `stable` release on the
first run), the other packages from the distribution.

## What the playbook downloads

`ansible/playbooks/site.yml` runs the roles of the collections in
[ansible/requirements.yml](../ansible/requirements.yml): `luminare.infra_edge` and
`luminare.gameserver` from their GitHub repositories at a release tag (git checks the commit the
tag points to), `devsec.hardening` 11.0.0 and `prometheus.prometheus` 0.30.2 from Ansible Galaxy
(`ansible-galaxy` checks each download against the sha256 that Galaxy publishes), and the other
community collections from the hash-pinned `ansible` package. The collections' roles pin their
own downloads (for example cloudflared, json_exporter and blackbox_exporter); their repositories
list them. The values of the `local` environment add one pin:

| What | Version | Pinned in | File | sha256 | Checksum source |
|---|---|---|---|---|---|
| Prometheus | 3.15.0 | `ansible/inventories/local/group_vars/monitoring.yml` (`site_prometheus_sha256`) | `prometheus-3.15.0.linux-amd64.tar.gz` | `2a542df32eac02ee17b9d844fb2aa1de00dafa5476579ba8a3ba862e9d572ea0` | `sha256sums.txt` of the [release](https://github.com/prometheus/prometheus/releases/tag/v3.15.0); `site.yml` checks the download against the pin before the `prometheus` role installs it, and the role against that file |

The game server of the `local` environment is never downloaded: it is the stand-in build of
`tests/fake-artifact/`, built on the control node.

## Python

Python **3.12** is the `python3` of the `ubuntu-24.04` runner and the oldest version
ansible-core 2.21 supports. Python 3.13 works too.

The table names the file that pins each package instead of repeating its version, so a
Dependabot update of a requirements file needs no edit on this page. `scripts/run_tests.sh`
installs the Ansible tools, checks their installed versions against the pins and runs
ansible-lint; the Molecule jobs of CI and `task molecule` use the same file.

| Package | Pinned in | Purpose |
|---|---|---|
| ansible-core | `requirements-test.in`, compiled into `requirements-test.txt` | Ansible controller |
| ansible | `requirements-test.in`, compiled into `requirements-test.txt` | the community collections (`community.docker`, `ansible.posix`, `community.sops`, ...) for ansible-lint, Molecule and the roles; `ansible/requirements.yml` pins the same versions |
| ansible-lint | `requirements-test.in`, compiled into `requirements-test.txt` | Ansible linter (production profile) |
| molecule | `requirements-test.in`, compiled into `requirements-test.txt` | role test framework |
| molecule-plugins (`docker` extra) | `requirements-test.in`, compiled into `requirements-test.txt` | Molecule Docker driver |
| yamllint | `requirements-dev.txt` | YAML lint (CI `ci / lint-test`, `task lint`) |
| zizmor | `requirements-dev.txt` | workflow security audit (CI `ci / lint-test`, `task lint`) |
| pip-tools | `pip-tools==7.5.2` in the compile command under [Updating a pin](#updating-a-pin) | compiles `requirements-test.txt`; not installed by the tasks |
| click | `click==8.2.1` in the same command | command-line library of pip-tools, held below 8.3 (see below) |

`requirements-test.txt` is generated from `requirements-test.in` by pip-compile and lists every
dependency with its hashes.
`requirements-dev.txt` comes from the template and is pinned by hand. Install either file with
`pip install --require-hashes --only-binary=:all: -r <file>`; `scripts/run_tests.sh` and
`task venv` do this.

## Hooks before a commit

`.pre-commit-config.yaml` runs the quick checks as git hooks: end-of-file and trailing-whitespace
fixes, shellcheck, gitleaks on the staged changes, yamllint, the check that every
`secrets/*.enc.env` is encrypted (`sops filestatus`), `tofu fmt`, TFLint and ansible-lint. It is
optional; CI runs the same checks in its own jobs. Install pre-commit (for example
`pipx install pre-commit`), run `task venv` and put `.venv/bin` on the PATH, then
`pre-commit install`. The hooks of other repositories are pinned to a commit SHA with the tag in a
comment (`pre-commit autoupdate --freeze` writes them so), and pre-commit installs them into its own
cache on the first run: pre-commit-hooks v6.0.0, shellcheck-py v0.11.0.1 (shellcheck 0.11.0) and the
`gitleaks-system` hook of gitleaks v8.30.1, which runs the gitleaks binary of the table above. The
other hooks run the tools of this page.

## Updating a pin

- **Python test tools:** Dependabot recompiles `requirements-test.txt` when a pinned package has
  a new release. To change the pins by
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
