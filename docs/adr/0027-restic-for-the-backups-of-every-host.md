# 0027. restic for the backups of every host, instead of hypervisor snapshots or BorgBackup

- **Status:** accepted
- **Date:** 2026-10-22

## Context

The hosts hold data that a rebuild cannot recreate: the database dumps, the game server's data
and its own backups, and the configuration under `/etc`. A rebuilt environment is only as good as
its last restorable backup. The environments run on different substrates (containers, Proxmox VE,
cloud servers), and the planned off-host target is an S3-compatible bucket (the bucket
`luminare-backups` of plan 09), which does not exist yet.

## Considered options

1. restic on every host, through the `restic_backup` role of `luminare.infra_edge`.
2. BorgBackup on every host.
3. Snapshots or backups of the substrate only (Proxmox VE backup jobs, cloud server backups).

## Decision

Chosen option: 1, because restic encrypts on the host before anything leaves it, writes to S3,
SFTP, REST and local backends alike, and the role already brings timers, retention, a monthly
check, a status metric and a restore test.

- `site.yml` runs `luminare.infra_edge.restic_backup` on every host as the last play, after the
  roles that write what it backs up: the role's default paths `/etc` and `/var/backups` hold the
  database dumps of the `mariadb` role and the game server backups of the `fxserver` role.
- Each host has its own repository and password; the repository, the password and the backend
  credentials are inventory values, kept in `*.sops.yaml` files for real environments
  ([ADR 0006](0006-sops-and-age-for-secrets.md)) and never committed in clear text.
- `local` and `demo` write to `/srv/restic-repo` on the host itself, with a password generated
  into the git-ignored `.generated/` folder: enough to test the jobs and the restore, not a backup.
- The time of the last successful backup is exported through node_exporter's textfile collector
  (`restic_backup_last_success_timestamp_seconds`), and `/usr/local/sbin/restic-restore-test` on
  each host restores the newest snapshot and compares it with the snapshot listing
  ([runbook](../runbook.md#procedure-test-a-restore)).
- Substrate snapshots stay optional: they restore a whole machine, not single files, and they
  live with the machine they protect.

## Consequences

- Good: the same role and the same restore test on every substrate; the storage provider sees
  ciphertext only.
- Bad: no off-host repository was used for this version (no bucket); the backups of `local` and
  `demo` disappear with their hosts.
- Bad: a lost repository password means lost backups; it is kept in the SOPS file and offline.
- Recovery point: one backup a night, so a loss costs at most the changes of the last 24 hours;
  `restic-restore-test` fails once the newest snapshot is older than 26 hours. Recovery time: a
  rebuild of the environment plus the restore of its data, measured for `local` by
  `task e2e:local`, whose last step backs up and restores every host (README, Results;
  `task restore-test ENV=<env>` runs the same test on any environment).
