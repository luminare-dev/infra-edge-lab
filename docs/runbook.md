# Runbook

At this version the repository runs no service; the failures below are those of the repository's
own checks and of the OpenTofu checks (CI job `tofu`, `task tofu`).

## Failure: the secret scan finds a secret

| | |
|---|---|
| **Meaning** | `secrets / gitleaks` (or `task lint`) found something that looks like a credential in a commit or the working tree. |
| **Impact** | If the commit was pushed, the value must be treated as public, whatever the visibility of the repository. |
| **Diagnosis** | `gitleaks git --redact --config .gitleaks.toml .` names the rule, file and commit; `git show <commit> -- <file>` shows the line. A value inside a SOPS file is fine only if it starts with `ENC[`. |
| **Mitigation** | Revoke or rotate the credential at its provider first, before anything else. |
| **Fix** | Remove the value from the branch (rewrite the commits before merging, or open an issue to purge merged history), move it into an encrypted file in `secrets/`, and add a test or allowlist entry only for a proven false positive. |

## Failure: the hash-pinned install fails

| | |
|---|---|
| **Meaning** | `scripts/run_tests.sh` or `task venv` stopped in `pip install --require-hashes`, for example with `THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE`. |
| **Impact** | `ci / lint-test` and the release build fail; no tests run. |
| **Diagnosis** | Read which package and file pip names. Check the Python version (3.12 or 3.13) and the platform (Linux x86_64): another interpreter may need a distribution file the requirements do not list. |
| **Mitigation** | Run with Python 3.12, the version the files are compiled for. |
| **Fix** | Never copy a new hash from the error message. Recompile `requirements-test.txt` as in [toolchain.md](toolchain.md) and review the diff: a changed hash for an unchanged version means the file on PyPI changed and needs an explanation before it is accepted. |

## Failure: a Dependabot pull request fails CI

| | |
|---|---|
| **Meaning** | A dependency update breaks a check or a test. |
| **Impact** | The update waits; the current pins stay in use. |
| **Diagnosis** | Open the failed job; compare the release notes of the updated dependency. A version copied into the docs is not the cause: `tests/test_toolchain.py` keeps the Python versions in the requirements files only. |
| **Mitigation** | Leave the pull request open or close it; Dependabot proposes the next version later. |
| **Fix** | Adapt the code in the same pull request, or pin around the broken version with a comment that names the issue. |

## Failure: the zone guard rejects a name or a record

| | |
|---|---|
| **Meaning** | `tofu test` or `tofu plan` fails with a validation error of `cf_tunnel` or `cf_access_app`, for example "Every dns_names entry must be a first-level label with the prefix of env". |
| **Impact** | Nothing reaches Cloudflare: the plan stops before any API call. This is the guard working ([ADR 0009](adr/0009-guard-rails-for-a-shared-dns-zone.md)). |
| **Diagnosis** | The error names the variable. Compare the name with the rules in the [cf_tunnel README](../tofu/modules/cf_tunnel/README.md#name-rules): prefix of the environment, first level only, lower case, not reserved; A/AAAA records in `showcase` only. |
| **Mitigation** | Use a name with the environment's prefix (`lab-`, `demo-`, `show-`). |
| **Fix** | Change the name, never the guard. A change of the rules themselves needs a new ADR and new tests in both modules. |

## Failure: `tofu init` reports that a provider does not match the lock file

| | |
|---|---|
| **Meaning** | `scripts/check_tofu.sh` runs `tofu init -lockfile=readonly`; a constraint in `versions.tf` and the module's `.terraform.lock.hcl` disagree, or a downloaded provider has another checksum than the lock file. |
| **Impact** | The CI job `tofu` fails; no test runs. |
| **Diagnosis** | Read which provider OpenTofu names. Compare `versions.tf` with the `constraints` line of the lock file. A checksum mismatch for an unchanged version means the registry served another file and needs an explanation. |
| **Mitigation** | Keep the previous constraint and lock file. |
| **Fix** | Write the lock file again for both platforms ([toolchain.md](toolchain.md#opentofu-providers-and-the-host-image)) and review its diff. |

## Failure: the IaC security scan reports a finding

| | |
|---|---|
| **Meaning** | The `iac` step of `scripts/check_tofu.sh` (CI job `tofu`, `task tofu`) failed: `trivy config` found a misconfiguration in `tofu/` or `images/` that `.trivyignore.yaml` does not list. |
| **Impact** | The CI job `tofu` fails; nothing was applied. |
| **Diagnosis** | The output names the check ID (for example `DS-0002`), its severity and the file, with a link to the description of the check. |
| **Mitigation** | Keep the previous code. |
| **Fix** | Change the code so that the check passes. Add an entry to `.trivyignore.yaml` (ID, path relative to the scanned folder, statement) only for a finding that the design needs, with the reason in its statement; `tests/test_tofu.py` refuses an entry without one. |

## Failure: the `docker_host` integration test leaves containers behind

| | |
|---|---|
| **Meaning** | The test was interrupted (for example with Ctrl-C) before its own destroy step. |
| **Impact** | Containers, a network and an image named `lab-it-…` stay on the Docker daemon; the next run fails because the names exist. |
| **Diagnosis** | `docker ps -a --filter name=lab-it-`, `docker network ls --filter name=lab-it-`, `docker image ls 'lab-it-*'`. |
| **Mitigation** | Remove exactly those objects: `docker rm -f` with the listed containers, then `docker network rm` and `docker image rm` with the listed names. |
| **Fix** | Run the test again; it ends with a destroy of everything it created. |
