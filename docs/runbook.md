# Runbook

At this version the repository runs no service; the failures below are those of the repository's
own checks, of the OpenTofu checks (CI job `tofu`, `task tofu`) and of the environments' state
([ADR 0013](adr/0013-encrypted-state-in-r2-with-a-lock-file.md)).

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

## Failure: the state of an environment cannot be decrypted

| | |
|---|---|
| **Meaning** | `tofu plan` or `tofu apply` stops with `decryption failed for all provided methods` (with a local state file the message starts with `Error acquiring the state lock` and `failed to write backup file`). |
| **Impact** | Nothing can be planned or changed in that environment until the right passphrase is back; the resources themselves keep running. |
| **Diagnosis** | Check that `TF_VAR_state_passphrase` comes from the right SOPS file (`sops exec-env secrets/<env>.enc.env 'printenv TF_VAR_state_passphrase \| wc -c'` prints its length, not the value) and that `SECRETS` does not point at another environment's file. For `local`, a new random passphrase cannot read the state of an earlier run. |
| **Mitigation** | Use the passphrase from the offline copy. Never delete the state or turn off `enforced`. |
| **Fix** | With the passphrase lost for good, the state is gone: remove the resources by hand (`local`: the containers named `<name_prefix>local-*`, their network and image) or import them into a new state, then store the new passphrase in the SOPS file and offline. |

## Procedure: change the state passphrase

The state records which key provider encrypted it, so the passphrase changes in two runs with a
temporary second key provider, `next`, given in the `TF_ENCRYPTION` environment variable (which
OpenTofu merges with `encryption.tofu`); nothing is committed. Tested on 2026-10-21 with OpenTofu
1.13.1 on a local state file.

1. With the old passphrase in `TF_VAR_state_passphrase`, set `TF_ENCRYPTION` to a
   `key_provider "pbkdf2" "next"` with the new passphrase, a `method "aes_gcm" "next"` with
   `keys = key_provider.pbkdf2.next`, and
   `state { method = method.aes_gcm.next, enforced = true, fallback { method = method.aes_gcm.main } }`
   (each attribute on its own line). Run `tofu apply -refresh-only`: it reads the state with the
   old key and writes it with the new one.
2. Put the new passphrase into `TF_VAR_state_passphrase`, keep the `next` key provider and
   method in `TF_ENCRYPTION`, and swap the state block to
   `state { method = method.aes_gcm.main, enforced = true, fallback { method = method.aes_gcm.next } }`.
   Run `tofu apply -refresh-only` again: the state is now encrypted by `main` with the new
   passphrase.
3. Unset `TF_ENCRYPTION`, run `tofu plan` (it reports no changes), and replace the passphrase in
   the SOPS file and the offline copy.

## Failure: the state is locked

| | |
|---|---|
| **Meaning** | `tofu plan` or `tofu apply` stops with `Error acquiring the state lock`, naming a lock ID and, for the R2 backend, the lock object `<env>/terraform.tfstate.tflock`. |
| **Impact** | The run changes nothing. Another run holds the lock, or a run was killed while holding it. |
| **Diagnosis** | The message names who took the lock and when. Check for another terminal, a CI job or an `apply` waiting at its approval prompt. |
| **Mitigation** | Wait for the other run to end. |
| **Fix** | Only when no run is active: `tofu -chdir=tofu/envs/<env> force-unlock <lock ID>`. Whether R2 enforces the lock is not tested yet (see the README's limitations); until it is, only one operator applies at a time. |

## Failure: an environment plans against the wrong state

| | |
|---|---|
| **Meaning** | `task plan ENV=<env>` prints `note: <env> plans against its local state file`, or proposes to create resources that exist. |
| **Impact** | A plan against an empty local state would create a second copy of every resource if applied. |
| **Diagnosis** | `ls tofu/envs/<env>/backend_override.tf`: the file is there after `task init ENV=<env> BACKEND=local`. |
| **Mitigation** | Do not apply that plan. |
| **Fix** | `task init ENV=<env>` (without `BACKEND=local`) removes the override file and switches back to the remote state. |
