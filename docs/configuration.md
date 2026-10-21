# Configuration

The inputs and outputs of the four environments (`local`, `lab`, `demo`, `showcase`) are listed
in [tofu/envs/README.md](../tofu/envs/README.md), those of the OpenTofu modules in each module's
README: [pve_vm](../tofu/modules/pve_vm/README.md),
[hcloud_vm](../tofu/modules/hcloud_vm/README.md),
[cf_tunnel](../tofu/modules/cf_tunnel/README.md),
[cf_access_app](../tofu/modules/cf_access_app/README.md) and
[docker_host](../tofu/modules/docker_host/README.md). The zone is always an input (`zone`), never
a value in the code. An environment reads its inputs from `TF_VAR_*` environment variables (from
its SOPS file) or from a `*.auto.tfvars` file next to it, which git ignores; examples use
`example.com` and the documentation ranges.

The options below change how the tasks, checks and tests run.

| Option | Type | Default | Description |
|---|---|---|---|
| `VENV` (Taskfile variable, `task lint VENV=path`) | path | `.venv` | Python virtual environment that `task venv`, `task lint` and `task test` use. |
| `TEST_VENV` (environment variable) | path | `$RUNNER_TEMP/venv-test` in CI, else `.venv` | Virtual environment into which `scripts/run_tests.sh` installs `requirements-test.txt` before it runs the unit tests. |
| `GITHUB_REPOSITORY` (environment variable) | `owner/name` | the `origin` remote | Repository name for the name check of `scripts/forbidden_words.py`; set it when the clone has no `origin` remote. |
| `STEPS` (Taskfile variable, `task tofu STEPS='fmt test'`) | list of steps | `all` | Steps of `scripts/check_tofu.sh`: `fmt`, `validate`, `tflint`, `iac` (Trivy), `test`, `integration` (needs Docker), `compat`, or `all`. |
| `TF_PLUGIN_CACHE_DIR` (environment variable) | path | unset; `$RUNNER_TEMP/tofu-plugin-cache` in CI | Shared provider cache for `scripts/check_tofu.sh`; the providers are still checked against each lock file. |
| `ENV` (Taskfile variable, `task init ENV=lab`) | `local`, `lab`, `demo` or `showcase` | none; required by `init` and `plan` | Environment under `tofu/envs/` for `task init`, `task plan` and `task test` (`task test` without `ENV` runs the unit tests). |
| `BACKEND` (Taskfile variable, `task init ENV=lab BACKEND=local`) | `remote` or `local` | `remote` | `local` keeps the state of `lab`, `demo` or `showcase` in a local file (still encrypted) through a git-ignored `backend_override.tf`; `remote` removes that file again. |
| `SECRETS` (environment variable) | path | `secrets/<env>.enc.env` | SOPS file that `task init` and `task plan` read with `sops exec-env` when it exists, for example `secrets/lab-ci.enc.env` for a read-only plan. |
| `TF_VAR_state_passphrase` (environment variable) | string, at least 16 characters | none; required | Passphrase of the state and plan encryption ([ADR 0013](adr/0013-encrypted-state-in-r2-with-a-lock-file.md)); from the SOPS file, or a random one per run for `local`. |
| Arguments after `--` (`task plan ENV=lab -- -out=lab.tfplan`) | OpenTofu arguments | none | Passed on to `tofu init` or `tofu plan`. |

## Secrets

Secrets never go into this repository, an issue or a log. CI scans every commit with gitleaks; a
leaked secret is rotated first and removed from history second.

Credentials for an environment are kept in SOPS-encrypted dotenv files in `secrets/`
([ADR 0006](adr/0006-sops-and-age-for-secrets.md), [secrets/README.md](../secrets/README.md)).
At this version the repository ships none of them and no `.sops.yaml` yet. The keys a file can
hold:

| Key | Read by | Notes |
|---|---|---|
| `PROXMOX_VE_ENDPOINT`, `PROXMOX_VE_API_TOKEN`, `PROXMOX_VE_API_HEADERS` | bpg/proxmox provider | API token with privilege separation; extra headers for an access proxy in front of the API |
| `CLOUDFLARE_API_TOKEN`, `TF_VAR_account_id`, `TF_VAR_zone_id` | cloudflare/cloudflare provider | token limited to one zone |
| `TF_VAR_zone`, `TF_VAR_access_team_name`, `TF_VAR_allowed_emails` | `lab`, `demo`, `showcase` | the zone, the Zero Trust team name and who may log in (JSON list) |
| `TF_VAR_ssh_keys`, `TF_VAR_ssh_public_key` | `lab` (JSON list), `demo` and `showcase` (one key line) | public keys of the admin user |
| `HCLOUD_TOKEN` | hetznercloud/hcloud provider | token of a project that holds nothing but this lab |
| `AWS_ENDPOINT_URL_S3`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | S3-compatible state backend | the account's endpoint (`https://<account_id>.r2.cloudflarestorage.com`) and a token for the state bucket only |
| `TF_VAR_state_passphrase` | state and plan encryption | at least 16 characters; kept offline as well, since a lost passphrase means a lost state |

To create a file: generate an age key (`age-keygen -o ~/.config/sops/age/keys.txt`), add its
public key to the creation rules in `.sops.yaml` at the repository root (a committed file that
holds public keys only), then run `sops edit secrets/<env>.enc.env`.
Use the file only through `sops exec-env secrets/<env>.enc.env '<command>'`; `task init` and
`task plan` do this themselves when the file exists.
