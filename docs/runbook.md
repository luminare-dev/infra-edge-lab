# Runbook

Failures and procedures for the environments, the cloud workflows and the services of the roles
in `ansible/roles`. The collections have runbooks of their own.

| Situation | Go to |
|---|---|
| Rebuild an environment from nothing | [Procedure: rebuild an environment from nothing](#procedure-rebuild-an-environment-from-nothing) |
| Prove that the backups can be restored | [Procedure: test a restore](#procedure-test-a-restore) |
| Nobody can log in to a host any more | [Failure: locked out of a host](#failure-locked-out-of-a-host) |
| A published hostname does not answer | [Failure: a hostname of the tunnel does not answer](#failure-a-hostname-of-the-tunnel-does-not-answer) |
| The nightly drift check opened an issue | [Failure: an issue `Drift detected: <env>`](#failure-an-issue-drift-detected-env) |
| The tunnel test failed | [Failure: the tunnel test fails](#failure-the-tunnel-test-fails) |

## Failure: the zone guard rejects a name or a record

| | |
|---|---|
| **Meaning** | `tofu test` or `tofu plan` fails with a validation error of `cf_tunnel` or `cf_access_app`, for example "Every dns_names entry must be a first-level label with the prefix of env". |
| **Impact** | Nothing reaches Cloudflare: the plan stops before any API call. This is the guard working. |
| **Diagnosis** | The error names the variable. Compare the name with the rules in the [cf_tunnel README](../tofu/modules/cf_tunnel/README.md#name-rules): prefix of the environment, first level only, lower case, not reserved; A/AAAA records in `showcase` only. |
| **Mitigation** | Use a name with the environment's prefix (`lab-`, `demo-`, `show-`). |
| **Fix** | Change the name, never the guard. A change of the rules themselves needs new tests in both modules. |

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
OpenTofu merges with `encryption.tofu`); nothing is committed.

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
| **Fix** | Only when no run is active: `tofu -chdir=tofu/envs/<env> force-unlock <lock ID>`. Whether R2 enforces the lock is not tested yet; until it is, only one operator applies at a time. |

## Failure: an environment plans against the wrong state

| | |
|---|---|
| **Meaning** | `task plan ENV=<env>` prints `note: <env> plans against its local state file`, or proposes to create resources that exist. |
| **Impact** | A plan against an empty local state would create a second copy of every resource if applied. |
| **Diagnosis** | `ls tofu/envs/<env>/backend_override.tf`: the file is there after `task init ENV=<env> BACKEND=local`. |
| **Mitigation** | Do not apply that plan. |
| **Fix** | `task init ENV=<env>` (without `BACKEND=local`) removes the override file and switches back to the remote state. |

## Procedure: rebuild an environment from nothing

1. For `lab` and `demo`, have an age key for the zone copy: `task up` runs `task preflight` and
   `task dns-backup` before its apply and stops if either fails.
2. Install the collections once: `task collections` (again after a change of their tags, see
   [upgrade.md](upgrade.md#the-pinned-collections)).
3. `task rebuild ENV=<env>`: destroy, then init, apply, inventory, configure and smoke; it prints
   how long it took. `lab` and `demo` ask before the destroy and the apply unless
   `AUTO_APPROVE=1`; `local` needs `TF_VAR_state_passphrase` (a new random one when nothing of
   it exists). `showcase` is refused: it is taken down by hand only.
4. Read the smoke test at the end: every nginx site 200, MariaDB `SELECT 1`, `/info.json` with
   the build, every Prometheus target up.

`task e2e:local` does the same for `local` with a random passphrase, runs the playbook twice,
plans again, backs up and restore-tests every host, and always destroys at the end (about 15 minutes).

The GIF at the top of the README is an asciinema recording of that run (`docs/media/e2e-local.cast`,
converted with agg). Before committing a new one, remove the `command` field of the cast's first
line and check that no real host name, address or secret is visible.

## Procedure: test a restore

Every host backs up `/etc` and `/var/backups` (the database dumps and the game server backups)
with restic every night at 03:45, after the database dumps at 03:15. A backup counts only once a
restore has worked.

1. Run `task restore-test ENV=<env>` (`ansible/playbooks/restore_test.yml`). On every host,
   `/usr/local/sbin/restic-restore-test` restores the newest snapshot into a new folder under
   `/var/tmp`, compares every file, folder and link with the snapshot, prints the counts, the bytes
   and how long the restore took, removes the folder and ends with `passed`. It fails when the
   newest snapshot is older than 26 hours (`restic_backup_max_age_hours`): the nightly backup did
   not run. With `BACKUP_NOW=1` the hosts first take the database dumps and a backup, as
   `task e2e:local` does in its last step; without it the test checks the nightly backup.
2. Write down the time of the restore (how long a host takes to restore) and the age of the
   newest snapshot (how much data a loss would cost) with the date.
3. To bring back data for real, restore into a folder first and copy from there, as root on the
   host: `restic-env restore latest --target /var/tmp/restore --include /var/backups/mariadb`. A
   database comes back from its dump:
   `zstd -dc /var/tmp/restore/var/backups/mariadb/<database>-<time>.sql.zst | mariadb`.

By hand on one host (for `local` prefix each command with `docker exec lab-local-<host>`): on a
database host first `systemctl start mariadb-dump.service`, then `systemctl start
restic-backup.service`, `journalctl -u restic-backup.service -n 20`, `restic-env snapshots` and
`/usr/local/sbin/restic-restore-test`.

**Recovery point and recovery time.** With one backup a night, a loss costs at most the changes
of the last 24 hours (the recovery point); the restore test fails once the newest snapshot is 26
hours old. The recovery time is a rebuild of the environment plus the restore of its data: for
`local`, `task e2e:local` builds and configures the three hosts in about 8 minutes, and the restore
of each host's snapshot takes about a second. The repository of `local` and `demo`
is a folder on the host itself: the test proves the jobs and the restore, not an off-host copy.

## Failure: locked out of a host

| | |
|---|---|
| **Meaning** | SSH refuses the admin and the automation user (`Permission denied (publickey)`, a timeout, or `Connection closed`), so neither a person nor Ansible gets in. Typical causes: a key list without the current key (the base role replaces all keys), a wrong `base_mgmt_cidrs` or `base_ssh_allow_mode`, a ban by fail2ban, or, in `demo` and `showcase`, a tunnel that no longer carries `<env>-ssh`. |
| **Impact** | `task configure` and the `apply` workflow cannot change the host; the services on it keep running. |
| **Diagnosis** | `ssh -v` shows how far the login gets: no answer at all (firewall, tunnel), a refused key (key list, `AllowGroups`), or a closed connection (fail2ban). For `demo` and `showcase`, check the tunnel first ([next failure](#failure-a-hostname-of-the-tunnel-does-not-answer)). |
| **Mitigation** | Get a root shell without SSH: `local` and the container of the tunnel test: `docker exec -it lab-local-<host> bash` (Ansible itself uses this, so `local` cannot lock Ansible out). `lab`: on the Proxmox VE host, `qm guest exec <vmid> -- <command>` runs a command as root through the guest agent (installed in the template, enabled by `pve_vm`), or open the virtual machine's console (`lab-pve` behind Access) and log in as the admin user, which needs `base_admin_password_hash` to be set. `demo`: nothing on it outlives it: `task rebuild ENV=demo`. `showcase`: the cloud server's web console in the Hetzner Cloud Console with the admin password; as a last resort the provider's rescue system, which needs an SSH rule in the cloud firewall for the time of the repair (`drift` reports that rule until it is gone). |
| **Fix** | With the root shell: `systemctl stop nftables` opens the firewall until the next run; `fail2ban-client status sshd` and `fail2ban-client unban <address>`; `sshd -T` shows what SSH enforces; add the missing key to the user's `~/.ssh/authorized_keys`. Then correct the inventory (`base_admin_ssh_keys`, `base_automation_ssh_keys`, `base_mgmt_cidrs`, `base_ssh_allow_mode`) and run `task configure ENV=<env>`; it replaces the manual changes. The base role's README in `luminare.infra_edge` describes the same steps. |

## Failure: a hostname of the tunnel does not answer

| | |
|---|---|
| **Meaning** | A hostname of `lab`, `demo` or `showcase` shows a Cloudflare error page (error 1033 or 1016: no connector of the tunnel is connected, or the name does not lead to a live tunnel; 502: the connector cannot reach the origin), the tunnel is listed as down or degraded in the Zero Trust dashboard (Networks, Tunnels), or Ansible cannot reach `<env>-ssh`. |
| **Impact** | Every hostname of the environment is affected when the connector is down; one hostname when only its origin is. A people's hostname that asks for a login works: that is Access, not a failure. |
| **Diagnosis** | On the edge host: `systemctl status cloudflared` and `journalctl -u cloudflared -n 50`; `curl -s http://127.0.0.1:2000/ready` answers 200 with the number of connections, 503 with none. `Unauthorized` or `token` in the journal: the token was rotated or the tunnel was replaced. Connection errors to port 7844: outbound traffic to Cloudflare's edge is blocked (QUIC uses UDP, HTTP/2 uses TCP). A 502 for one hostname: check its origin on the host itself (for example `curl -sI http://127.0.0.1:8080/` for the web server) and its rule in the `ingress` output. The tunnel that the dashboard shows must be the one in the `tunnel_id` output (`sops exec-env secrets/<env>.enc.env 'tofu -chdir=tofu/envs/<env> output tunnel_id'`). |
| **Mitigation** | `demo`: `task rebuild ENV=demo`. Other environments: restart the connector (`systemctl restart cloudflared`) and check `/ready` again. |
| **Fix** | A rotated or replaced token: `task configure ENV=<env>` fetches the current token and writes it to the host. Blocked UDP: add `--protocol http2` to `cloudflared_extra_args` in the inventory and configure again. A wrong origin: fix the ingress rule in `tofu/envs/<env>/main.tf` or the service on the host, then apply or configure through a pull request. A tunnel deleted outside this code: `task plan ENV=<env>` shows it as missing; apply to create it again, then configure. |

## Failure: the e2e run or the smoke test fails

| | |
|---|---|
| **Meaning** | `task e2e:local` (or the CI job `e2e-local`) ends with `Result: failed at "<step>"`, or `task smoke` fails a check. |
| **Impact** | The change is not proven to rebuild the environment; the e2e run has already destroyed its containers. |
| **Diagnosis** | The step names the cause: `tofu apply` (Docker, the host image), `collections` (the git tags, see [troubleshooting](troubleshooting.md)), `configure` (the failed task and host in the log; set `E2E_LOG_DIR` to keep both playbook logs), `second run` (a task that is not idempotent), `tofu plan` (a resource that drifts after its apply), `smoke` (the check and host). To look inside, run the steps one by one: `task up ENV=local`, then `docker exec lab-local-<host> journalctl -u <service>`. |
| **Mitigation** | `task destroy ENV=local` with the same `TF_VAR_state_passphrase` removes what a manual run left. |
| **Fix** | Fix the role or the inventory value that the failed task names, then run `task e2e:local` again. |

## Procedure: set up the Proxmox VE users of the lab

The lab's API tokens get only what the lab needs. Run once as root on the
Proxmox VE 9 host, after the template (VM ID 9000) exists; `<node>` is the node name
(`TF_VAR_node_name`). This procedure has not been run for this version: no Proxmox VE host was
used.

1. Pool and template: `pveum pool add lab`, then `pveum pool modify lab --vms 9000`.
2. Role and users:

   ```bash
   pveum role add TofuProvisioner -privs "VM.Allocate VM.Audit VM.Clone VM.Config.CDROM VM.Config.CPU VM.Config.Cloudinit VM.Config.Disk VM.Config.HWType VM.Config.Memory VM.Config.Network VM.Config.Options VM.PowerMgmt VM.GuestAgent.Audit Datastore.AllocateSpace Datastore.Audit SDN.Use Sys.Audit Pool.Audit"
   pveum user add tofu@pve
   pveum user add ci-plan@pve
   pveum user token add tofu@pve iac --privsep 1
   pveum user token add ci-plan@pve plan --privsep 1
   ```

   Each `token add` prints the token secret once: put `tofu@pve!iac=<secret>` into
   `secrets/lab.enc.env` and `ci-plan@pve!plan=<secret>` into `secrets/lab-ci.enc.env` as
   `PROXMOX_VE_API_TOKEN` (`sops edit`).
3. Grant the role to each user and its token on the four paths, never on `/`:

   ```bash
   for path in /pool/lab /storage/local-lvm /sdn/zones/localnetwork /nodes/<node>; do
     pveum acl modify "$path" --roles TofuProvisioner --users tofu@pve --tokens 'tofu@pve!iac'
     pveum acl modify "$path" --roles PVEAuditor --users ci-plan@pve --tokens 'ci-plan@pve!plan'
   done
   ```

4. Check: `pveum user permissions tofu@pve` lists the privileges per path, and
   `task plan ENV=lab` with the plan token shows the machines without an error. A `403` in a
   later apply names the missing privilege: add it to the role.

## Procedure: turn on the cloud workflows

The workflows `plan`, `apply`, `drift` and `e2e-tunnel` are skipped until the repository variable
`CLOUD_ENVS_ENABLED` is `true`.
Before setting it (Settings, Secrets and variables, Actions, Variables):

1. Create one age key per GitHub environment (`age-keygen`), keep each private key only in that
   environment's secret `SOPS_AGE_KEY`, and add its public key to the creation rules of
   `.sops.yaml` for the files that environment may read ([secrets/README.md](../secrets/README.md)).
2. Create the GitHub environments (Settings, Environments):
   - `lab-plan`: no reviewer, any branch; reads `secrets/lab-ci.enc.env`, `secrets/demo-ci.enc.env`
     and `secrets/showcase-ci.enc.env` (read-only tokens, the state passphrase, a read-only R2 key).
   - `demo` and `showcase`: required reviewer (yourself), "Prevent self-reviews" off, branch `main`
     only; read `secrets/demo.enc.env` or `secrets/showcase.enc.env` (write credentials).
   - `demo-e2e`: no reviewer, branch `main` only; reads `secrets/demo-e2e.enc.env`, which holds a
     Cloudflare token with the permissions that `task preflight ENV=demo` prints (one zone, one
     account) and the account, zone and team values, but no cloud server token.
3. Commit the encrypted files (`sops edit secrets/<file>`); an environment without its `-ci`
   file is skipped by `plan` and `drift` with a notice. For the configure step of `apply`, put
   the private key of `TF_VAR_ssh_public_key` into `secrets/demo.enc.env` and
   `secrets/showcase.enc.env` as `SSH_PRIVATE_KEY_B64` (`base64 -w0 <key file>`, one line): the
   job reaches the server through `demo-ssh` or `show-ssh` with it.
4. Set `CLOUD_ENVS_ENABLED` to `true`, then run `e2e-tunnel` and `plan` once on demand.
5. Once a month, open the Actions tab: GitHub turns off scheduled workflows of a public repository
   after 60 days without activity; "Enable workflow" turns `drift` and `e2e-tunnel` on again.

## Procedure: restore DNS records from a zone copy

`task dns-backup ENV=<env>` (and `task up`) writes `backups/dns/<UTC time>.zone.age`, the zone
file of the whole zone, encrypted for the operator's age key.

1. Decrypt it into the terminal only: `age --decrypt --identity ~/.config/sops/age/keys.txt
   backups/dns/<file>.zone.age | less`; never write the clear text into the repository.
2. Find the lines of the records that changed; `task preflight ENV=<env>` and the comparison of
   the workflows name them.
3. Put back each record by hand in the Cloudflare dashboard (DNS, Records), or import the lines
   that are missing (DNS, Records, Import and Export); an import adds records and never deletes
   one, so first remove a wrong record with the same name.
4. Run `task preflight ENV=<env>` again and `dig +short` the names that changed.

## Procedure: remove left-over demo objects

An interrupted run can leave Access applications, policies, service tokens, DNS records and a
tunnel named `demo-*` in Cloudflare. `drift` reports them every night.

1. Make sure no demo is in use: no `apply` of `demo` and no `e2e-tunnel` run is active, and no
   cloud server labelled `env=demo` should stay.
2. `task sweep:demo` lists what it would delete; a tunnel with a connector is never deleted (stop
   its connector first).
3. `task sweep:demo -- --delete` deletes the listed objects, applications first and tunnels last.
4. After an interrupted `task e2e:tunnel` on a workstation, `bash scripts/e2e_tunnel.sh cleanup`
   removes its containers and sweeps only what that run created.

## Failure: the preflight refuses an apply

| | |
|---|---|
| **Meaning** | `task preflight`, `task up`, the `apply` workflow or `task e2e:tunnel` stops with `preflight: refused:`. |
| **Impact** | Nothing was applied. The guard stopped a write into the shared zone. |
| **Diagnosis** | The line names the reason: a permission that a read cannot show (the token lacks it), `TF_VAR_zone_id does not belong to TF_VAR_zone` (wrong ID in the SOPS file), a record under the prefix without the comment `managed-by-tofu env=<env>` (made by hand), a name the plan would create that exists already (a running or left-over environment), or a plan that would touch a name outside the prefix. |
| **Mitigation** | Leave the zone as it is. |
| **Fix** | Correct the token or the IDs in the SOPS file; destroy the running environment or remove left-over demo objects (procedure above); rename or remove a record made by hand only after checking who uses it. Never weaken the check. |

## Failure: the tunnel test fails

| | |
|---|---|
| **Meaning** | The workflow `e2e-tunnel` (or `task e2e:tunnel`) ends with `Result: failed at "<step>"`. |
| **Impact** | The run has destroyed its container and swept what it created; the zone comparison at the end shows whether any record outside `demo-*` changed (it must not). |
| **Diagnosis** | The step names the cause: `preflight` (token, zone, left-overs), `tofu apply` (the Cloudflare API refused an attribute), `configure` (the role and host in the log), `tunnel connected` (the connector on the host reached no Cloudflare edge: it needs outbound port 7844, TCP or UDP), `demo-web through Access` (the HTTP status of each attempt; 200 without the marker means another site answered), `SSH through demo-ssh`, `sweep` (an object that could not be deleted). |
| **Mitigation** | Run `bash scripts/e2e_tunnel.sh cleanup` (in CI it runs as the last step) and `task sweep:demo`. |
| **Fix** | Fix the module, role or value that the step names, then run the test again on demand. |

## Failure: an issue `Drift detected: <env>`

| | |
|---|---|
| **Meaning** | The nightly `drift` workflow found a change between the code and the environment, a running cloud server labelled `env=demo`, or left-over `demo-*` objects. |
| **Impact** | The next apply would change the resources that the issue lists. |
| **Diagnosis** | The issue and the job summary list resources by address only. Plan the environment locally (`task plan ENV=<env>`) to see the attributes. |
| **Mitigation** | Do not apply until the cause is known. |
| **Fix** | Undo a change made by hand by applying the code, or put the change into the code and apply it through a pull request; destroy a forgotten demo (`task destroy ENV=demo`) and remove left-overs. Close the issue when the next nightly run is clean. |

## Failure: containers lose their network after a firewall change

| | |
|---|---|
| **Meaning** | On a Docker host, containers cannot reach the outside, or published ports stop answering, after `nftables.service` was restarted (its `flush ruleset` also removes Docker's rules). |
| **Impact** | Services in containers (for example Uptime Kuma) cannot check anything; ports published on a private address are unreachable. |
| **Diagnosis** | `nft list tables` shows no `ip nat` table of Docker; `systemctl show docker -p PartOf` does not list `nftables.service` (the role ran with `docker_restart_with_nftables: false`), or `/etc/nftables.d/60-docker.nft` is missing. `journalctl -u docker` with `Start request repeated too quickly` means more firewall restarts within a minute than `systemctl show docker -p StartLimitBurst` allows (the role's drop-in allows 10). |
| **Mitigation** | `systemctl restart docker` (with live restore the containers keep running). |
| **Fix** | Run the docker role with `docker_restart_with_nftables: true` (the default) and with the base role's `/etc/nftables.d` in place, so the drop-ins are written. |

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
checklist does not track monitors that were changed in the web interface.

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
