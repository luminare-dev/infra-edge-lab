# Configuration

At this version the repository has no environment to configure yet; the options below change how
the checks and tests run.

| Option | Type | Default | Description |
|---|---|---|---|
| `VENV` (Taskfile variable, `task lint VENV=path`) | path | `.venv` | Python virtual environment that `task venv`, `task lint` and `task test` use. |
| `TEST_VENV` (environment variable) | path | `$RUNNER_TEMP/venv-test` in CI, else `.venv` | Virtual environment into which `scripts/run_tests.sh` installs `requirements-test.txt` before it runs the unit tests. |
| `GITHUB_REPOSITORY` (environment variable) | `owner/name` | the `origin` remote | Repository name for the name check of `scripts/forbidden_words.py`; set it when the clone has no `origin` remote. |

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
| `HCLOUD_TOKEN` | hetznercloud/hcloud provider | token of a project that holds nothing but this lab |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | S3-compatible state backend | |
| `TF_VAR_state_passphrase` | state and plan encryption | at least 16 characters |

To create a file: generate an age key (`age-keygen -o ~/.config/sops/age/keys.txt`), add its
public key to the creation rules in `.sops.yaml` at the repository root (a committed file that
holds public keys only), then run `sops edit secrets/<env>.enc.env`.
Use the file only through `sops exec-env secrets/<env>.enc.env '<command>'`.
