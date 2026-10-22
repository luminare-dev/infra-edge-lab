# Troubleshooting

## `The virtual environment was not created successfully because ensurepip is not available`

**Cause:** Debian and Ubuntu ship the `venv` module of Python in a separate package.

**Fix:**

```bash
sudo apt install python3-venv
task venv
```

## `ERROR: Could not find a version that satisfies the requirement ansible-core==…`

**Cause:** ansible-core 2.21 needs Python 3.12 or later, and `--only-binary=:all:` allows wheels
only. An older `python3` finds no matching file.

**Fix:** install Python 3.12 or 3.13 and create the environment with it:

```bash
rm -rf .venv
python3.12 -m venv .venv
task venv
```

## `@name: repository name '…' contains the mark …` from `forbidden_words.py`

**Cause:** the clone has no `origin` remote, so the name check falls back to the folder name.

**Fix:** name the repository explicitly:

```bash
GITHUB_REPOSITORY=luminare-dev/infra-edge-lab python3 scripts/forbidden_words.py
```

## `task: Failed to run task "lint"` after `npx --yes markdownlint-cli2@0.23.2`

**Cause:** Node.js is missing or too old for markdownlint-cli2, or npm cannot reach the registry.

**Fix:** install Node.js 24.22.0 as described in [toolchain.md](toolchain.md) and run `task lint`
again.

## `install_tofu_tools.sh: the pinned downloads are for Linux x86_64`

**Cause:** the script and the sha256 values in [toolchain.md](toolchain.md) are for Linux x86_64
only.

**Fix:** install OpenTofu, TFLint and Trivy in the versions of [toolchain.md](toolchain.md) from
their release pages, after checking each download against the release's checksum file.

## The `docker_host` integration test fails while it waits for a container to become healthy

**Cause:** systemd did not finish booting in the container: the Docker daemon does not allow
privileged containers, the host does not share its cgroup tree (rootless Docker, some container
runtimes), or the host is slow.

**Fix:** run the test on a Docker daemon that allows privileged containers with the host cgroup
namespace, or skip that step: `task tofu STEPS='fmt validate tflint iac test compat'`. On a slow host
raise the module's `wait_timeout`.

## `TF_VAR_state_passphrase must hold the state passphrase`, `depends on var.state_passphrase which is not available` or `Failed to request input from user for variable var.state_passphrase`

**Cause:** every environment encrypts its state and plan files, so `tofu init`, `tofu plan` and
`tofu apply` need the passphrase, at least 16 characters. `tofu test` gets a fixed one from the
test files and needs none.

**Fix:** for `lab`, `demo` and `showcase`, put `TF_VAR_state_passphrase` into
`secrets/<env>.enc.env`, which `task init` and `task plan` read. For `local`, export a random one
per run:

```bash
export TF_VAR_state_passphrase="$(openssl rand -base64 32)"
task init ENV=local
```

## `AWS_ENDPOINT_URL_S3 must hold the endpoint of the state bucket`

**Cause:** `task init` or `task plan` would use the remote backend of `lab`, `demo` or
`showcase`, but the endpoint of the bucket is not set. Without it the S3 backend sends its
requests to AWS instead of R2, so the script stops first.

**Fix:** add `AWS_ENDPOINT_URL_S3=https://<account_id>.r2.cloudflarestorage.com` to
`secrets/<env>.enc.env` (`sops edit secrets/<env>.enc.env`), or work on a local state file with
`task init ENV=<env> BACKEND=local`.

## `Backend initialization required` after switching `BACKEND`

**Cause:** the environment was initialised for the other backend (the remote one or
`BACKEND=local`).

**Fix:** run `task init ENV=<env>` again with the backend you want; it runs
`tofu init -reconfigure`.

## ansible-lint: `couldn't resolve module/action 'community.docker.docker_container'`

**Cause:** ansible-lint runs outside the virtual environment of `requirements-test.txt`, whose
`ansible` package brings the community collections, or an older copy of a collection in
`~/.ansible/collections` comes first in the collection path.

**Fix:** run it through `task test` (or `bash scripts/run_tests.sh`), which installs the pinned
tools and puts them first on the `PATH`. Remove an outdated copy with
`rm -r ~/.ansible/collections/ansible_collections/community/docker` if nothing else needs it.

## `ansible-galaxy collection install -r requirements.yml` fails to clone a luminare collection

**Cause:** the luminare collections are installed from their GitHub repositories at a release
tag (`type: git`). The clone fails when the tag does not exist yet, when the repository is not
readable from this machine, or without `git`.

**Fix:** check that `git ls-remote https://github.com/luminare-dev/ansible-collection-infra_edge.git v0.2.0`
prints the tag. The unit tests and ansible-lint never install these collections, so they are not
affected; `task collections`, `task e2e:local` and the CI workflow `e2e-local` are. To run the
playbooks with collections built from local checkouts instead, install those into a folder of
your own and point `ANSIBLE_COLLECTIONS_PATH` at it; `task e2e:local` then skips the install:

```bash
ansible-galaxy collection build ../ansible-collection-infra_edge --output-path /tmp/collections-dist
ansible-galaxy collection build ../ansible-collection-gameserver --output-path /tmp/collections-dist
ansible-galaxy collection install /tmp/collections-dist/*.tar.gz -p /tmp/collections
ansible-galaxy collection install devsec.hardening:11.0.0 prometheus.prometheus:0.30.2 -p /tmp/collections
ANSIBLE_COLLECTIONS_PATH=/tmp/collections task e2e:local
```

## ansible-lint: `The role 'luminare.infra_edge.<role>' was not found`

**Cause:** the playbooks name roles of the luminare collections, which ansible-lint mocks
(`mock_roles` in `.ansible-lint`) because it runs offline. An older copy of such a collection in
the collection path (for example `~/.ansible/collections/ansible_collections/luminare/`) takes
precedence over the mock, and a role it lacks is then missing.

**Fix:** remove that copy if nothing else needs it, or run ansible-lint with a collection path
without it (CI has none). A role added to `site.yml` needs a `mock_roles` entry;
`tests/test_playbooks.py` checks the list.

## `task e2e:local`: `tofu/envs/local/terraform.tfstate is left from an earlier run`

**Cause:** an earlier run (or `task up ENV=local`) was not destroyed. Its state is encrypted with
that run's passphrase, which the new run does not know, and its containers may still exist.

**Fix:** destroy it with its passphrase (`TF_VAR_state_passphrase=<passphrase> task destroy
ENV=local`). If the passphrase is lost and `docker ps -a --filter name=lab-local-` lists nothing,
delete `tofu/envs/local/terraform.tfstate` and `terraform.tfstate.backup`; otherwise remove the
containers, the network `lab-local` and the image `lab-systemd-host-*` first.

## `task e2e:local`: `the second run changed something`

**Cause:** a task reports a change on every run, so the playbook is not idempotent; the lines
starting with `changed:` before the message name the tasks.

**Fix:** make the task idempotent in its role (in this repository or in the collection it comes
from), never by adding `changed_when: false` to a task that really changes something. A
service that a role starts again on the second run was stopped by something in the first run:
read its journal (`docker exec lab-local-<host> journalctl -u <service>`).

## `Temporary failure resolving '<host>'` in the local environment after the base role

**Cause:** the base role's firewall starts with `flush ruleset`, which also removes the NAT rules
through which a container reaches Docker's DNS server, and the drop-in
`/etc/nftables.d/05-local-container-dns.nft` that puts them back is missing (the playbook ran
without `playbooks/local_prepare.yml`).

**Fix:** run `task configure ENV=local`, which runs `local_prepare.yml` first, or run that
playbook and then `systemctl restart nftables` in the container
([ADR 0022](adr/0022-an-end-to-end-run-of-the-local-environment-on-every-pull-request.md)).

## Molecule: a scenario stops for about two minutes when it starts Docker or node_exporter

**Cause:** the instance was built from an image in which `systemd-networkd-wait-online.service`
is active: in a container it finds no interface to wait for and holds every unit ordered after
`network-online.target` until it times out.

**Fix:** build the instances from `images/systemd-host/Dockerfile`, which masks that unit
(`.config/molecule/config.yml` does this); remove an old `molecule_local/lab-molecule-*` image so
that it is built again.

## Molecule: `failed to mount ... fstype: overlay ... invalid argument` in the docker or monitoring scenario

**Cause:** Docker inside the instance cannot place its overlay storage on the instance's own
overlay root file system.

**Fix:** keep the tmpfs mounts of `/var/lib/docker` and `/var/lib/containerd` (with `exec`) in
`.config/molecule/config.yml`; they need about 1 GB of free memory while the monitoring scenario
runs Uptime Kuma.

## Molecule: `The container name "/lab-<role>-<platform>" is already in use`

**Cause:** two runs of the same role's scenario at the same time on one machine, for example
`--platform-name lab-docker-debian13` and `--platform-name lab-docker-ubuntu2404` in two
terminals. Molecule keeps one state per scenario on the machine, so one run acts on the
other run's instance. (CI runs each role and platform on its own runner.)

**Fix:** run the platforms of one role one after the other, or both in one run
(`task molecule ROLE=<role>`); `molecule destroy` in `ansible/roles/<role>` (with
`MOLECULE_ROLE=<role>`) removes the leftovers. Scenarios of different roles can run at the same
time.

## The docker role stops with `Remove docker.io ... first`

**Cause:** a Docker package of the distribution (`docker.io`, `containerd`, `runc`,
`podman-docker`, ...) is installed; it conflicts with Docker's own packages. The role does not
remove it, because that would stop its containers.

**Fix:** move or stop those containers, then `sudo apt-get purge docker.io containerd runc` (the
packages the message names) and run the role again.

## An upload with the deploy key fails

**Cause and fix**, by the message of `ssh` or `rsync`:

- `Permission denied (publickey)`: the key is not in `deploy_target_authorized_keys`, the
  connection does not come from an address in its `from` list (through a tunnel it comes from
  127.0.0.1 or ::1), or the upload account is not in the SSH group of `AllowGroups`
  (`deploy_target_ssh_groups`).
- `rrsync error: reading from write-only server is not allowed`, `SSH_ORIGINAL_COMMAND does not
  run rsync` or `option --delete... has been disabled on this server`: the key can only write
  into the spool directory with rsync, without deleting; send the files to `deploy@<host>:` with
  plain `rsync` options (`--perms --chmod=F640`).
- The upload succeeds but nothing deploys: the `.ready` marker is missing (it must be sent last,
  in a second rsync call) or the path unit has stopped; see the [runbook](runbook.md).

## Still stuck?

Search the issues, then ask in the organization's
[Discussions](https://github.com/orgs/luminare-dev/discussions). Never post secrets, keys, IP
addresses, hostnames or player data; redact logs before you paste them.
