# Upgrading

Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Before 1.0.0 a minor
release may contain breaking changes; they are listed under "BREAKING CHANGES" in the
[changelog](../CHANGELOG.md).

## General steps

1. Read the changelog entries between your version and the new one, and the version notes below.
2. Back up what the project changes: keep the state passphrase of each environment (its state is
   encrypted in its backend), and run the [restore test](runbook.md#procedure-test-a-restore) on
   the hosts before a change that touches them.
3. Check out the new release tag (or download the release and verify its checksum, see
   [Installation](install.md#verify-the-release-download)), run `task venv`, and install the
   collections again when `ansible/requirements.yml` changed (below).
4. Run `task test` and `task e2e:local`; both must pass before an environment with real hosts is
   planned (`task plan ENV=<env>`) and applied.

## The pinned collections

`luminare.infra_edge` and `luminare.gameserver` are pinned to a release tag in
`ansible/requirements.yml`, and the community collections to exact versions
([ADR 0016](adr/0016-collections-from-git-tags-and-one-pinned-bundle.md)). To move to a new tag:

1. Read the collection's changelog between the two tags.
2. Change `version:` of the collection in `ansible/requirements.yml` and the tag in the README's
   "Supported versions" table (a unit test keeps both equal).
3. Remove the installed copy and install again, so that the new tag replaces the old one:

   ```bash
   rm -rf ansible/collections/ansible_collections/luminare
   task collections
   ```

4. Run `task e2e:local` (both playbook runs and the smoke test must pass), then
   `task configure ENV=<env>` for the environments with real hosts.

To try a change of a collection before it is tagged, build it from a local checkout and point
`ANSIBLE_COLLECTIONS_PATH` at the result; `task e2e:local` then uses it instead of the tags (on a
workstation only; CI always installs the tags):

```bash
ansible-galaxy collection build ../ansible-collection-infra_edge --output-path /tmp/collections-dist
ansible-galaxy collection build ../ansible-collection-gameserver --output-path /tmp/collections-dist
ansible-galaxy collection install /tmp/collections-dist/*.tar.gz -p /tmp/collections
ansible-galaxy collection install devsec.hardening:11.0.0 prometheus.prometheus:0.30.2 -p /tmp/collections
ANSIBLE_COLLECTIONS_PATH=/tmp/collections task e2e:local
```

An update of the `ansible` package in `requirements-test.txt` (Dependabot) changes the bundled
community collections: set their versions in `ansible/requirements.yml` to the new ones; the
[runbook](runbook.md#failure-a-dependabot-pull-request-fails-ci) explains the failing test.

## Tools, providers and images

- OpenTofu providers: Dependabot proposes new constraints and lock files; read the provider's
  changelog, then run `task tofu` ([ADR 0012](adr/0012-provider-pins-and-lock-files.md)). A new
  major version of a provider, and every release of `bpg/proxmox` below 1.0, also needs a plan of
  each environment that uses it before it is merged.
- Binary tools (OpenTofu, TFLint, Terraform, Trivy, go-task, gitleaks, actionlint, SOPS, age,
  cloudflared): change the version and sha256 in [toolchain.md](toolchain.md) and wherever the
  tool is downloaded (the workflow inputs, `scripts/install_tofu_tools.sh`,
  `scripts/e2e_tunnel.sh`); the unit tests fail until every copy agrees.
- The host image: Dependabot updates the base image digests in
  `images/systemd-host/Dockerfile`; `task tofu` (the `docker_host` integration test) and
  `task molecule` build it again.
- node_exporter and Uptime Kuma: see the
  [runbook](runbook.md#procedure-upgrade-node_exporter-or-uptime-kuma).
- The state passphrase: see the [runbook](runbook.md#procedure-change-the-state-passphrase).

## Version notes

No version needs manual steps so far.
