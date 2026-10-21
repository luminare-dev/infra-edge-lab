# 0020. An upload-only deploy key and a path unit

- **Status:** accepted
- **Date:** 2026-10-21

## Context

A release pipeline must deliver builds to a staging or showcase game server. The CI job reaches
the host over SSH (through a tunnel with access control) with a key that is stored in CI, so the
key must be able to do as little as possible. The deploy itself (checking the archive, unpacking
it, switching the release, a reload) runs on the host as the game server user. The pipeline sends
the archive and its checksum first and an empty marker file last. The game server role of
`luminare.gameserver` runs the server as the user and group `fxserver`.

## Considered options

1. An account whose keys may only run `rrsync -wo -no-del <spool>` (`restrict` plus a forced
   command), and a systemd path unit with `PathExistsGlob=<spool>/*.ready` that starts the deploy
   script as the game server user.
2. SSH with a forced command that runs the deploy script directly, with the archive on standard
   input.
3. A pull model: the host downloads releases on a timer.

## Decision

Chosen option: 1.

- The upload account has the login shell `/bin/sh` (sshd runs the forced command through it;
  `nologin` would block it), the password field `*`, no sudo rights and exactly the groups in
  `deploy_target_ssh_groups` (`sshusers`, which the base role's `AllowGroups` requires).
  `authorized_keys` belongs to root and holds exactly the configured keys; each gets `restrict`,
  the forced command and optionally `from=`.
- The spool directory is `deploy:fxserver` with mode `2770`: the upload account writes, the game
  server user reads and deletes the processed files, and uploaded files inherit the group. The
  uploader sends them group-readable.
- `PathExistsGlob` (not `PathChanged`) starts the service only while a marker exists, so a
  half-written upload never starts a deploy.
- `luminare-deploy.service` runs as `fxserver` without privileges and may write only to the spool
  directory, the release root and listed paths. The deploy script is installed from a file of
  the release pipeline and gets its settings as environment variables.

Option 2 lets the key start the deploy logic with input it controls, as the user the deploy
needs. Option 3 needs credentials for the release store on the game server and delays deploys.

## Consequences

- Good: a stolen key can write files into one folder and nothing else; the deploy script runs
  with a fixed environment and checks the upload.
- Bad: the deploy script must delete every marker it has processed, or the path unit starts it
  again until systemd's start limit stops it.
- Bad: the uploader must send group-readable files; a file sent with mode `0600` cannot be read
  by the deploy script.
