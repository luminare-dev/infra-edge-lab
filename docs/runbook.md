# Runbook

The failures below are those of the repository's own checks, of the OpenTofu checks (CI job
`tofu`, `task tofu`) and of the environments' state
([ADR 0013](adr/0013-encrypted-state-in-r2-with-a-lock-file.md)), then of building and checking
an environment (`task up`, `task e2e:local`), followed by the services that the roles in
`ansible/roles` set up on a host: Docker, node_exporter, Uptime Kuma and the deploy target. The
services of the collections' roles have runbooks in their own repositories.

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
| **Fix** | Adapt the code in the same pull request, or pin around the broken version with a comment that names the issue. An update of the `ansible` package always needs one edit: set the community collections in `ansible/requirements.yml` to the versions the new package bundles; `tests/test_ansible.py` names each one ([ADR 0016](adr/0016-collections-from-git-tags-and-one-pinned-bundle.md)). |

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

## Procedure: rebuild an environment from nothing

1. For `lab` and `demo`, export the zone's DNS records first (the operational safety net of
   [ADR 0009](adr/0009-guard-rails-for-a-shared-dns-zone.md)); no task does this at this version.
2. Install the collections once: `task collections`.
3. `task rebuild ENV=<env>`: destroy, then init, apply, inventory, configure and smoke; it prints
   how long it took. `lab` and `demo` ask before the destroy and the apply unless
   `AUTO_APPROVE=1`; `local` needs `TF_VAR_state_passphrase` (a new random one when nothing of
   it exists). `showcase` is refused: it is taken down by hand only
   ([ADR 0014](adr/0014-one-root-module-per-environment.md)).
4. Read the smoke test at the end: every nginx site 200, MariaDB `SELECT 1`, `/info.json` with
   the build, every Prometheus target up.

`task e2e:local` does the same for `local` with a random passphrase, runs the playbook twice and
plans again, and always destroys at the end
([ADR 0022](adr/0022-an-end-to-end-run-of-the-local-environment-on-every-pull-request.md)).

## Failure: the e2e run or the smoke test fails

| | |
|---|---|
| **Meaning** | `task e2e:local` (or the CI job `e2e-local`) ends with `Result: failed at "<step>"`, or `task smoke` fails a check. |
| **Impact** | The change is not proven to rebuild the environment; the e2e run has already destroyed its containers. |
| **Diagnosis** | The step names the cause: `tofu apply` (Docker, the host image), `collections` (the git tags, see [troubleshooting](troubleshooting.md)), `configure` (the failed task and host in the log; set `E2E_LOG_DIR` to keep both playbook logs), `second run` (a task that is not idempotent), `tofu plan` (a resource that drifts after its apply), `smoke` (the check and host). To look inside, run the steps one by one: `task up ENV=local`, then `docker exec lab-local-<host> journalctl -u <service>`. |
| **Mitigation** | `task destroy ENV=local` with the same `TF_VAR_state_passphrase` removes what a manual run left. |
| **Fix** | Fix the role or the inventory value that the failed task names, then run `task e2e:local` again. |

## Failure: a Molecule scenario leaves containers behind

| | |
|---|---|
| **Meaning** | `task molecule` or `molecule test` was interrupted before its last destroy step. |
| **Impact** | The instances `lab-<role>-debian13` and `lab-<role>-ubuntu2404` keep running; the next run of the same role destroys them first, so it is not blocked. |
| **Diagnosis** | `docker ps -a --filter name=lab-docker- --filter name=lab-monitoring- --filter name=lab-deploy_target-`. |
| **Mitigation** | In `ansible/roles/<role>`, with `MOLECULE_ROLE=<role>`: `molecule destroy`. |
| **Fix** | Nothing else; the scenarios keep no state outside their instances. |

## Failure: containers lose their network after a firewall change

| | |
|---|---|
| **Meaning** | On a Docker host, containers cannot reach the outside, or published ports stop answering, after `nftables.service` was restarted (its `flush ruleset` also removes Docker's rules). |
| **Impact** | Services in containers (for example Uptime Kuma) cannot check anything; ports published on a private address are unreachable. |
| **Diagnosis** | `nft list tables` shows no `ip nat` table of Docker; `systemctl show docker -p PartOf` does not list `nftables.service` (the role ran with `docker_restart_with_nftables: false`), or `/etc/nftables.d/60-docker.nft` is missing. `journalctl -u docker` with `Start request repeated too quickly` means more firewall restarts within a minute than `systemctl show docker -p StartLimitBurst` allows (the role's drop-in allows 10). |
| **Mitigation** | `systemctl restart docker` (with live restore the containers keep running). |
| **Fix** | Run the docker role with `docker_restart_with_nftables: true` (the default) and with the base role's `/etc/nftables.d` in place, so the drop-ins are written ([ADR 0019](adr/0019-docker-ports-on-loopback-and-a-firewall-that-restarts-docker.md)). |

## Procedure: create the Uptime Kuma monitors

1. Open Uptime Kuma through its tunnel hostname (or an SSH port forward to
   `127.0.0.1:3001`) and create the admin account on the first visit; keep its password in the
   password manager.
2. Read `/etc/uptime-kuma/monitors.md` on the monitoring host (`sudo cat`). For each row, choose
   "Add New Monitor", the monitor type of the row, and copy name, target, accepted status codes,
   interval and the "upside down" setting.
3. Under Settings, Notifications, add the notification channel and attach it to every monitor.
4. Stop one watched service for a moment and check that the alert arrives, then that it clears.

Repeat steps 2 and 3 after a change of `monitoring_monitors` or `monitoring_external_probes`; the
checklist does not track monitors that were changed in the web interface
([ADR 0018](adr/0018-uptime-kuma-monitors-as-a-checklist.md)).

## Procedure: upgrade node_exporter or Uptime Kuma

1. node_exporter: read the new release's `sha256sums.txt`, then change
   `monitoring_node_exporter_version` and both values of `monitoring_node_exporter_checksums` in
   the role defaults (or the inventory) and in [toolchain.md](toolchain.md).
2. Uptime Kuma: stop the container and back up its data volume first, for example with the
   BusyBox image that the docker role's tests use:

   ```bash
   docker stop uptime-kuma
   docker run --rm -v uptime-kuma-data:/data:ro -v "$PWD":/backup \
     busybox:1.37@sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e \
     tar -czf /backup/uptime-kuma-data.tgz -C /data .
   ```

   Then change `monitoring_uptime_kuma_image` to the new tag and its digest
   (`docker buildx imagetools inspect louislam/uptime-kuma:<tag>` shows the digest).
3. Run the role; it restarts node_exporter and recreates the container with the same volume.
   Roll back the same way with the old values.

## Failure: the deploy path unit no longer starts the deploy

| | |
|---|---|
| **Meaning** | An upload with its `.ready` marker stays in the spool directory; `systemctl status luminare-deploy.path` shows `failed` with `unit-start-limit-hit` or `trigger-limit-hit`. |
| **Impact** | No deploy runs until the units are reset. |
| **Diagnosis** | `journalctl -u luminare-deploy.service` shows the script's output. A marker the script did not delete makes the path unit start the service again and again until systemd stops it. `ls -l /srv/luminare/incoming` shows files that the game server user cannot read (mode `0600`, uploaded without `--chmod=F640`). |
| **Mitigation** | Move the leftover files out of the spool directory, then `systemctl reset-failed luminare-deploy.service luminare-deploy.path` and `systemctl restart luminare-deploy.path`. |
| **Fix** | Make the deploy script delete every marker it has handled, also after a failure, and make the uploader send group-readable files. |

## Procedure: rotate or revoke an upload key

1. Add the new public key to `deploy_target_authorized_keys` next to the old one and run the role.
2. Change the private key in the CI secrets and check one upload.
3. Remove the old key from the list and run the role again; `authorized_keys` then holds exactly
   the remaining keys. To revoke a leaked key at once, skip steps 1 and 2.
