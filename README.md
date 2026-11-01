<!-- header:begin: the project page on luminare.tech drops this block, because the page has its own heading -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/brand/readme-header-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/brand/readme-header-light.svg">
  <img alt="infra-edge-lab" src="docs/brand/readme-header-light.svg">
</picture>

<!-- byline:studio -->
*a [Luminare Development](https://luminare.tech/open-source/infra-edge-lab/) open-source project*
<!-- /byline:studio -->
<!-- byline:personal
*by ItsPaulAT · [project page](https://luminare.tech/open-source/infra-edge-lab/)*
/byline:personal -->
<!-- header:end -->

# infra-edge-lab

Infrastructure as code that rebuilds a small edge environment from nothing with one command, tested on every change.

[![ci](https://github.com/luminare-dev/infra-edge-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/luminare-dev/infra-edge-lab/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/luminare-dev/infra-edge-lab?sort=semver)](https://github.com/luminare-dev/infra-edge-lab/releases)
[![licence](https://img.shields.io/github/license/luminare-dev/infra-edge-lab)](LICENSE)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/luminare-dev/infra-edge-lab/badge)](https://scorecard.dev/viewer/?uri=github.com/luminare-dev/infra-edge-lab)

![task e2e:local: three hosts created, configured twice with no change on the second run, smoke-tested, restore-tested and destroyed](docs/media/e2e-local.gif)

## Quick start

```bash
git clone https://github.com/luminare-dev/infra-edge-lab.git
cd infra-edge-lab
task test
task e2e:local
```

This needs go-task, Python 3.12 or 3.13 with `venv`, git, OpenTofu and a Docker daemon that
allows privileged containers, but no account and no secret ([docs/install.md](docs/install.md)).
`task e2e:local` creates `edge-01`, `db-01` and `fx-01` as systemd containers, configures them
twice (the second run must change nothing), smoke-tests them, tests a backup restore and
destroys them again. CI runs the same on every pull request.

## How it works

OpenTofu creates the hosts, the Cloudflare tunnel, its DNS records and the Access applications;
every environment returns the same `hosts` output, which `scripts/render_inventory.py` turns into
an Ansible inventory. `ansible/playbooks/site.yml` then configures every environment with the
`luminare.infra_edge` and `luminare.gameserver` collections and the roles in `ansible/roles`.
Credentials live in SOPS files and reach a command only through its environment.

| Environment | Hosts | Status |
|---|---|---|
| `local` | `edge-01`, `db-01`, `fx-01` as systemd containers on the local Docker daemon | rebuilt by CI on every pull request |
| `lab` | Proxmox VE virtual machines behind a tunnel and Access | validated and tested with mocked providers, not applied yet |
| `demo` | one throw-away cloud server, or a container for the tunnel test | validated and tested with mocked providers, not applied yet |
| `showcase` | one protected long-lived cloud server (skeleton) | validated and planned offline, not applied yet |

The environments never touch hosts they did not create, and in the shared DNS zone they may only
write names with their own prefix. The cloud workflows (`plan`, `apply`, `drift`, `e2e-tunnel`)
stay off until the repository variable `CLOUD_ENVS_ENABLED` is set
([runbook](docs/runbook.md#procedure-turn-on-the-cloud-workflows)).

Modules: [tofu/modules](tofu/modules) (each has a README). Environments:
[tofu/envs/README.md](tofu/envs/README.md). Roles: [ansible/roles](ansible/roles).

## Supported versions

| Component | Tested with | Supported |
|---|---|---|
| Python (tests and checks) | 3.12, 3.13 | 3.12, 3.13 |
| Managed hosts | Debian 13, Ubuntu 24.04 (x86_64) | Debian 13, Ubuntu 24.04 |
| `luminare.infra_edge` | `v0.2.1` | the tag pinned in `ansible/requirements.yml` |
| `luminare.gameserver` | `v0.2.0` | the tag pinned in `ansible/requirements.yml` |
| go-task | 3.54.0 | 3.54.0 |
| OpenTofu | 1.13.1 | 1.13.1 (`required_version = ">= 1.11.0"`) |
| Docker Engine | 29.2.1 | versions that run privileged containers in the host cgroup namespace |

Every other tool and its checksum is in [docs/toolchain.md](docs/toolchain.md).

## Limitations

- `lab`, `demo` and `showcase` have only been validated, tested with mocked providers and
  planned offline; nothing has been applied to Proxmox VE, Hetzner Cloud or R2 yet, and the live
  tunnel test has not run.
- `local` runs a stand-in game server build (`tests/fake-artifact/`), on containers rather than
  machines. Ubuntu 24.04 is tested per role with Molecule only; arm64 is not tested.
- Prometheus evaluates alerts but nothing delivers them yet (no Alertmanager, no Grafana).
- The repository ships no encrypted secrets and no `.sops.yaml` recipients: bring your own keys
  ([docs/configuration.md](docs/configuration.md#secrets)).

## Documentation

- [Installation](docs/install.md) · [Configuration](docs/configuration.md) ·
  [Upgrade](docs/upgrade.md) · [Troubleshooting](docs/troubleshooting.md) ·
  [Runbook](docs/runbook.md) · [Toolchain](docs/toolchain.md)
- Development: `task lint`, `task test`, `task tofu` and `task molecule` run the CI checks;
  `pre-commit install` runs the quick ones before each commit.
- [Changelog](CHANGELOG.md) and [releases](https://github.com/luminare-dev/infra-edge-lab/releases)
  (with `SHA256SUMS` and a build provenance attestation)
- [Contributing](https://github.com/luminare-dev/.github/blob/main/CONTRIBUTING.md) ·
  [Code of conduct](https://github.com/luminare-dev/.github/blob/main/CODE_OF_CONDUCT.md) ·
  [Security](https://github.com/luminare-dev/.github/blob/main/SECURITY.md) ·
  [Support](https://github.com/luminare-dev/.github/blob/main/SUPPORT.md)
- Project page: <https://luminare.tech/open-source/infra-edge-lab/>

## Not affiliated

Not affiliated with or endorsed by Cfx.re, Rockstar Games or Take-Two.

## Licence

[Apache-2.0](LICENSE). The licence covers the code only: the project name, logo, header images
and `docs/brand/` are not licensed (see [NOTICE](NOTICE)).

<!-- byline:studio -->
*a [Luminare Development](https://luminare.tech/open-source/infra-edge-lab/) open-source project*
<!-- /byline:studio -->
<!-- byline:personal
*by ItsPaulAT · [project page](https://luminare.tech/open-source/infra-edge-lab/)*
/byline:personal -->
