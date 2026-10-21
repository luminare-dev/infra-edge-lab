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

## Still stuck?

Search the issues, then ask in the organization's
[Discussions](https://github.com/orgs/luminare-dev/discussions). Never post secrets, keys, IP
addresses, hostnames or player data; redact logs before you paste them.
